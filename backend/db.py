# -*- coding: utf-8 -*-
"""MySQL 持久化：连接管理、建库建表、轻量迁移 + 比价数据存取"""
import json
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DB_NAME, DATABASE_URL, SERVER_URL
from models import Base, BiddingRecord, QueryHistory, User

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
ServerEngine = create_engine(SERVER_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_database():
    """数据库不存在时自动创建"""
    with ServerEngine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        conn.commit()


# 已有表的轻量迁移（create_all 不会给已存在的表加列/加索引）
# MySQL 不支持 ADD COLUMN IF NOT EXISTS，靠错误码静默跳过：1060=列已存在 1061=索引已存在
_MIGRATION_STATEMENTS = [
    "ALTER TABLE bidding_record ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE bidding_record ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE bidding_record ADD INDEX idx_br_flight_date (flight_date)",
    "ALTER TABLE bidding_record ADD INDEX idx_br_created_at (created_at)",
    "ALTER TABLE bidding_record ADD INDEX idx_br_dpt_arr (dpt, arr)",
    "ALTER TABLE scrape_task ADD COLUMN days_ahead INT NOT NULL DEFAULT 1",
    "ALTER TABLE user ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0",
]


def _run_migrations():
    with engine.connect() as conn:
        for stmt in _MIGRATION_STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                code = getattr(getattr(e, "orig", None), "args", [None])[0]
                if code in (1060, 1061):
                    continue
                print(f"[warn] 迁移语句执行失败（忽略）: {stmt} -> {e}")


def init_db():
    ensure_database()
    Base.metadata.create_all(engine)
    _run_migrations()


def ensure_default_admin():
    """确保存在管理员账号：无管理员时创建默认账号 admin / admin123"""
    from auth import hash_password

    db = SessionLocal()
    try:
        if db.query(User).filter(User.is_admin == 1).first():
            return
        existing = db.query(User).filter(User.username == "admin").first()
        if existing:
            existing.is_admin = 1
            db.commit()
            print("[init] 已将账号 admin 提升为管理员")
            return
        db.add(
            User(
                username="admin",
                password_hash=hash_password("admin123"),
                is_admin=1,
                is_active=1,
            )
        )
        db.commit()
        print("[init] 已创建初始管理员账号：admin / admin123（请登录后尽快在「用户管理」中改密）")
    finally:
        db.close()


def _record_key(rec: "BiddingRecord") -> tuple:
    """行级业务键：用于去掉目标站接口返回的重复行"""
    return (
        rec.flight_date, rec.dpt, rec.arr, rec.flight_no, rec.main_flight_no,
        rec.cabin, rec.policy_type, rec.follow_base_price, rec.sell_price,
        rec.external_cabin, rec.self_price,
    )


def save_query_result(params: dict, rows: list, source: str = "manual") -> int:
    """保存一次查询及全部结果行（业务键相同的重复行只留一条），返回 history_id"""
    row_dicts = []
    seen = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        rec = BiddingRecord(
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
            source=source,
        )
        key = _record_key(rec)
        if key in seen:
            continue  # 目标站接口返回的重复行，只保留一条
        seen.add(key)
        row_dicts.append(rec)

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


def find_recent_history(params: dict, seconds: int = 10):
    """短时防重：同参数在 seconds 秒内已入库则返回该 history_id，否则 None。
    兜底重复提交（双击、多标签页、网络重试），同秒只留一份。"""
    from datetime import timedelta

    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(seconds=seconds)
        h = (
            db.query(QueryHistory)
            .filter(
                QueryHistory.domain == (params.get("domain") or "shm"),
                QueryHistory.flight_no == (params.get("flightNo") or ""),
                QueryHistory.dpt == (params.get("dpt") or ""),
                QueryHistory.arr == (params.get("arr") or ""),
                QueryHistory.flight_date == (params.get("flightDate") or ""),
                QueryHistory.cabin == (params.get("cabin") or ""),
                QueryHistory.carrier == (params.get("carrier") or ""),
                QueryHistory.created_at >= cutoff,
            )
            .order_by(QueryHistory.id.desc())
            .first()
        )
        return h.id if h else None
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


def delete_history(history_id: int) -> tuple:
    """删除一次历史及其全部结果行，返回 (是否删除, 行数)"""
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
