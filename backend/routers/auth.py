# -*- coding: utf-8 -*-
"""登录 / 当前用户（开放注册已移除，账号由管理员在「用户管理」中创建）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from db import SessionLocal
from models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: AuthIn):
    username = (body.username or "").strip()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active or not auth.verify_password(body.password or "", user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = auth.create_token(user.id, user.username)
        return {
            "success": True,
            "data": {"token": token, "username": user.username, "isAdmin": bool(user.is_admin)},
        }
    finally:
        db.close()


@router.get("/me")
def me(user: User = Depends(auth.get_current_user)):
    return {
        "success": True,
        "data": {"id": user.id, "username": user.username, "isAdmin": bool(user.is_admin)},
    }
