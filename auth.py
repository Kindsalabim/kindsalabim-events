import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from config import get_config

# Auf Render (HTTPS) Session-Cookies als secure markieren; lokal (HTTP) nicht,
# sonst sendet der Browser das Cookie über http://127.0.0.1 nicht mit.
COOKIE_SECURE = bool(os.environ.get("RENDER"))

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

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

def create_magic_token(dienstleister, db) -> str:
    """Generiert einen Magic-Link-Token (24h gültig) und speichert ihn."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    dienstleister.magic_token = token
    dienstleister.magic_token_expires = expires
    db.commit()
    return token

def verify_magic_token(token: str, db) -> Optional[object]:
    """Prüft Magic Token – gibt Dienstleister zurück oder None."""
    from models import Dienstleister
    d = db.query(Dienstleister).filter(Dienstleister.magic_token == token).first()
    if not d or not d.magic_token_expires:
        return None
    if datetime.utcnow() > datetime.fromisoformat(d.magic_token_expires):
        return None
    return d

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
