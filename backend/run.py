# -*- coding: utf-8 -*-
"""后端一键启动：python run.py"""
import uvicorn

from config import APP_HOST, APP_PORT

if __name__ == "__main__":
    # 注意：必须单 worker（定时任务调度器依赖单进程）
    uvicorn.run("main:app", host=APP_HOST, port=APP_PORT)
