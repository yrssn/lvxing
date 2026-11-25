"""独立厦航任务队列，既不调用也不改变九旅行的调度器。"""
import asyncio
from datetime import datetime, timedelta

from models import XiamenTask, XiamenTaskLog
import xiamenair

_loop_task = None
_jobs = {}
_execution_lock = asyncio.Lock()
ACTIVE = ("queued", "running", "stopping")


def next_time(task, now=None):
    now = now or xiamenair.now_cn()
    candidate = datetime.combine(now.date(), task.time_of_day)
    if candidate <= now:
        candidate += timedelta(days=task.interval_days)
    return candidate


def task_dates(task, today=None):
    today = today or xiamenair.now_cn().date()
    if task.window_mode == "fixed":
        start, end = task.fixed_date_from, task.fixed_date_to or task.fixed_date_from
    else:
        start = today + timedelta(days=task.days_ahead)
        end = start + timedelta(days=task.days_count - 1)
    # 固定日期监控自动跳过已过期的航班日期。
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if start + timedelta(days=i) >= today]


def stop_requested(task_id):
    from db import SessionLocal
    with SessionLocal() as db:
        task = db.get(XiamenTask, task_id)
        return not task or bool(task.stop_requested)


def enqueue(task_id, trigger="manual"):
    from db import SessionLocal
    with SessionLocal() as db:
        count = db.query(XiamenTask).filter(XiamenTask.id == task_id, XiamenTask.status == "idle").update(
            {"status": "queued", "stop_requested": 0})
        db.commit()
    if not count:
        return False
    job = asyncio.create_task(run_task(task_id, trigger))
    _jobs[task_id] = job
    def forget(finished):
        if _jobs.get(task_id) is finished:
            _jobs.pop(task_id, None)
    job.add_done_callback(forget)
    return True


