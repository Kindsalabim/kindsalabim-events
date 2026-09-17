import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import ExpiredSignatureError, JWTError, jwt
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

def decode_token(token: str, _ctx: str = "") -> Optional[dict]:
    cfg = get_config()
    try:
        return jwt.decode(token, cfg["secret_key"], algorithms=["HS256"])
    except ExpiredSignatureError:
        print(f"[AUTH]{_ctx} Token ABGELAUFEN")
        return None
    except JWTError as e:
        # z. B. Signatur ungültig -> deutet auf geänderten SECRET_KEY hin
        print(f"[AUTH]{_ctx} Token UNGÜLTIG: {type(e).__name__}: {e}")
        return None

def get_admin_user(request: Request):
    token = request.cookies.get("admin_token")
    if not token:
        print("[AUTH] admin: KEIN admin_token-Cookie gesendet (Browser hat keins / abgelaufen / blockiert)")
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    payload = decode_token(token, " admin:")
    if not payload or payload.get("role") != "admin" or not admin_sitzung_gueltig(payload):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    return payload


def admin_sitzung_gueltig(payload: dict) -> bool:
    """Gehört das (signaturgültige) Token noch zu einem aktiven Zugang?

    Ohne diese Prüfung blieb ein gelöschter oder deaktivierter Zugang bis zum
    Token-Ablauf (30 Tage) eingeloggt – ein gelöschter Büro-Zugang sogar mit
    Vollzugriff, weil unbekannte Zugänge als Inhaber galten. `sv` (Sitzungs-
    Version) wird beim Passwort-Zurücksetzen erhöht und beendet alte Sitzungen;
    Tokens ohne `sv` (vor Einführung ausgestellt) zählen als 0."""
    from database import SessionLocal
    from models import Admin
    from sqlalchemy import func
    email = (payload.get("sub") or payload.get("email") or "").strip().lower()
    if not email:
        return False
    db = SessionLocal()
    try:
        a = db.query(Admin).filter(func.lower(Admin.email) == email).first()
        if not a or not a.aktiv:
            print(f"[AUTH] admin: Zugang {email} gelöscht oder deaktiviert")
            return False
        if int(payload.get("sv") or 0) != int(a.sitzung_version or 0):
            print(f"[AUTH] admin: Sitzung von {email} beendet (Passwort geändert)")
            return False
        return True
    finally:
        db.close()

def create_magic_token(dienstleister, db) -> str:
    """Generiert einen Magic-Link-Token (36h gültig) und speichert ihn."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=36)).isoformat()
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
