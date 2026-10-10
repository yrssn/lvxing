# -*- coding: utf-8 -*-
"""定时任务调度器：asyncio 轮询（30s tick），无第三方依赖。

- next_run_at 为调度依据；advance() 以旧值为锚点推进，保证「隔天」语义不漂移
- DB CAS 抢占（status idle->running）防双跑；启动时复位残留的 running
- 任务内多条参数之间随机延时，Cookie 失效立即熔断
"""
import asyncio
import random
from datetime import datetime, time as time_type, timedelta

from models import QueryParam, ScrapeTask, TaskParam, TaskRunLog

TICK_SECONDS = 30

_loop_task: asyncio.Task = None


def advance(old_next: datetime, now: datetime, interval_days: int, time_of_day: time_type) -> datetime:
    """推进到严格大于 now 的下一个执行点（old_next 为锚点，补跑/宕机多天也能追上）"""
    candidate = old_next or datetime.combine(now.date(), time_of_day)
    while candidate <= now:
        candidate = datetime.combine(candidate.date() + timedelta(days=interval_days), time_of_day)
    return candidate


def compute_initial_next_run(interval_days: int, time_of_day: time_type) -> datetime:
    """创建/启用/修改任务时：今天的时刻未过则今天，否则顺延"""
    return advance(None, datetime.now(), interval_days, time_of_day)


def startup_reset():
    """复位崩溃/强杀残留的 running 状态"""
    from db import SessionLocal

    db = SessionLocal()
    try:
        n = (
            db.query(ScrapeTask)
            .filter(ScrapeTask.status == "running")
            .update({"status": "idle"})
        )
        db.commit()
        if n:
            print(f"[scheduler] 复位 {n} 个残留 running 任务")
    except Exception as e:
        print(f"[warn] 启动复位失败: {e}")
    finally:
        db.close()


def claim_task(task_id: int) -> bool:
    """CAS 抢占：idle -> running，成功返回 True（防双跑）"""
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = (
            db.query(ScrapeTask)
            .filter(ScrapeTask.id == task_id, ScrapeTask.status == "idle")
            .update({"status": "running", "last_run_at": datetime.now()})
        )
        db.commit()
        return row == 1
    finally:
        db.close()


async def run_task(task_id: int, trigger: str = "schedule"):
    """执行一个任务：逐条抓取关联参数并入库，写执行日志。schedule 触发时推进 next_run_at。"""
    import scraper
    from db import SessionLocal

    db = SessionLocal()
    try:
        task = db.get(ScrapeTask, task_id)
        if not task:
            return
        pairs = (
            db.query(TaskParam, QueryParam)
            .join(QueryParam, TaskParam.param_id == QueryParam.id)
            .filter(TaskParam.task_id == task_id)
            .order_by(TaskParam.order_index)
            .all()
        )
        cookie = scraper.get_cookie()
        log = TaskRunLog(
            task_id=task_id,
            trigger_type=trigger,
            started_at=datetime.now(),
            status="running",
            total_params=len(pairs),
        )
        db.add(log)
        db.commit()
        run_id = log.id

        detail = []
        ok = 0
        status = "success"
        message = ""

        if not cookie:
            status = "failed"
            message = "Cookie 未配置，请到系统设置填写"
        elif not pairs:
            status = "failed"
            message = "任务没有关联查询参数"
        else:
            flight_date = (datetime.now() + timedelta(days=task.days_ahead or 0)).strftime("%Y-%m-%d")
            for i, (tp, qp) in enumerate(pairs):
                if i > 0:
                    lo = max(0, task.min_delay_sec or 0)
                    hi = max(lo, task.max_delay_sec or 0)
                    if hi > 0:
                        await asyncio.sleep(random.uniform(lo, hi))
                p = {
                    "domain": qp.domain or "shm",
                    "flightNo": qp.flight_no or "",
                    "dpt": qp.dpt or "",
                    "arr": qp.arr or "",
                    "flightDate": flight_date,
                    "cabin": qp.cabin or "",
                    "carrier": qp.carrier or "",
                }
                item = {
                    "paramId": qp.id,
                    "name": qp.name,
                    "dpt": qp.dpt,
                    "arr": qp.arr,
                    "flightDate": flight_date,
                }
                result = await scraper.scrape_and_save(p, source="task", save=True)
                if result.get("cookieInvalid"):
                    item["error"] = "Cookie 已失效"
                    detail.append(item)
                    status = "failed"
                    message = "Cookie 已失效，本次任务提前终止，请到系统设置更新 Cookie"
                    break
                if result.get("error"):
                    item["error"] = result.get("message") or result["error"]
                    detail.append(item)
                    if status == "success":
                        status = "partial"
                    continue
                ok += 1
                item["historyId"] = result.get("historyId")
                item["rowCount"] = result.get("rowCount")
                detail.append(item)
            if status != "failed" and ok < len(pairs):
                status = "partial"
            if not message:
                message = f"共 {len(pairs)} 条参数，成功 {ok} 条"

        # 更新日志
        log2 = db.get(TaskRunLog, run_id)
        log2.finished_at = datetime.now()
        log2.status = status
        log2.ok_params = ok
        log2.message = message
        log2.detail = detail

        # schedule 触发：推进 next_run_at 并释放；manual 触发：仅释放
        t = db.get(ScrapeTask, task_id)
        if t:
            t.last_status = status
            if trigger == "schedule":
                t.next_run_at = advance(t.next_run_at, datetime.now(), t.interval_days, t.time_of_day)
                t.status = "idle"
            else:
                t.status = "idle"
        db.commit()
        print(f"[scheduler] 任务#{task_id} {trigger} 执行完成: {status}，{message}")
    except Exception as e:
        print(f"[scheduler] 任务#{task_id} 执行异常: {e}")
        # 异常兜底：确保任务不卡在 running
        try:
            db.rollback()
            t = db.get(ScrapeTask, task_id)
            if t and t.status == "running":
                if trigger == "schedule":
                    t.next_run_at = advance(
                        t.next_run_at, datetime.now(), t.interval_days or 1, t.time_of_day or time_type(0, 0)
                    )
                t.status = "idle"
                t.last_status = "failed"
                db.commit()
        except Exception as e2:
            print(f"[scheduler] 兜底复位失败: {e2}")
    finally:
        db.close()


async def _loop():
    while True:
        try:
            now = datetime.now()
            from db import SessionLocal

            db = SessionLocal()
            try:
                due = [
                    r[0]
                    for r in db.query(ScrapeTask.id)
                    .filter(
                        ScrapeTask.enabled == 1,
                        ScrapeTask.status == "idle",
                        ScrapeTask.next_run_at.isnot(None),
                        ScrapeTask.next_run_at <= now,
                    )
                    .all()
                ]
            finally:
                db.close()
            for tid in due:
                if claim_task(tid):
                    await run_task(tid, trigger="schedule")  # 串行执行，不并发
        except Exception as e:
            print(f"[scheduler] tick error: {e}")
        await asyncio.sleep(TICK_SECONDS)


def scheduler_start():
    global _loop_task
    startup_reset()
    _loop_task = asyncio.create_task(_loop())
    print("[scheduler] 已启动（每 30s 扫描到期任务）")


def scheduler_stop():
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        _loop_task = None
