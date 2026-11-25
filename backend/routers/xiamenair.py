"""厦航独立模块 API。仅航线三字码从原航线库导入。"""
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func

import auth
import xiamenair as service
import xiamen_scheduler as scheduler
from db import SessionLocal
from models import QueryParam, User, XiamenOffer, XiamenQuery, XiamenTask, XiamenTaskLog

router = APIRouter(prefix="/api/xiamenair", tags=["xiamenair"])


def airport(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise HTTPException(400, "机场必须是三字码")
    return value


def valid_date(value):
    today = service.now_cn().date()
    if not today <= value <= today + timedelta(days=90):
        raise HTTPException(400, "航班日期需在今天至未来 90 天内")
    return value


class SessionIn(BaseModel):
    cookie: str = Field(min_length=1, max_length=16000)
    uds: str = Field(min_length=1, max_length=2000)


class QueryIn(BaseModel):
    dpt: str
    arr: str
    flightDate: date
    mfOnly: bool = True


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    routeIds: list[int] = Field(min_length=1, max_length=200)
    windowMode: str = "rolling"
    daysAhead: int = Field(default=1, ge=0, le=90)
    daysCount: int = Field(default=7, ge=1, le=30)
    fixedDateFrom: date | None = None
    fixedDateTo: date | None = None
    intervalDays: int = Field(default=1, ge=1, le=30)
    timeOfDay: str = "09:00"
    minDelaySec: int = Field(default=30, ge=30, le=3600)
    maxDelaySec: int = Field(default=60, ge=30, le=3600)
    mfOnly: bool = True
    enabled: bool = False


@router.get("/settings")
def get_settings(user: User = Depends(auth.get_current_user)):
    return {"success": True, "data": service.public_settings()}


@router.put("/settings")
async def put_settings(body: SessionIn, user: User = Depends(auth.require_admin)):
    cookie, uds = body.cookie.strip(), body.uds.strip()
    if not cookie or not uds or any(c in cookie + uds for c in "\r\n"):
        raise HTTPException(400, "Cookie 和 uds 必填，且不能包含换行")
    try:
        await service.save_session(cookie, uds)
    except service.CollectionStopped as e:
        raise HTTPException(409, str(e))
    return {"success": True}


@router.get("/routes")
def routes(user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        rows = db.query(QueryParam).filter(QueryParam.enabled == 1).order_by(QueryParam.id).all()
        seen, result = set(), []
        for p in rows:
            dpt, arr = p.dpt.strip().upper(), p.arr.strip().upper()
            if re.fullmatch(r"[A-Z]{3}", dpt) and re.fullmatch(r"[A-Z]{3}", arr) and dpt != arr and (dpt, arr) not in seen:
                seen.add((dpt, arr))
                result.append({"id": p.id, "dpt": dpt, "arr": arr})
        return {"success": True, "data": result}


@router.post("/query")
async def query(body: QueryIn, user: User = Depends(auth.get_current_user)):
    dpt, arr = airport(body.dpt), airport(body.arr)
    if dpt == arr:
        raise HTTPException(400, "出发与到达不能相同")
    valid_date(body.flightDate)
    try:
        result = await service.collect(dpt, arr, body.flightDate, body.mfOnly, manual=True)
    except service.CollectionStopped as e:
        raise HTTPException(429 if e.kind in ("risk", "quota", "cooldown") else 409, str(e))
    return {"success": True, "data": result}


@router.get("/offers")
def offers(dpt: str = "", arr: str = "", flightNo: str = "", dateFrom: date | None = None,
           dateTo: date | None = None, latest: bool = True, mfOnly: bool = True,
           page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
           user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        q = db.query(XiamenOffer, XiamenQuery).join(XiamenQuery, XiamenOffer.query_id == XiamenQuery.id)
        if latest:
            newest = db.query(func.max(XiamenQuery.id)).group_by(XiamenQuery.dpt, XiamenQuery.arr, XiamenQuery.flight_date)
            q = q.filter(XiamenOffer.query_id.in_(newest))
        if dpt:
            q = q.filter(XiamenQuery.dpt == airport(dpt))
        if arr:
            q = q.filter(XiamenQuery.arr == airport(arr))
        if dateFrom:
            q = q.filter(XiamenOffer.flight_date >= dateFrom)
        if dateTo:
            q = q.filter(XiamenOffer.flight_date <= dateTo)
        if flightNo.strip():
            q = q.filter(XiamenOffer.flight_numbers.contains(flightNo.strip().upper(), autoescape=True))
        if mfOnly:
            q = q.filter(XiamenOffer.all_mf == 1)
        total = q.count()
        rows = q.order_by(XiamenOffer.created_at.desc(), XiamenOffer.total_amount, XiamenOffer.id.desc()).offset((page-1)*pageSize).limit(pageSize).all()
        return {"success": True, "data": {"total": total, "items": [dict(
            o.payload, id=o.id, queryId=o.query_id, flightDate=str(o.flight_date), capturedAt=o.created_at.isoformat(),
            requestedRoute=[snap.dpt, snap.arr], source=snap.source, taskId=snap.task_id,
        ) for o, snap in rows]}}


def serialize_task(t):
    return {"id": t.id, "name": t.name, "routes": t.routes, "routeIds": [r["id"] for r in t.routes],
            "windowMode": t.window_mode, "daysAhead": t.days_ahead, "daysCount": t.days_count,
            "fixedDateFrom": str(t.fixed_date_from) if t.fixed_date_from else None,
            "fixedDateTo": str(t.fixed_date_to) if t.fixed_date_to else None,
            "intervalDays": t.interval_days, "timeOfDay": t.time_of_day.strftime("%H:%M"),
            "minDelaySec": t.min_delay_sec, "maxDelaySec": t.max_delay_sec, "mfOnly": bool(t.mf_only),
            "enabled": bool(t.enabled), "status": t.status, "lastStatus": t.last_status,
            "nextRunAt": t.next_run_at.isoformat() if t.next_run_at else None,
            "lastRunAt": t.last_run_at.isoformat() if t.last_run_at else None}


def apply_task(db, task, body):
    if not body.name.strip():
        raise HTTPException(400, "任务名称不能为空")
    if body.minDelaySec > body.maxDelaySec:
        raise HTTPException(400, "最小间隔不能大于最大间隔")
    if body.windowMode not in ("rolling", "fixed"):
        raise HTTPException(400, "日期模式无效")
    try:
        tod = datetime.strptime(body.timeOfDay, "%H:%M").time()
    except ValueError:
        raise HTTPException(400, "执行时间格式应为 HH:MM")
    if body.windowMode == "fixed":
        if not body.fixedDateFrom:
            raise HTTPException(400, "请选择固定起始日期")
        start = valid_date(body.fixedDateFrom)
        end = valid_date(body.fixedDateTo or start)
        days = (end-start).days + 1
        if not 1 <= days <= 30:
            raise HTTPException(400, "固定日期段必须为 1–30 天")
    else:
        days = body.daysCount
        if body.daysAhead + days - 1 > 90:
            raise HTTPException(400, "窗口结束日期不能超过未来 90 天")
    selected, seen = [], set()
    for pid in dict.fromkeys(body.routeIds):
        p = db.get(QueryParam, pid)
        if not p or not p.enabled:
            raise HTTPException(400, f"航线 #{pid} 已不存在或已停用，请重新选择")
        dpt, arr = airport(p.dpt), airport(p.arr)
        if dpt == arr:
            raise HTTPException(400, "出发与到达不能相同")
        if (dpt, arr) not in seen:
            seen.add((dpt, arr))
            selected.append({"id": pid, "dpt": dpt, "arr": arr})
    if len(selected) * days > service.MAX_TASK_REQUESTS:
        raise HTTPException(400, "航线数 × 天数不能超过 200；请缩小范围。所有任务共用每天 200 次配额")
    task.name, task.routes = body.name.strip(), selected
    task.window_mode, task.days_ahead, task.days_count = body.windowMode, body.daysAhead, body.daysCount
    task.fixed_date_from = body.fixedDateFrom if body.windowMode == "fixed" else None
    task.fixed_date_to = (body.fixedDateTo or body.fixedDateFrom) if body.windowMode == "fixed" else None
    task.interval_days, task.time_of_day = body.intervalDays, tod
    task.min_delay_sec, task.max_delay_sec = body.minDelaySec, body.maxDelaySec
    task.mf_only, task.enabled = int(body.mfOnly), int(body.enabled)
    task.next_run_at = scheduler.next_time(task) if task.enabled else None


@router.get("/tasks")
def tasks(user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        return {"success": True, "data": [serialize_task(t) for t in db.query(XiamenTask).order_by(XiamenTask.id.desc()).all()]}


@router.post("/tasks")
def create_task(body: TaskIn, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        t = XiamenTask(status="idle", created_at=service.now_cn())
        apply_task(db, t, body)
        db.add(t)
        db.commit()
        return {"success": True, "data": serialize_task(t)}


@router.put("/tasks/{task_id}")
def update_task(task_id: int, body: TaskIn, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        t = db.get(XiamenTask, task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        if t.status in scheduler.ACTIVE:
            raise HTTPException(409, "请先停止本次执行，再修改任务")
        apply_task(db, t, body)
        db.commit()
        return {"success": True}


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        if not db.get(XiamenTask, task_id):
            raise HTTPException(404, "任务不存在")
    if not scheduler.enqueue(task_id):
        raise HTTPException(409, "任务已经在排队或执行中")
    return {"success": True, "message": "已排队；首次请求也会等待 30–60 秒或任务指定的更长间隔"}


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: int, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        t = db.get(XiamenTask, task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        if t.status in scheduler.ACTIVE:
            t.stop_requested, t.status = 1, "stopping"
        db.commit()
        return {"success": True, "message": "停止请求已提交，当前在途请求完成后不再发送新请求"}


class ToggleIn(BaseModel):
    enabled: bool


@router.post("/tasks/{task_id}/toggle")
def toggle_task(task_id: int, body: ToggleIn, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        t = db.get(XiamenTask, task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        t.enabled = int(body.enabled)
        t.next_run_at = scheduler.next_time(t) if body.enabled else None
        if not body.enabled and t.status in scheduler.ACTIVE:
            t.stop_requested, t.status = 1, "stopping"
        db.commit()
        return {"success": True}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        t = db.get(XiamenTask, task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        if t.status in scheduler.ACTIVE:
            raise HTTPException(409, "请先停止任务")
        db.delete(t)  # 保留已采集报价与日志
        db.commit()
        return {"success": True}


@router.get("/tasks/{task_id}/logs")
def task_logs(task_id: int, user: User = Depends(auth.get_current_user)):
    with SessionLocal() as db:
        rows = db.query(XiamenTaskLog).filter_by(task_id=task_id).order_by(XiamenTaskLog.id.desc()).limit(50).all()
        return {"success": True, "data": [{"id": r.id, "trigger": r.trigger_type, "status": r.status,
            "startedAt": r.started_at.isoformat(), "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
            "total": r.total, "completed": r.completed, "offerCount": r.offer_count, "message": r.message,
            "detail": r.detail or []} for r in rows]}
