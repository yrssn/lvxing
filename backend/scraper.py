# -*- coding: utf-8 -*-
"""抓取核心：手动抓取与定时任务共用。Cookie 统一从 app_setting 读取。"""
import time
import warnings
from datetime import datetime, timedelta

import httpx

from models import AppSetting

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE_URL = "https://fuwu.jiulvxing.com"
BIDDING_URL = f"{BASE_URL}/tts/agent/tool/statistics/bidding"
REFERER = f"{BASE_URL}/tts/agent/tool/statistics/home?domain=shm"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0"
)

COOKIE_KEY = "cookie"


# ---------- Cookie（系统设置） ----------

def get_cookie() -> str:
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.setting_key == COOKIE_KEY).first()
        return (row.setting_value or "").strip() if row else ""
    finally:
        db.close()


def save_cookie(cookie: str) -> None:
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.setting_key == COOKIE_KEY).first()
        if row:
            row.setting_value = cookie.strip()
        else:
            db.add(AppSetting(setting_key=COOKIE_KEY, setting_value=cookie.strip()))
        db.commit()
    finally:
        db.close()


def get_cookie_updated_at() -> str:
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.setting_key == COOKIE_KEY).first()
        if row and row.updated_at:
            return row.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        return ""
    finally:
        db.close()


# ---------- 请求目标站 ----------

def build_query(p: dict) -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "domain": p.get("domain") or "shm",
        "flightNo": p.get("flightNo") or "",
        "dpt": p.get("dpt") or "",
        "arr": p.get("arr") or "",
        "flightDate": p.get("flightDate") or "",
        "cabin": p.get("cabin") or "",
        "carrier": p.get("carrier") or "",
        "_v": ts,
        "_": ts,
    }


def _headers(cookie: str) -> dict:
    return {
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


async def fetch_bidding(params: dict, cookie: str):
    """请求目标站比价接口，返回 (status_code, data)"""
    async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
        resp = await client.get(BIDDING_URL, params=build_query(params), headers=_headers(cookie))
    return resp.status_code, _safe_json(resp)


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return {"_non_json_body": resp.text[:2000]}


def _looks_cookie_invalid(status: int, data) -> bool:
    """判断是否 Cookie 失效：非 200、被重定向到登录页（非 JSON 响应）、明确的登录跳转"""
    if status in (301, 302, 401, 403):
        return True
    if isinstance(data, dict):
        if "_non_json_body" in data:
            return True
        msg = str(data.get("message", "")).lower()
        if data.get("success") is False and ("login" in msg or "登录" in msg):
            return True
    return False


def extract_order_rows(data):
    """从目标站返回 JSON 中提取 orderList 行"""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        rows = data["data"].get("orderList")
        if isinstance(rows, list):
            return rows
    return []


async def scrape_and_save(params: dict, source: str = "manual", save: bool = True) -> dict:
    """抓取一次并可选入库。返回 {status, raw, rows, rowCount, historyId, cookieInvalid, error, message}"""
    cookie = get_cookie()
    if not cookie:
        return {
            "error": "cookie_not_set",
            "message": "未配置 Cookie，请先到「系统设置」填写网站 Cookie",
        }
    try:
        status, data = await fetch_bidding(params, cookie)
    except httpx.HTTPError as e:
        return {"error": "request_failed", "status": 502, "message": f"请求目标网站失败: {e}"}

    cookie_invalid = _looks_cookie_invalid(status, data)
    rows = [] if cookie_invalid else extract_order_rows(data)
    history_id = None
    duplicate = False
    if save and rows:
        try:
            import db

            recent_id = db.find_recent_history(params, seconds=10)
            if recent_id is not None:
                # 10 秒内同参数已入库（重复提交），复用已有历史，不再落库
                history_id = recent_id
                duplicate = True
            else:
                history_id = db.save_query_result(params, rows, source=source)
        except Exception as e:
            print(f"[warn] 结果入库失败: {e}")
    return {
        "status": status,
        "raw": data,
        "rows": rows,
        "rowCount": len(rows),
        "historyId": history_id,
        "cookieInvalid": cookie_invalid,
        "duplicate": duplicate,
        "error": None,
    }


def probe_cookie():
    """用一次真实请求试探 Cookie 是否有效（系统设置-测试 Cookie 用）"""
    flight_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    params = {"dpt": "LHW", "arr": "HGH", "flightDate": flight_date}
    return params
