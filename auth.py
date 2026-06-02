from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from config import get_config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict, expires_minutes: int = 60 * 8) -> str:
    cfg = get_config()
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return jwt.encode(payload, cfg["secret_key"], algorithm="HS256")

def decode_token(token: str) -> Optional[dict]:
    cfg = get_config()
    try:
        return jwt.decode(token, cfg["secret_key"], algorithms=["HS256"])
    except JWTError:
        return None

def get_admin_user(request: Request):
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    payload = decode_token(token)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    return payload

def get_portal_user(request: Request):
    token = request.cookies.get("portal_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/portal/login"})
    payload = decode_token(token)
    if not payload or payload.get("role") != "dienstleister":
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/portal/login"})
    return payload
