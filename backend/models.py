# -*- coding: utf-8 -*-
"""全部 ORM 模型"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    """登录用户"""

    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(200), nullable=False)
    is_admin = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


class AppSetting(Base):
    """系统设置（key/value）：cookie、jwt_secret 等"""

    __tablename__ = "app_setting"

    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(50), nullable=False, unique=True)
    setting_value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QueryParam(Base):
    """航班信息：预存储查询参数，供定时任务选用"""

    __tablename__ = "query_param"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), default="")
    domain = Column(String(20), default="shm")
    dpt = Column(String(10), nullable=False, default="")
    arr = Column(String(10), nullable=False, default="")
    flight_no = Column(String(20), default="")
    cabin = Column(String(10), default="")
    carrier = Column(String(10), default="")
    enabled = Column(Integer, default=1)
    remark = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.now)


class ScrapeTask(Base):
    """定时任务"""

    __tablename__ = "scrape_task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    interval_days = Column(Integer, nullable=False, default=1)  # 1=每天 2=隔天...（weekdays 为空时生效）
    weekdays = Column(String(20), nullable=False, default="")  # 每周执行日，逗号分隔 0-6（0=周一），空=按 interval_days
    time_of_day = Column(Time, nullable=False)  # 每日执行时刻
    window_mode = Column(String(10), nullable=False, default="rolling")  # rolling=滚动窗口 fixed=固定日期段
    days_ahead = Column(Integer, default=1)  # rolling：抓取今天+N天后的航班日期
    days_ahead_to = Column(Integer)  # rolling：范围终点（含），NULL=仅抓 days_ahead 单日
    fixed_date_from = Column(Date)  # fixed：起始航班日期
    fixed_date_to = Column(Date)  # fixed：结束航班日期（含），NULL=仅抓起始日
    enabled = Column(Integer, default=1)
    status = Column(String(20), nullable=False, default="idle")  # idle/running
    next_run_at = Column(DateTime)
    last_run_at = Column(DateTime)
    last_status = Column(String(20))  # success/partial/failed
    min_delay_sec = Column(Integer, nullable=False, default=3)
    max_delay_sec = Column(Integer, nullable=False, default=10)
    created_at = Column(DateTime, default=datetime.now)


class TaskParam(Base):
    """任务-查询参数关联"""

    __tablename__ = "task_param"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    param_id = Column(Integer, nullable=False, index=True)
    order_index = Column(Integer, nullable=False, default=0)


class TaskRunLog(Base):
    """任务执行日志"""

    __tablename__ = "task_run_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    trigger_type = Column(String(20), nullable=False)  # schedule/manual
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    status = Column(String(20), nullable=False)  # running/success/partial/failed
    total_params = Column(Integer, default=0)
    ok_params = Column(Integer, default=0)
    message = Column(String(500), default="")
    detail = Column(JSON)


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
    source = Column(String(10), nullable=False, default="manual")  # manual/task
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_br_flight_date", "flight_date"),
        Index("idx_br_created_at", "created_at"),
        Index("idx_br_dpt_arr", "dpt", "arr"),
    )


class XiamenQuery(Base):
    """一次成功的厦航查询；无优惠的查询也保存，防止展示旧的可售结果。"""
    __tablename__ = "xiamen_query"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, index=True)
    dpt = Column(String(3), nullable=False)
    arr = Column(String(3), nullable=False)
    flight_date = Column(Date, nullable=False)
    mf_only = Column(Integer, nullable=False, default=1)
    source = Column(String(10), nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (Index("idx_xq_route_date", "dpt", "arr", "flight_date", "mf_only"),)


class XiamenOffer(Base):
    """整程优惠报价快照，金额使用十进制，航段/权益保留结构化数据。"""
    __tablename__ = "xiamen_offer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(Integer, nullable=False, index=True)
    flight_date = Column(Date, nullable=False, index=True)
    dpt = Column(String(3), nullable=False)
    arr = Column(String(3), nullable=False)
    flight_numbers = Column(String(255), nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    base_amount = Column(Numeric(12, 2))
    currency = Column(String(8), nullable=False)
    all_mf = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class XiamenTask(Base):
    __tablename__ = "xiamen_task"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    routes = Column(JSON, nullable=False)  # 从航线库选取后保存三字码快照，互不影响
    window_mode = Column(String(10), nullable=False, default="rolling")
    days_ahead = Column(Integer, nullable=False, default=1)
    days_count = Column(Integer, nullable=False, default=7)
    fixed_date_from = Column(Date)
    fixed_date_to = Column(Date)
    interval_days = Column(Integer, nullable=False, default=1)
    time_of_day = Column(Time, nullable=False)
    min_delay_sec = Column(Integer, nullable=False, default=30)
    max_delay_sec = Column(Integer, nullable=False, default=60)
    mf_only = Column(Integer, nullable=False, default=1)
    enabled = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="idle")
    stop_requested = Column(Integer, nullable=False, default=0)
    next_run_at = Column(DateTime)
    last_run_at = Column(DateTime)
    last_status = Column(String(20))
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class XiamenTaskLog(Base):
    __tablename__ = "xiamen_task_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    trigger_type = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    finished_at = Column(DateTime)
    total = Column(Integer, nullable=False, default=0)
    completed = Column(Integer, nullable=False, default=0)
    offer_count = Column(Integer, nullable=False, default=0)
    message = Column(String(500), default="")
    detail = Column(JSON, nullable=False, default=list)
