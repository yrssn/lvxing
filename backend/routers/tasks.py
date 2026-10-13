# -*- coding: utf-8 -*-
"""定时任务：CRUD + 启停 + 立即执行 + 执行日志"""
import asyncio
import re
from datetime import datetime, time as time_type

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
import scheduler
from db import SessionLocal
from models import QueryParam, ScrapeTask, TaskParam, TaskRunLog, User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskIn(BaseModel):
    name: str
    intervalDays: int = 1
    timeOfDay: str  # "HH:MM"
    weekdays: str = ""  # 每周执行日 "0,3,5"（0=周一），空=按 intervalDays
    windowMode: str = "rolling"  # rolling=滚动窗口 fixed=固定日期段
    daysAhead: int = 1
    daysAheadTo: int = 0  # rolling：范围终点（含），0/缺省=仅抓 daysAhead 单日
    fixedDateFrom: str = ""  # fixed："YYYY-MM-DD"
    fixedDateTo: str = ""  # fixed：结束日期（含）
    minDelaySec: int = 3
    maxDelaySec: int = 10
    enabled: bool = True
    paramIds: list = []


def _parse_time(s: str) -> time_type:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (s or "").strip())
    if not m:
        raise HTTPException(status_code=400, detail="执行时间格式应为 HH:MM")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise HTTPException(status_code=400, detail="执行时间不合法")
    return time_type(h, mi)


def _parse_date(s: str, field: str):
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field}格式应为 YYYY-MM-DD")


def _validate(body: TaskIn):
    if not (1 <= body.intervalDays <= 30):
        raise HTTPException(status_code=400, detail="间隔天数需在 1-30 之间")
    if body.windowMode not in ("rolling", "fixed"):
        raise HTTPException(status_code=400, detail="抓取日期窗口模式不合法")
    if body.windowMode == "rolling":
        if not (0 <= body.daysAhead <= 90):
            raise HTTPException(status_code=400, detail="抓取日期偏移需在 0-90 之间")
        if body.daysAheadTo and not (body.daysAhead <= body.daysAheadTo <= 90):
            raise HTTPException(status_code=400, detail="抓取日期范围终点需不小于起点且不超过 90")
    else:
        if not (body.fixedDateFrom or "").strip():
            raise HTTPException(status_code=400, detail="固定日期段必须选择起始日期")
        _parse_date(body.fixedDateFrom, "起始日期")
        if (body.fixedDateTo or "").strip():
            d0 = _parse_date(body.fixedDateFrom, "起始日期")
            d1 = _parse_date(body.fixedDateTo, "结束日期")
            if d1 < d0:
                raise HTTPException(status_code=400, detail="结束日期不能早于起始日期")
            if (d1 - d0).days > 90:
                raise HTTPException(status_code=400, detail="固定日期段最长 90 天")
    # weekdays 非空时按每周模式，intervalDays 不生效
    if (body.weekdays or "").strip():
        for part in body.weekdays.split(","):
            part = part.strip()
            if part and (not part.isdigit() or not 0 <= int(part) <= 6):
                raise HTTPException(status_code=400, detail="每周执行日格式不合法")
    if body.minDelaySec < 0 or body.maxDelaySec < 0:
        raise HTTPException(status_code=400, detail="延时秒数不能为负")
    if body.minDelaySec > body.maxDelaySec:
        raise HTTPException(status_code=400, detail="最小延时不能大于最大延时")
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="任务名称必填")


def _serialize(t: ScrapeTask, param_ids: list) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "intervalDays": t.interval_days,
        "timeOfDay": t.time_of_day.strftime("%H:%M") if t.time_of_day else "",
        "weekdays": t.weekdays or "",
        "windowMode": t.window_mode or "rolling",
        "daysAhead": t.days_ahead if t.days_ahead is not None else 1,
        "daysAheadTo": t.days_ahead_to or 0,
        "fixedDateFrom": t.fixed_date_from.strftime("%Y-%m-%d") if t.fixed_date_from else "",
        "fixedDateTo": t.fixed_date_to.strftime("%Y-%m-%d") if t.fixed_date_to else "",
        "enabled": bool(t.enabled),
        "status": t.status,
        "nextRunAt": t.next_run_at.strftime("%Y-%m-%d %H:%M:%S") if t.next_run_at else "",
        "lastRunAt": t.last_run_at.strftime("%Y-%m-%d %H:%M:%S") if t.last_run_at else "",
        "lastStatus": t.last_status or "",
        "minDelaySec": t.min_delay_sec,
        "maxDelaySec": t.max_delay_sec,
        "paramIds": param_ids,
        "paramCount": len(param_ids),
    }


def _set_params(db, task_id: int, param_ids: list):
    db.query(TaskParam).filter(TaskParam.task_id == task_id).delete()
    seen = set()
    for i, pid in enumerate(param_ids):
        pid = int(pid)
        if pid in seen:
            continue
        seen.add(pid)
        db.add(TaskParam(task_id=task_id, param_id=pid, order_index=i))


