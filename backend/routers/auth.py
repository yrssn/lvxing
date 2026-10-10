# -*- coding: utf-8 -*-
"""注册 / 登录 / 当前用户"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from db import SessionLocal
from models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthIn(BaseModel):
    username: str
    password: str


def _validate(username: str, password: str):
    username = (username or "").strip()
    if not (3 <= len(username) <= 32):
        raise HTTPException(status_code=400, detail="用户名长度需 3-32 位")
    if len(password or "") < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    return username, password


@router.post("/register")
def register(body: AuthIn):
    username, password = _validate(body.username, body.password)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = User(username=username, password_hash=auth.hash_password(password), is_active=1)
        db.add(user)
        db.commit()
        return {"success": True, "data": {"id": user.id, "username": user.username}}
    finally:
        db.close()


@router.post("/login")
def login(body: AuthIn):
    username = (body.username or "").strip()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active or not auth.verify_password(body.password or "", user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = auth.create_token(user.id, user.username)
        return {"success": True, "data": {"token": token, "username": user.username}}
    finally:
        db.close()


@router.get("/me")
def me(user: User = Depends(auth.get_current_user)):
    return {"success": True, "data": {"id": user.id, "username": user.username}}
