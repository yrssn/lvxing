# -*- coding: utf-8 -*-
"""九旅行 国内比价工具 爬虫后端

转发 fuwu.jiulvxing.com 的比价接口，Cookie 由前端传入。
启动: uvicorn main:app --reload --port 8000
"""
import time
import warnings

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import db
from db import get_history_records, delete_history, list_history

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

app = FastAPI(title="九旅比价爬虫")


@app.on_event("startup")
def on_startup():
    try:
        db.init_db()
    except Exception as e:  # 数据库暂不可用时不阻塞爬取功能
        print(f"[warn] MySQL 初始化失败，历史记录功能不可用: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://fuwu.jiulvxing.com"
BIDDING_URL = f"{BASE_URL}/tts/agent/tool/statistics/bidding"
REFERER = f"{BASE_URL}/tts/agent/tool/statistics/home?domain=shm"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0"
)


@app.get("/api/bidding")
async def bidding(
    cookie: str = Query(..., description="完整 Cookie 字符串，如 jt01=xxx; JSESSIONID=xxx"),
    domain: str = Query("shm"),
    flightNo: str = Query(""),
    dpt: str = Query(""),
    arr: str = Query(""),
    flightDate: str = Query(""),
    cabin: str = Query(""),
    carrier: str = Query(""),
):
    """比价查询：参数与原站一致，Cookie 由前端填写传入"""
    ts = str(int(time.time() * 1000))
    params = {
        "domain": domain,
        "flightNo": flightNo,
        "dpt": dpt,
        "arr": arr,
        "flightDate": flightDate,
        "cabin": cabin,
        "carrier": carrier,
        "_v": ts,
        "_": ts,
    }
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "referer": REFERER,
        "user-agent": UA,
        "x-requested-with": "XMLHttpRequest",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "cookie": cookie,
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
            resp = await client.get(BIDDING_URL, params=params, headers=headers)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"success": False, "message": f"请求目标网站失败: {e}"})

    # 原样透传目标站响应，同时带出状态码便于前端判断 Cookie 是否失效
    # 成功拿到数据时入库保存
    saved_id = None
    data = _safe_json(resp)
    rows = (
        data.get("data", {}).get("orderList")
        if isinstance(data, dict) and isinstance(data.get("data"), dict)
        else None
    )
    if rows:
        try:
            saved_id = db.save_query_result(
                {
                    "domain": domain,
                    "flightNo": flightNo,
                    "dpt": dpt,
                    "arr": arr,
                    "flightDate": flightDate,
                    "cabin": cabin,
                    "carrier": carrier,
                },
                rows,
            )
        except Exception as e:
            print(f"[warn] 结果入库失败: {e}")

    return JSONResponse(
        status_code=resp.status_code,
        content={"success": True, "status": resp.status_code, "historyId": saved_id, "raw": data},
    )


@app.get("/api/history")
async def history(limit: int = Query(50, ge=1, le=200)):
    """查询历史列表"""
    try:
        return {"success": True, "data": list_history(limit)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})


@app.get("/api/history/{history_id}/records")
async def history_records(history_id: int):
    """回看某次查询保存的结果"""
    try:
        return {"success": True, "data": get_history_records(history_id)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})


@app.delete("/api/history/{history_id}")
async def history_delete(history_id: int):
    """删除某次查询历史及其结果"""
    try:
        deleted, n = delete_history(history_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"success": False, "message": "记录不存在"})
        return {"success": True, "deletedRows": n}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return {"_non_json_body": resp.text[:2000]}


@app.get("/api/health")
async def health():
    return {"status": "ok"}
