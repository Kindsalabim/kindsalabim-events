"""Einmaliger CSV-Import aus Jira Service Management → Dienstleister-Tabelle."""
import csv
import io

from fastapi import APIRouter, Request, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Dienstleister
from auth import get_admin_user
from config import get_config

router = APIRouter(prefix="/admin/import")
templates = Jinja2Templates(directory="templates")


def tpl_context(request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _bool(val: str) -> bool:
    return val.strip().lower() in ("true", "ja", "yes", "1")


def _float(val: str):
    val = val.strip().replace(",", ".")
    try:
        return float(val) if val else None
    except ValueError:
        return None


def _str(val: str):
    return val.strip() or None


def _split_name(name: str):
    name = name.strip()
    parts = name.split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (name, "")


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def import_dienstleister(content: bytes, db: Session):
    text = _decode(content)
    reader = csv.reader(io.StringIO(text))

    # Header überspringen
    try:
        next(reader)
    except StopIteration:
        return 0, 0, []

    imported, skipped, errors = 0, 0, []

    for lineno, row in enumerate(reader, start=2):
        if not row or len(row) < 9:
            continue

        name = _str(row[3])
        if not name:
            continue

        email = _str(row[8])

        # Ohne E-Mail kein Import möglich (Pflichtfeld + Portal-Login)
        if not email:
            skipped += 1
            continue

        # Duplikat-Check per E-Mail
        if db.query(Dienstleister).filter(
                Dienstleister.email == email).first():
            skipped += 1
            continue

        vorname, nachname = _split_name(name)

        is_teamer   = _bool(row[10]) if len(row) > 10 else False
        is_kuenstler = _bool(row[11]) if len(row) > 11 else False

        if is_teamer and is_kuenstler:
            rolle = "Beides"
        elif is_kuenstler:
            rolle = "Künstler"
        else:
            rolle = "Teamer"

        dsgvo_text = row[22].strip() if len(row) > 22 else ""
        dsgvo = "unterzeichnet" in dsgvo_text.lower()

        hat_auto = _bool(row[16]) if len(row) > 16 else False

        try:
            d = Dienstleister(
                vorname=vorname,
                nachname=nachname,
                email=email,
                telefon=_str(row[9])   if len(row) > 9  else None,
                strasse=_str(row[5])   if len(row) > 5  else None,
                stadt=_str(row[6])     if len(row) > 6  else None,
                gebiet=_str(row[7])    if len(row) > 7  else None,
                rolle=rolle,
                fuehrerschein=_bool(row[15]) if len(row) > 15 else False,
                logistiker=hat_auto,
                mobilitaet="Auto" if hat_auto else "ÖPNV",
                kleidergroesse=_str(row[17]) if len(row) > 17 else None,
                verfuegbarkeit=_str(row[14]) if len(row) > 14 else None,
                vertragstyp=_str(row[13])    if len(row) > 13 else None,
                stundensatz_teamer=_float(row[23])    if len(row) > 23 else None,
                stundensatz_kuenstler=_float(row[24]) if len(row) > 24 else None,
                dsgvo_unterzeichnet=dsgvo,
                website=_str(row[21])  if len(row) > 21 else None,
                notizen=_str(row[20])  if len(row) > 20 else None,
                aktiv=True,
            )
            db.add(d)
            db.flush()   # Constraint-Fehler sofort erkennen
            imported += 1
        except Exception as exc:
            db.rollback()
            errors.append(f"Zeile {lineno} ({name}): {exc}")

    db.commit()
    return imported, skipped, errors


# ── Routen ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def import_page(request: Request, user=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/import.html", tpl_context(request))


@router.post("", response_class=HTMLResponse)
async def import_post(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    content = await file.read()
    imported, skipped, errors = import_dienstleister(content, db)
    return templates.TemplateResponse("admin/import.html", tpl_context(
        request,
        result={
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }
    ))
