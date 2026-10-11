# -*- coding: utf-8 -*-
"""全部 ORM 模型"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
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
    interval_days = Column(Integer, nullable=False, default=1)  # 1=每天 2=隔天...
    time_of_day = Column(Time, nullable=False)  # 每日执行时刻
    days_ahead = Column(Integer, default=1)  # 抓取今天+N天后的航班日期
    days_ahead_to = Column(Integer)  # 抓取日期范围终点（含），NULL=仅抓 days_ahead 单日
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
