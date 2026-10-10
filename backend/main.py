# -*- coding: utf-8 -*-
"""九旅行 国内比价工具 后端

- 登录鉴权（JWT）
- 手动抓取 / 抓取历史
- 航班数据（数据库浏览 + 走势）
- 航班信息（预存查询参数）
- 定时任务（后台自动抓取入库）
启动: uvicorn main:app --port 8000（必须单 worker）
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
from routers import auth, data, history, params, scrape, settings, tasks, users
from scheduler import scheduler_start, scheduler_stop


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
        db.ensure_default_admin()
    except Exception as e:  # 数据库暂不可用时不阻塞启动
        print(f"[warn] MySQL 初始化失败: {e}")
    try:
        scheduler_start()
    except Exception as e:
        print(f"[warn] 调度器启动失败: {e}")
    yield
    scheduler_stop()


app = FastAPI(title="九旅比价爬虫", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, users.router, settings.router, scrape.router, history.router, params.router, tasks.router, data.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