async def run_task(task_id, trigger):
    from db import SessionLocal
    log_id = None
    status, message, detail = "success", "", []
    completed = offer_count = total = 0
    # 日志在进入队列时建立，排队任务也能查看状态。
    with SessionLocal() as db:
        task = db.get(XiamenTask, task_id)
        if not task:
            return
        log = XiamenTaskLog(task_id=task_id, trigger_type=trigger, status="queued",
                           message="已排队，等待其他厦航任务完成", started_at=xiamenair.now_cn())
        db.add(log)
        db.commit()
        log_id = log.id

    def progress(text):
        with SessionLocal() as db:
            log = db.get(XiamenTaskLog, log_id)
            log.message = text[:500]
            db.commit()

    try:
        while _execution_lock.locked():
            if stop_requested(task_id):
                raise xiamenair.CollectionStopped("已取消排队，未发送请求", "cancelled")
            await asyncio.sleep(1)
        async with _execution_lock:
            if stop_requested(task_id):
                raise xiamenair.CollectionStopped("已取消排队，未发送请求", "cancelled")
            with SessionLocal() as db:
                task = db.get(XiamenTask, task_id)
                task.status = "running"
                task.last_run_at = xiamenair.now_cn()
                dates = task_dates(task)
                routes = list(task.routes)
                total = len(routes) * len(dates)
                log = db.get(XiamenTaskLog, log_id)
                log.status, log.total = "running", total
                db.commit()
                # expire_on_commit=False，复制执行配置后关闭连接。
                mf_only, lo, hi = bool(task.mf_only), task.min_delay_sec, task.max_delay_sec
            if not dates:
                message = "固定日期段已结束，任务已自动停用"
                with SessionLocal() as db:
                    task = db.get(XiamenTask, task_id)
                    task.enabled = 0
                    db.commit()
            if total > xiamenair.MAX_TASK_REQUESTS:
                raise xiamenair.CollectionStopped("本次任务超过 200 次查询上限，请缩小日期或航线范围", "configuration")
            for flight_date in dates:
                for route in routes:
                    if stop_requested(task_id):
                        raise xiamenair.CollectionStopped("已停止；已完成的数据保留", "cancelled")
                    prefix = f"{completed + 1}/{total} {route['dpt']}→{route['arr']} {flight_date}："
                    item = {"dpt": route["dpt"], "arr": route["arr"], "flightDate": str(flight_date)}
                    try:
                        result = await xiamenair.collect(
                            route["dpt"], route["arr"], flight_date, mf_only, task_id, lo, hi,
                            stopped=lambda: stop_requested(task_id), progress=lambda msg: progress(prefix + msg))
                    except xiamenair.CollectionStopped as e:
                        item["error"] = str(e)
                        detail.append(item)
                        raise
                    completed += 1
                    offer_count += result["rowCount"]
                    item.update(queryId=result["queryId"], rowCount=result["rowCount"], cached=result["cached"])
                    detail.append(item)
                    with SessionLocal() as db:
                        log = db.get(XiamenTaskLog, log_id)
                        log.completed, log.offer_count, log.detail = completed, offer_count, list(detail)
                        log.message = prefix + result["message"]
                        db.commit()
            if not message:
                message = f"完成 {completed}/{total} 次查询，获得 {offer_count} 条优惠（含复用缓存）"
    except xiamenair.CollectionStopped as e:
        status = "cancelled" if e.kind == "cancelled" else "blocked"
        message = str(e)
        if e.kind in ("session", "risk", "schema", "configuration"):
            with SessionLocal() as db:
                task = db.get(XiamenTask, task_id)
                task.enabled = 0
                db.commit()
            message += "；任务已停用，处理后手动启用"
    except asyncio.CancelledError:
        status, message = "interrupted", "服务停止，任务已暂停；已完成的数据保留，请检查后重新启用"
        with SessionLocal() as db:
            task = db.get(XiamenTask, task_id)
            if task:
                task.enabled = 0
                db.commit()
        raise
    except Exception as e:
        # 不打印外部请求头、Cookie、SQL 参数或原始响应。
        status, message = "failed", "内部处理失败，任务已停止（" + type(e).__name__ + "）"
    finally:
        with SessionLocal() as db:
            log = db.get(XiamenTaskLog, log_id)
            if log:
                log.status, log.message, log.detail = status, message, list(detail)
                log.completed, log.offer_count = completed, offer_count
                log.finished_at = xiamenair.now_cn()
            task = db.get(XiamenTask, task_id)
            if task:
                task.status, task.stop_requested, task.last_status = "idle", 0, status
                if trigger == "schedule" or not task.enabled:
                    task.next_run_at = next_time(task) if task.enabled else None
            db.commit()


async def loop():
    from db import SessionLocal
    while True:
        try:
            with SessionLocal() as db:
                ids = [row[0] for row in db.query(XiamenTask.id).filter(
                    XiamenTask.enabled == 1, XiamenTask.status == "idle",
                    XiamenTask.next_run_at <= xiamenair.now_cn()).order_by(XiamenTask.next_run_at).all()]
            for task_id in ids:
                enqueue(task_id, "schedule")
        except Exception as e:
            print("[xiamenair] 调度检查失败:", type(e).__name__)
        await asyncio.sleep(15)


def start():
    global _loop_task
    from db import SessionLocal
    with SessionLocal() as db:
        db.query(XiamenTask).filter(XiamenTask.status.in_(ACTIVE)).update(
            {"status": "idle", "enabled": 0, "next_run_at": None, "stop_requested": 0, "last_status": "interrupted"})
        db.query(XiamenTaskLog).filter(XiamenTaskLog.status.in_(ACTIVE)).update(
            {"status": "interrupted", "message": "服务重启中断，请检查已采集记录后手动启用任务", "finished_at": xiamenair.now_cn()})
        db.commit()
    _loop_task = asyncio.create_task(loop())


async def stop():
    global _loop_task
    jobs = list(_jobs.values()) + ([_loop_task] if _loop_task else [])
    for job in jobs:
        job.cancel()
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)
    _loop_task = None
