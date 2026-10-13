# -*- coding: utf-8 -*-
"""航班数据：基于数据库（bidding_record）的浏览、筛选、走势聚合"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_

import auth
from db import SessionLocal
from models import BiddingRecord, User

router = APIRouter(tags=["data"])


def _apply_filters(q, dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom="", flightDateTo="", policyTypes=None):
    if dpt.strip():
        q = q.filter(BiddingRecord.dpt == dpt.strip().upper())
    if arr.strip():
        q = q.filter(BiddingRecord.arr == arr.strip().upper())
    if flightNo.strip():
        q = q.filter(BiddingRecord.flight_no.like(f"%{flightNo.strip().upper()}%"))
    if carrier.strip():
        q = q.filter(BiddingRecord.flight_no.startswith(carrier.strip().upper()))
    if source in ("manual", "task"):
        q = q.filter(BiddingRecord.source == source)
    # 政策类型多选：任一匹配（每个值模糊匹配，OR 连接）
    conds = [
        BiddingRecord.policy_type.like(f"%{t.strip()}%")
        for t in (policyTypes or [])
        if (t or "").strip()
    ]
    if conds:
        q = q.filter(or_(*conds))
    if flightDateFrom.strip():
        q = q.filter(BiddingRecord.flight_date >= flightDateFrom.strip())
    if flightDateTo.strip():
        q = q.filter(BiddingRecord.flight_date <= flightDateTo.strip())
    try:
        if crawlFrom.strip():
            q = q.filter(BiddingRecord.created_at >= datetime.strptime(crawlFrom.strip(), "%Y-%m-%d"))
    except ValueError:
        pass
    try:
        if crawlTo.strip():
            q = q.filter(
                BiddingRecord.created_at
                <= datetime.strptime(crawlTo.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            )
    except ValueError:
        pass
    return q


def _serialize(r: BiddingRecord) -> dict:
    return {
        "id": r.id,
        "historyId": r.history_id,
        "source": r.source,
        "createdAt": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        "flightDate": r.flight_date,
        "dpt": r.dpt,
        "arr": r.arr,
        "flightNo": r.flight_no,
        "mainFlightNo": r.main_flight_no,
        "cabin": r.cabin,
        "policyType": r.policy_type,
        "followBasePrice": r.follow_base_price,
        "sellPrice": r.sell_price,
        "externalCabin": r.external_cabin,
        "selfPrice": r.self_price,
    }


@router.get("/api/data/policy-types")
def policy_types(user: User = Depends(auth.get_current_user)):
    """政策类型去重选项（供筛选下拉，来自数据库）"""
    db = SessionLocal()
    try:
        rows = (
            db.query(BiddingRecord.policy_type)
            .filter(BiddingRecord.policy_type != "")
            .distinct()
            .order_by(BiddingRecord.policy_type)
            .all()
        )
        return {"success": True, "data": [r[0] for r in rows]}
    finally:
        db.close()


@router.get("/api/data/records")
def records(
    dpt: str = "",
    arr: str = "",
    flightNo: str = "",
    carrier: str = "",
    source: str = "",
    policyType: list[str] = Query(default=[]),
    flightDateFrom: str = "",
    flightDateTo: str = "",
    crawlFrom: str = "",
    crawlTo: str = "",
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=10000),
    user: User = Depends(auth.get_current_user),
):
    """按条件分页浏览已入库的抓取数据"""
    db = SessionLocal()
    try:
        q = _apply_filters(db.query(BiddingRecord), dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom, flightDateTo, policyType)
        total = q.count()
        items = (
            q.order_by(BiddingRecord.created_at.desc(), BiddingRecord.id.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
            .all()
        )
        return {"success": True, "data": {"total": total, "items": [_serialize(r) for r in items]}}
    finally:
        db.close()


@router.get("/api/data/trend")
def trend(
    dpt: str = "",
    arr: str = "",
    flightNo: str = "",
    carrier: str = "",
    source: str = "",
    policyType: list[str] = Query(default=[]),
    flightDateFrom: str = "",
    flightDateTo: str = "",
    crawlFrom: str = "",
    crawlTo: str = "",
    user: User = Depends(auth.get_current_user),
):
    """走势图数据：按航班日期聚合的最低价（基于数据库），并带出最低价对应舱位"""
    db = SessionLocal()
    try:
        q = _apply_filters(db.query(BiddingRecord), dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom, flightDateTo, policyType)
        q = q.filter(BiddingRecord.flight_date != "")
        rows = (
            q.with_entities(
                BiddingRecord.flight_date,
                BiddingRecord.sell_price,
                BiddingRecord.external_cabin,
                BiddingRecord.self_price,
                BiddingRecord.cabin,
            )
            .all()
        )
        # 按航班日期分组，Python 内取最低价对应行（SQL 的 MIN 拿不到同行舱位）
        grouped: dict = {}
        for fd, sell, ext_cabin, self_p, cabin in rows:
            grouped.setdefault(fd, []).append((sell, ext_cabin or "", self_p, cabin or ""))
        data = []
        for fd in sorted(grouped):
            items = grouped[fd]
            sell_row = min((r for r in items if r[0] is not None), key=lambda r: r[0], default=None)
            self_row = min((r for r in items if r[2] is not None), key=lambda r: r[2], default=None)
            data.append(
                {
                    "flightDate": fd,
                    "minSellPrice": sell_row[0] if sell_row else None,
                    "sellCabin": (sell_row[1] or sell_row[3]) if sell_row else "",
                    "minSelfPrice": self_row[2] if self_row else None,
                    "selfCabin": self_row[3] if self_row else "",
                    "recordCount": len(items),
                }
            )
        return {"success": True, "data": data}
    finally:
        db.close()
