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


def _parse_weekdays(weekdays: str) -> set:
    """'0,3,5' -> {0,3,5}；0=周一 ... 6=周日；空/非法 -> 空集合（按 interval_days 模式）"""
    out = set()
    for part in (weekdays or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            out.add(int(part))
    return out


def advance(old_next: datetime, now: datetime, interval_days: int, time_of_day, weekdays: str = "") -> datetime:
    """推进到严格大于 now 的下一个执行点（old_next 为锚点，补跑/宕机多天也能追上）

    - weekdays 非空：每周模式，找下一个允许星期几的执行时刻（忽略 interval_days）
    - weekdays 为空：按 interval_days 间隔（原逻辑）
    """
    wd = _parse_weekdays(weekdays)
    if not wd:
        candidate = old_next or datetime.combine(now.date(), time_of_day)
        while candidate <= now:
            candidate = datetime.combine(candidate.date() + timedelta(days=interval_days), time_of_day)
        return candidate
    # 每周模式：从锚点/现在的当天或次日开始，找第一个允许星期几
    day = (old_next or now).date()
    candidate = datetime.combine(day, time_of_day)
    if candidate <= now:
        day += timedelta(days=1)
        candidate = datetime.combine(day, time_of_day)
    guard = 0
    while candidate.weekday() not in wd and guard < 60:
        day += timedelta(days=1)
        candidate = datetime.combine(day, time_of_day)
        guard += 1
    return candidate


def compute_initial_next_run(interval_days: int, time_of_day, weekdays: str = "") -> datetime:
    """创建/启用/修改任务时：今天的时刻未过则今天，否则顺延"""
    return advance(None, datetime.now(), interval_days, time_of_day, weekdays)


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
            # 抓取航班日期列表
            if task.window_mode == "fixed" and task.fixed_date_from:
                # 固定日期段：from~to 逐天（to 空 = 单日）
                d0 = task.fixed_date_from
                d1 = task.fixed_date_to or d0
                if d1 < d0:
                    d1 = d0
                dates = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
            else:
                # 滚动窗口：今天+daysAhead 至 今天+daysAheadTo（含）
                start_off = task.days_ahead or 0
                end_off = task.days_ahead_to if task.days_ahead_to is not None else start_off
                if end_off < start_off:
                    end_off = start_off
                dates = [(datetime.now() + timedelta(days=off)).date() for off in range(start_off, end_off + 1)]
            log2 = db.get(TaskRunLog, log.id)
            log2.total_params = len(pairs) * len(dates)
            db.commit()

            first = True
            for flight_date in dates:
                flight_date_str = flight_date.strftime("%Y-%m-%d")
                for tp, qp in pairs:
                    if not first:
                        lo = max(0, task.min_delay_sec or 0)
                        hi = max(lo, task.max_delay_sec or 0)
                        if hi > 0:
                            await asyncio.sleep(random.uniform(lo, hi))
                    first = False
                    p = {
                        "domain": qp.domain or "shm",
                        "flightNo": qp.flight_no or "",
                        "dpt": qp.dpt or "",
                        "arr": qp.arr or "",
                        "flightDate": flight_date_str,
                        "cabin": qp.cabin or "",
                        "carrier": qp.carrier or "",
                    }
                    item = {
                        "paramId": qp.id,
                        "name": qp.name,
                        "dpt": qp.dpt,
                        "arr": qp.arr,
                        "flightDate": flight_date_str,
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
                if status == "failed":
                    break
            total = len(pairs) * len(dates)
            if status != "failed" and ok < total:
                status = "partial"
            if not message:
                mode = "固定日期段" if (task.window_mode == "fixed" and task.fixed_date_from) else "滚动窗口"
                message = f"共 {total} 次抓取（{len(pairs)} 条参数 × {len(dates)} 天，{mode}），成功 {ok} 次"

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
                t.next_run_at = advance(t.next_run_at, datetime.now(), t.interval_days, t.time_of_day, t.weekdays)
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
                        t.next_run_at, datetime.now(), t.interval_days or 1,
                        t.time_of_day or time_type(0, 0), t.weekdays or "",
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
