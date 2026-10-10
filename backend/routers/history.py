# -*- coding: utf-8 -*-
"""查询历史：抓取入库记录的管理（原 /api/history 接口迁移 + 鉴权）"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

import auth
import db
from models import User

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def history(limit: int = Query(50, ge=1, le=200), user: User = Depends(auth.get_current_user)):
    try:
        return {"success": True, "data": db.list_history(limit)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})


@router.get("/{history_id}/records")
def history_records(history_id: int, user: User = Depends(auth.get_current_user)):
    try:
        return {"success": True, "data": db.get_history_records(history_id)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})


@router.delete("/{history_id}")
def history_delete(history_id: int, user: User = Depends(auth.get_current_user)):
    try:
        deleted, n = db.delete_history(history_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"success": False, "message": "记录不存在"})
        return {"success": True, "deletedRows": n}
    except Exception as e:
        return JSONResponse(status_code=503, content={"success": False, "message": f"MySQL 不可用: {e}"})
