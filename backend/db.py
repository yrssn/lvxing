# -*- coding: utf-8 -*-
"""MySQL 持久化：查询历史 + 比价记录"""
import json
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_NAME, DATABASE_URL, SERVER_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
ServerEngine = create_engine(SERVER_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


class QueryHistory(Base):
    """一次比价查询"""
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(20), default="shm")
    flight_no = Column(String(20), default="")
    dpt = Column(String(10), default="")
    arr = Column(String(10), default="")
    flight_date = Column(String(20), default="")
    cabin = Column(String(10), default="")
    carrier = Column(String(10), default="")
    row_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class BiddingRecord(Base):
    """比价结果中的一行"""
    __tablename__ = "bidding_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    history_id = Column(Integer, index=True, nullable=False)
    flight_date = Column(String(20), default="")
    dpt = Column(String(10), default="")
    arr = Column(String(10), default="")
    flight_no = Column(String(20), default="")
    main_flight_no = Column(String(20), default="")
    cabin = Column(String(10), default="")
    policy_type = Column(String(100), default="")
    follow_base_price = Column(Float)
    sell_price = Column(Float)
    external_cabin = Column(String(10), default="")
    self_price = Column(Float)
    raw = Column(JSON)


def ensure_database():
    """数据库不存在时自动创建"""
    from sqlalchemy import text

    with ServerEngine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        conn.commit()


def init_db():
    ensure_database()
    Base.metadata.create_all(engine)


def save_query_result(params: dict, rows: list) -> int:
    """保存一次查询及全部结果行，返回 history_id"""
    row_dicts = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        row_dicts.append(
            BiddingRecord(
                history_id=0,  # 占位，flush 后回填
                flight_date=str(r.get("flightDate") or ""),
                dpt=str(r.get("dpt") or ""),
                arr=str(r.get("arr") or ""),
                flight_no=str(r.get("flightNo") or ""),
                main_flight_no=str(r.get("mainFlightNo") or ""),
                cabin=str(r.get("cabin") or ""),
                policy_type=str(r.get("policyType") or ""),
                follow_base_price=_to_float(r.get("followBasePrice")),
                sell_price=_to_float(r.get("sellPrice")),
                external_cabin=str(r.get("externalCabin") or ""),
                self_price=_to_float(r.get("selfPrice")),
                raw=r,
            )
        )

    db = SessionLocal()
    try:
        history = QueryHistory(
            domain=params.get("domain", "shm"),
            flight_no=params.get("flightNo", ""),
            dpt=params.get("dpt", ""),
            arr=params.get("arr", ""),
            flight_date=params.get("flightDate", ""),
            cabin=params.get("cabin", ""),
            carrier=params.get("carrier", ""),
            row_count=len(row_dicts),
        )
        db.add(history)
        db.flush()
        for rec in row_dicts:
            rec.history_id = history.id
            db.add(rec)
        db.commit()
        return history.id
    finally:
        db.close()


def list_history(limit: int = 50) -> list:
    """最近的查询历史（新在前）"""
    db = SessionLocal()
    try:
        items = (
            db.query(QueryHistory)
            .order_by(QueryHistory.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": h.id,
                "domain": h.domain,
                "flightNo": h.flight_no,
                "dpt": h.dpt,
                "arr": h.arr,
                "flightDate": h.flight_date,
                "cabin": h.cabin,
                "carrier": h.carrier,
                "rowCount": h.row_count,
                "createdAt": h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else "",
            }
            for h in items
        ]
    finally:
        db.close()


def get_history_records(history_id: int) -> list:
    """取某次查询保存的结果行（返回原始 JSON 字典，便于前端直接渲染）"""
    db = SessionLocal()
    try:
        recs = (
            db.query(BiddingRecord)
            .filter(BiddingRecord.history_id == history_id)
            .all()
        )
        return [r.raw if isinstance(r.raw, dict) else json.loads(str(r.raw)) for r in recs]
    finally:
        db.close()


def delete_history(history_id: int) -> int:
    """删除一次历史及其全部结果行，返回删除的行数"""
    db = SessionLocal()
    try:
        n = db.query(BiddingRecord).filter(BiddingRecord.history_id == history_id).delete()
        deleted = db.query(QueryHistory).filter(QueryHistory.id == history_id).delete()
        db.commit()
        return deleted, n
    finally:
        db.close()


def _to_float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None
