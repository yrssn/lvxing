# -*- coding: utf-8 -*-
"""航班数据：基于数据库（bidding_record）的浏览、筛选、走势聚合"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

import auth
from db import SessionLocal
from models import BiddingRecord, User

router = APIRouter(tags=["data"])


def _apply_filters(q, dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom="", flightDateTo=""):
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


@router.get("/api/data/records")
def records(
    dpt: str = "",
    arr: str = "",
    flightNo: str = "",
    carrier: str = "",
    source: str = "",
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
        q = _apply_filters(db.query(BiddingRecord), dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom, flightDateTo)
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
    flightDateFrom: str = "",
    flightDateTo: str = "",
    crawlFrom: str = "",
    crawlTo: str = "",
    user: User = Depends(auth.get_current_user),
):
    """走势图数据：按航班日期聚合的最低价（基于数据库）"""
    db = SessionLocal()
    try:
        q = _apply_filters(db.query(BiddingRecord), dpt, arr, flightNo, carrier, source, crawlFrom, crawlTo, flightDateFrom, flightDateTo)
        q = q.filter(BiddingRecord.flight_date != "")
        rows = (
            q.with_entities(
                BiddingRecord.flight_date,
                func.min(BiddingRecord.sell_price).label("min_sell"),
                func.min(BiddingRecord.self_price).label("min_self"),
                func.count(BiddingRecord.id).label("cnt"),
            )
            .group_by(BiddingRecord.flight_date)
            .order_by(BiddingRecord.flight_date)
            .all()
        )
        return {
            "success": True,
            "data": [
                {
                    "flightDate": r[0],
                    "minSellPrice": r[1],
                    "minSelfPrice": r[2],
                    "recordCount": r[3],
                }
                for r in rows
            ],
        }
    finally:
        db.close()