@router.get("")
def list_tasks(user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        tasks = db.query(ScrapeTask).order_by(ScrapeTask.id.desc()).all()
        links = db.query(TaskParam).all()
        by_task = {}
        for l in links:
            by_task.setdefault(l.task_id, []).append(l.param_id)
        return {"success": True, "data": [_serialize(t, sorted(by_task.get(t.id, []))) for t in tasks]}
    finally:
        db.close()


@router.post("")
def create_task(body: TaskIn, user: User = Depends(auth.get_current_user)):
    _validate(body)
    tod = _parse_time(body.timeOfDay)
    db = SessionLocal()
    try:
        t = ScrapeTask(
            name=body.name.strip(),
            interval_days=body.intervalDays,
            weekdays=(body.weekdays or "").strip(),
            time_of_day=tod,
            window_mode=body.windowMode,
            days_ahead=body.daysAhead,
            days_ahead_to=body.daysAheadTo or None,
            fixed_date_from=_parse_date(body.fixedDateFrom, "起始日期") if body.windowMode == "fixed" and (body.fixedDateFrom or "").strip() else None,
            fixed_date_to=_parse_date(body.fixedDateTo, "结束日期") if body.windowMode == "fixed" and (body.fixedDateTo or "").strip() else None,
            enabled=1 if body.enabled else 0,
            status="idle",
            min_delay_sec=body.minDelaySec,
            max_delay_sec=body.maxDelaySec,
            next_run_at=scheduler.compute_initial_next_run(body.intervalDays, tod, body.weekdays) if body.enabled else None,
        )
        db.add(t)
        db.flush()
        _set_params(db, t.id, body.paramIds)
        db.commit()
        ids = [r[0] for r in db.query(TaskParam.param_id).filter(TaskParam.task_id == t.id).all()]
        return {"success": True, "data": _serialize(t, sorted(ids))}
    finally:
        db.close()


@router.put("/{task_id}")
def update_task(task_id: int, body: TaskIn, user: User = Depends(auth.get_current_user)):
    _validate(body)
    tod = _parse_time(body.timeOfDay)
    db = SessionLocal()
    try:
        t = db.get(ScrapeTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        if t.status == "running":
            raise HTTPException(status_code=409, detail="任务正在执行，请稍后再修改")
        t.name = body.name.strip()
        t.interval_days = body.intervalDays
        t.weekdays = (body.weekdays or "").strip()
        t.time_of_day = tod
        t.window_mode = body.windowMode
        t.days_ahead = body.daysAhead
        t.days_ahead_to = body.daysAheadTo or None
        t.fixed_date_from = _parse_date(body.fixedDateFrom, "起始日期") if body.windowMode == "fixed" and (body.fixedDateFrom or "").strip() else None
        t.fixed_date_to = _parse_date(body.fixedDateTo, "结束日期") if body.windowMode == "fixed" and (body.fixedDateTo or "").strip() else None
        t.min_delay_sec = body.minDelaySec
        t.max_delay_sec = body.maxDelaySec
        t.enabled = 1 if body.enabled else 0
        t.next_run_at = scheduler.compute_initial_next_run(body.intervalDays, tod, body.weekdays) if body.enabled else None
        _set_params(db, task_id, body.paramIds)
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.delete("/{task_id}")
def delete_task(task_id: int, user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        t = db.get(ScrapeTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        if t.status == "running":
            raise HTTPException(status_code=409, detail="任务正在执行，无法删除")
        db.query(TaskParam).filter(TaskParam.task_id == task_id).delete()
        db.query(TaskRunLog).filter(TaskRunLog.task_id == task_id).delete()
        db.delete(t)
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.post("/{task_id}/toggle")
def toggle_task(task_id: int, body: dict, user: User = Depends(auth.get_current_user)):
    enabled = bool(body.get("enabled"))
    db = SessionLocal()
    try:
        t = db.get(ScrapeTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        t.enabled = 1 if enabled else 0
        if enabled:
            t.next_run_at = scheduler.compute_initial_next_run(t.interval_days, t.time_of_day, t.weekdays)
        db.commit()
        return {"success": True, "data": {"enabled": enabled, "nextRunAt": t.next_run_at.strftime("%Y-%m-%d %H:%M:%S") if t.next_run_at else ""}}
    finally:
        db.close()


@router.post("/{task_id}/run-now")
async def run_now(task_id: int, user: User = Depends(auth.get_current_user)):
    """立即执行一次（异步），不影响 next_run_at"""
    db = SessionLocal()
    try:
        t = db.get(ScrapeTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
    finally:
        db.close()
    if not scheduler.claim_task(task_id):
        raise HTTPException(status_code=409, detail="任务正在执行中")
    asyncio.create_task(scheduler.run_task(task_id, trigger="manual"))
    return {"success": True, "data": {"message": "已触发执行，可在日志中查看进度"}}


@router.get("/{task_id}/logs")
def task_logs(task_id: int, limit: int = Query(50, ge=1, le=200), user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        logs = (
            db.query(TaskRunLog)
            .filter(TaskRunLog.task_id == task_id)
            .order_by(TaskRunLog.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "success": True,
            "data": [
                {
                    "id": l.id,
                    "trigger": l.trigger_type,
                    "startedAt": l.started_at.strftime("%Y-%m-%d %H:%M:%S") if l.started_at else "",
                    "finishedAt": l.finished_at.strftime("%Y-%m-%d %H:%M:%S") if l.finished_at else "",
                    "status": l.status,
                    "totalParams": l.total_params,
                    "okParams": l.ok_params,
                    "message": l.message,
                    "detail": l.detail or [],
                }
                for l in logs
            ],
        }
    finally:
        db.close()
