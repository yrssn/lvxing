# -*- coding: utf-8 -*-
"""手动抓取：查询（不入库）或抓取入库，功能与原 /api/bidding 一致"""
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import auth
import scraper
from models import User

router = APIRouter(prefix="/api/scrape", tags=["scrape"])


class ScrapeIn(BaseModel):
    domain: str = "shm"
    flightNo: str = ""
    dpt: str
    arr: str
    flightDate: str
    cabin: str = ""
    carrier: str = ""
    save: bool = False  # True=抓取并入库；False=仅查询查看


@router.post("/run")
async def run(body: ScrapeIn, user: User = Depends(auth.get_current_user)):
    if not body.dpt.strip() or not body.arr.strip():
        return JSONResponse(status_code=400, content={"success": False, "message": "出发、到达机场为必填项"})
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.flightDate or ""):
        return JSONResponse(status_code=400, content={"success": False, "message": "航班日期格式应为 yyyy-MM-dd"})

    result = await scraper.scrape_and_save(body.dict(), source="manual", save=body.save)

    if result.get("error") == "cookie_not_set":
        return JSONResponse(status_code=409, content={"success": False, "message": result["message"]})
    if result.get("error") == "request_failed":
        return JSONResponse(status_code=502, content={"success": False, "message": result["message"]})

    return {
        "success": True,
        "status": result["status"],
        "historyId": result["historyId"],
        "rowCount": result["rowCount"],
        "cookieInvalid": result["cookieInvalid"],
        "duplicate": result.get("duplicate", False),
        "raw": result["raw"],
    }
