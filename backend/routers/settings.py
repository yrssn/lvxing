# -*- coding: utf-8 -*-
"""系统设置：Cookie 管理（存数据库，手动抓取与定时任务共用）"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

import auth
import scraper
from models import User

router = APIRouter(prefix="/api/settings", tags=["settings"])


class CookieIn(BaseModel):
    cookie: str


@router.get("/cookie")
def get_cookie(user: User = Depends(auth.get_current_user)):
    return {
        "success": True,
        "data": {"cookie": scraper.get_cookie(), "updatedAt": scraper.get_cookie_updated_at()},
    }


@router.put("/cookie")
def put_cookie(body: CookieIn, user: User = Depends(auth.get_current_user)):
    scraper.save_cookie(body.cookie or "")
    return {"success": True}


@router.post("/test-cookie")
async def test_cookie(user: User = Depends(auth.get_current_user)):
    """用一次真实请求试探 Cookie 是否有效"""
    cookie = scraper.get_cookie()
    if not cookie:
        return {"success": True, "data": {"valid": False, "message": "尚未配置 Cookie", "status": 0}}
    probe = scraper.probe_cookie()
    try:
        status, data = await scraper.fetch_bidding(probe, cookie)
    except Exception as e:
        return {"success": True, "data": {"valid": False, "message": f"请求失败: {e}", "status": 0}}
    invalid = scraper._looks_cookie_invalid(status, data)
    rows = scraper.extract_order_rows(data)
    if invalid:
        message = "Cookie 已失效，请重新从浏览器复制"
    elif status != 200:
        message = f"目标站返回状态 {status}，Cookie 可能失效"
    else:
        message = "Cookie 有效" + (f"，试探查询返回 {len(rows)} 行" if rows else "")
    return {"success": True, "data": {"valid": not invalid and status == 200, "message": message, "status": status}}
