# -*- coding: utf-8 -*-
"""数据库连接配置，可通过环境变量覆盖"""
import os

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3308"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
DB_NAME = os.getenv("DB_NAME", "spider_lvxing")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)
SERVER_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/?charset=utf8mb4"
)
