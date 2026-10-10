# -*- coding: utf-8 -*-
"""航班信息：预存储查询参数 CRUD（供定时任务选用）"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
from db import SessionLocal
from models import QueryParam, TaskParam, User

router = APIRouter(prefix="/api/params", tags=["params"])


class ParamIn(BaseModel):
    name: str = ""
    domain: str = "shm"
    dpt: str
    arr: str
    flightNo: str = ""
    cabin: str = ""
    carrier: str = ""
    enabled: bool = True
    remark: str = ""


def _serialize(p: QueryParam) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "domain": p.domain,
        "dpt": p.dpt,
        "arr": p.arr,
        "flightNo": p.flight_no,
        "cabin": p.cabin,
        "carrier": p.carrier,
        "enabled": bool(p.enabled),
        "remark": p.remark,
        "createdAt": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
    }


def _apply(p: QueryParam, body: ParamIn):
    if not body.dpt.strip() or not body.arr.strip():
        raise HTTPException(status_code=400, detail="出发、到达机场为必填项")
    p.name = (body.name or "").strip() or f"{body.dpt.strip().upper()}→{body.arr.strip().upper()}"
    p.domain = body.domain or "shm"
    p.dpt = body.dpt.strip().upper()
    p.arr = body.arr.strip().upper()
    p.flight_no = (body.flightNo or "").strip().upper()
    p.cabin = (body.cabin or "").strip().upper()
    p.carrier = (body.carrier or "").strip().upper()
    p.enabled = 1 if body.enabled else 0
    p.remark = (body.remark or "").strip()


@router.get("")
def list_params(
    keyword: str = Query("", description="按名称/航线模糊搜索"),
    user: User = Depends(auth.get_current_user),
):
    db = SessionLocal()
    try:
        q = db.query(QueryParam)
        if keyword.strip():
            kw = f"%{keyword.strip()}%"
            q = q.filter(
                (QueryParam.name.like(kw))
                | (QueryParam.dpt.like(kw))
                | (QueryParam.arr.like(kw))
                | (QueryParam.flight_no.like(kw))
            )
        items = q.order_by(QueryParam.id.desc()).all()
        return {"success": True, "data": [_serialize(p) for p in items]}
    finally:
        db.close()


@router.post("")
def create_param(body: ParamIn, user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        p = QueryParam()
        _apply(p, body)
        db.add(p)
        db.commit()
        return {"success": True, "data": _serialize(p)}
    finally:
        db.close()


@router.put("/{param_id}")
def update_param(param_id: int, body: ParamIn, user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        p = db.get(QueryParam, param_id)
        if not p:
            raise HTTPException(status_code=404, detail="参数不存在")
        _apply(p, body)
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.delete("/{param_id}")
def delete_param(param_id: int, user: User = Depends(auth.get_current_user)):
    db = SessionLocal()
    try:
        p = db.get(QueryParam, param_id)
        if not p:
            raise HTTPException(status_code=404, detail="参数不存在")
        db.query(TaskParam).filter(TaskParam.param_id == param_id).delete()
        db.delete(p)
        db.commit()
        return {"success": True}
    finally:
        db.close()
