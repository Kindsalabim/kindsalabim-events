"""Datei-Upload/-Download/-Lösch-Logik für R2.

Admin-Routen:   /admin/events/{id}/dateien      → typ="planung"
Portal-Routen:  /portal/events/{id}/fotos       → typ="bericht_foto"
"""
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth import get_admin_user, get_portal_user
from config import get_config
from database import get_db
from models import Event, EventDatei

router = APIRouter()

ALLOWED_PLANUNG  = {"image/jpeg", "image/png", "image/webp", "image/gif",
                    "application/pdf"}
ALLOWED_FOTO     = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE_MB = 20


_r2_cache = {}  # Modul-global: boto3-Client einmal bauen und wiederverwenden (Review Gruppe 4)


def _r2_client():
    if "client" in _r2_cache:
        return _r2_cache["client"]
    cfg = get_config()
    account_id = cfg.get("r2_account_id", "")
    access_key = cfg.get("r2_access_key_id", "")
    secret_key = cfg.get("r2_secret_access_key", "")
    if not (account_id and access_key and secret_key):
        return None
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    _r2_cache["client"] = client
    return client


def generate_presigned_url(r2_key: str, expires: int = 3600) -> str | None:
    cfg = get_config()
    client = _r2_client()
    if not client:
        return None
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg["r2_bucket"], "Key": r2_key},
            ExpiresIn=expires,
        )
    except Exception:
        return None


def download_file(r2_key: str) -> bytes | None:
    cfg = get_config()
    client = _r2_client()
    if not client:
        return None
    try:
        resp = client.get_object(Bucket=cfg["r2_bucket"], Key=r2_key)
        return resp["Body"].read()
    except Exception:
        return None


def _upload(data: bytes, event_id: int, filename: str, content_type: str, typ: str, db: Session):
    cfg = get_config()
    client = _r2_client()
    if not client:
        raise HTTPException(500, "R2 nicht konfiguriert.")

    ext = (filename or "datei").rsplit(".", 1)[-1].lower()
    r2_key = f"events/{event_id}/{typ}/{uuid.uuid4().hex}.{ext}"

    client.put_object(
        Bucket=cfg["r2_bucket"],
        Key=r2_key,
        Body=data,
        ContentType=content_type,
    )

    datei = EventDatei(
        event_id=event_id,
        r2_key=r2_key,
        filename=filename or r2_key,
        typ=typ,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(datei)
    db.commit()


# ── Admin: Planungsdateien ─────────────────────────────────────────────────────

@router.post("/admin/events/{event_id}/dateien")
async def upload_planungsdatei(
    event_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404)
    if file.content_type not in ALLOWED_PLANUNG:
        raise HTTPException(400, "Nur JPG, PNG, WEBP, GIF oder PDF erlaubt.")
    data = await file.read()
    if len(data) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"Datei zu groß (max. {MAX_SIZE_MB} MB).")
    _upload(data, event_id, file.filename or "datei", file.content_type, "planung", db)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)


@router.post("/admin/events/{event_id}/dateien/{datei_id}/delete")
def delete_planungsdatei(
    event_id: int,
    datei_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    _delete(event_id, datei_id, db)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)


# ── Admin: Auftragsbestätigung ─────────────────────────────────────────────────

@router.post("/admin/events/{event_id}/auftragsbestaetigung")
async def upload_auftragsbestaetigung(
    event_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404)
    if file.content_type not in ALLOWED_PLANUNG:
        raise HTTPException(400, "Nur JPG, PNG, WEBP, GIF oder PDF erlaubt.")
    data = await file.read()
    if len(data) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"Datei zu groß (max. {MAX_SIZE_MB} MB).")
    _upload(data, event_id, file.filename or "auftragsbestaetigung",
            file.content_type, "auftragsbestaetigung", db)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)


@router.post("/admin/events/{event_id}/auftragsbestaetigung/{datei_id}/delete")
def delete_auftragsbestaetigung(
    event_id: int,
    datei_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    _delete(event_id, datei_id, db)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)


@router.get("/admin/events/{event_id}/auftragsbestaetigung/view")
def view_auftragsbestaetigung(
    event_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    """Stabiler Link zur neuesten Auftragsbestätigung – leitet auf eine frische
    presigned URL um (für den späteren Google-Kalender-Eintrag nutzbar)."""
    datei = db.query(EventDatei).filter(
        EventDatei.event_id == event_id,
        EventDatei.typ == "auftragsbestaetigung",
    ).order_by(EventDatei.uploaded_at.desc()).first()
    if not datei:
        raise HTTPException(404, "Keine Auftragsbestätigung hinterlegt.")
    url = generate_presigned_url(datei.r2_key)
    if not url:
        raise HTTPException(500, "Datei-Speicher nicht konfiguriert.")
    return RedirectResponse(url, status_code=307)


# ── Portal: Event-Fotos (Teamleiter) ──────────────────────────────────────────

@router.post("/portal/events/{event_id}/fotos")
async def upload_bericht_foto(
    event_id: int,
    file: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_portal_user),
):
    """Nimmt ein oder mehrere Fotos (Galerie-Mehrfachauswahl). Ungültige Dateien
    (falscher Typ / zu groß) werden übersprungen, gültige hochgeladen."""
    did = int(user["sub"])
    ev = db.get(Event, event_id)
    if not ev or ev.teamleiter_id != did:
        raise HTTPException(403)
    for f in file:
        if f.content_type not in ALLOWED_FOTO:
            continue
        data = await f.read()
        if not data or len(data) > MAX_SIZE_MB * 1024 * 1024:
            continue
        _upload(data, event_id, f.filename or "foto", f.content_type, "bericht_foto", db)
    return RedirectResponse(f"/portal/bericht/{event_id}", status_code=303)


@router.post("/portal/events/{event_id}/fotos/{datei_id}/delete")
def delete_bericht_foto(
    event_id: int,
    datei_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_portal_user),
):
    did = int(user["sub"])
    ev = db.get(Event, event_id)
    if not ev or ev.teamleiter_id != did:
        raise HTTPException(403)
    # SICHERHEIT: nur eigene Event-Fotos – niemals Auftragsbestätigung/Planungsdateien.
    # Ohne diese Typ-Sperre könnte ein Teamleiter über eine geratene datei_id die
    # (für ihn unsichtbare) Auftragsbestätigung seines Events löschen.
    _delete(event_id, datei_id, db, nur_typ="bericht_foto")
    return RedirectResponse(f"/portal/bericht/{event_id}", status_code=303)


# ── Shared ─────────────────────────────────────────────────────────────────────

def _delete(event_id: int, datei_id: int, db: Session, nur_typ: str | None = None):
    datei = db.get(EventDatei, datei_id)
    if not datei or datei.event_id != event_id:
        raise HTTPException(404)
    if nur_typ is not None and datei.typ != nur_typ:
        raise HTTPException(404)
    cfg = get_config()
    client = _r2_client()
    if client:
        try:
            client.delete_object(Bucket=cfg["r2_bucket"], Key=datei.r2_key)
        except Exception:
            pass
    db.delete(datei)
    db.commit()
