# -*- coding: utf-8 -*-
"""数据库/服务配置：支持 .env 文件（backend 目录）与环境变量，环境变量优先"""
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path):
    """极简 .env 解析（零依赖）：KEY=VALUE 一行一条，# 注释；已存在的环境变量不覆盖"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(_BACKEND_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3666"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "123456")
DB_NAME = os.getenv("DB_NAME", "lvxing")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)
SERVER_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/?charset=utf8mb4"
)

# 登录 token 有效期（小时）
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "72"))

# 后端监听（run.py 读取）
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
