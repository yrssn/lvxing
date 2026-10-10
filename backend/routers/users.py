# -*- coding: utf-8 -*-
"""用户管理（仅管理员）：创建账号、重置密码、启停、删除"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from db import SessionLocal
from models import User

router = APIRouter(prefix="/api/users", tags=["users"])


class UserIn(BaseModel):
    username: str
    password: str
    isAdmin: bool = False


class UserUpdate(BaseModel):
    password: Optional[str] = None
    isActive: Optional[bool] = None
    isAdmin: Optional[bool] = None


def _serialize(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "isAdmin": bool(u.is_admin),
        "isActive": bool(u.is_active),
        "createdAt": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
    }


@router.get("")
def list_users(admin: User = Depends(auth.require_admin)):
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        return {"success": True, "data": [_serialize(u) for u in users]}
    finally:
        db.close()


@router.post("")
def create_user(body: UserIn, admin: User = Depends(auth.require_admin)):
    username = (body.username or "").strip()
    if not (3 <= len(username) <= 32):
        raise HTTPException(status_code=400, detail="用户名长度需 3-32 位")
    if len(body.password or "") < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=409, detail="用户名已存在")
        u = User(
            username=username,
            password_hash=auth.hash_password(body.password),
            is_admin=1 if body.isAdmin else 0,
            is_active=1,
        )
        db.add(u)
        db.commit()
        return {"success": True, "data": _serialize(u)}
    finally:
        db.close()


@router.put("/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(auth.require_admin)):
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="用户不存在")
        if body.password is not None:
            if len(body.password) < 6:
                raise HTTPException(status_code=400, detail="密码至少 6 位")
            u.password_hash = auth.hash_password(body.password)
        if body.isActive is not None:
            if not body.isActive and u.id == admin.id:
                raise HTTPException(status_code=400, detail="不能停用当前登录账号")
            u.is_active = 1 if body.isActive else 0
        if body.isAdmin is not None:
            if u.is_admin and not body.isAdmin:
                admins = db.query(User).filter(User.is_admin == 1, User.is_active == 1).count()
                if admins <= 1:
                    raise HTTPException(status_code=400, detail="至少保留一个管理员")
            u.is_admin = 1 if body.isAdmin else 0
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: User = Depends(auth.require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="用户不存在")
        if u.is_admin:
            admins = db.query(User).filter(User.is_admin == 1).count()
            if admins <= 1:
                raise HTTPException(status_code=400, detail="至少保留一个管理员")
        db.delete(u)
        db.commit()
        return {"success": True}
    finally:
        db.close()
