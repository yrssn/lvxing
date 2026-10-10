# -*- coding: utf-8 -*-
"""认证：pbkdf2 密码哈希 + HS256 JWT（标准库实现，无第三方依赖）+ FastAPI 鉴权依赖"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException, Request

from config import TOKEN_EXPIRE_HOURS
from models import AppSetting, User

PBKDF2_ITERATIONS = 100_000

_secret_cache = None


# ---------- 密码 ----------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


# ---------- JWT（HS256，标准库实现） ----------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def get_jwt_secret() -> str:
    """从 app_setting 读取 JWT 密钥，首次调用时生成并持久化（重启后 token 不失效）"""
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.setting_key == "jwt_secret").first()
        if row and row.setting_value:
            _secret_cache = row.setting_value
            return _secret_cache
        secret = secrets.token_hex(32)
        if row:
            row.setting_value = secret
        else:
            db.add(AppSetting(setting_key="jwt_secret", setting_value=secret))
        db.commit()
        _secret_cache = secret
        return secret
    finally:
        db.close()


def create_token(user_id: int, username: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps(
            {
                "uid": user_id,
                "username": username,
                "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
            }
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(get_jwt_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def decode_token(token: str) -> dict:
    try:
        header, payload, sig = token.split(".")
        signing_input = f"{header}.{payload}".encode()
        expected = hmac.new(
            get_jwt_secret().encode(), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig)):
            raise ValueError("bad signature")
        data = json.loads(_b64url_decode(payload))
        if int(data.get("exp", 0)) < time.time():
            raise ValueError("expired")
        return data
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")


# ---------- FastAPI 依赖 ----------

def get_current_user(request: Request) -> User:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_token(auth_header[7:].strip())
    from db import SessionLocal

    db = SessionLocal()
    try:
        user = db.get(User, int(payload.get("uid", 0)))
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="账号不存在或已禁用")
        return user
    finally:
        db.close()


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
