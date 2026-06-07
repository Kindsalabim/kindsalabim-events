from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta

from database import get_db
from models import Dienstleister, Verfuegbarkeitsanfrage, Event
from auth import get_portal_user, create_token, create_magic_token, verify_magic_token, COOKIE_SECURE
from config import get_config
from choices import de_date, de_month

router = APIRouter(prefix="/portal")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_month"] = de_month

def tpl_context(request: Request, **kwargs):
    return {"request": request, "cfg": get_config(), **kwargs}


# ── Login (Magic Link) ─────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def portal_login(request: Request, sent: str = ""):
    return templates.TemplateResponse("portal/login.html",
        tpl_context(request, sent=sent))

@router.post("/login")
def portal_login_post(request: Request, db: Session = Depends(get_db),
                      email: str = Form(...)):
    d = db.query(Dienstleister).filter(Dienstleister.email == email).first()
    if d and d.aktiv:
        token = create_magic_token(d, db)
        base_url = str(request.base_url).rstrip("/")
        from email_service import send_magic_link
        send_magic_link(d, token, base_url)
    # Immer gleiche Antwort – keine Info ob E-Mail existiert
    return RedirectResponse("/portal/login?sent=1", status_code=303)

@router.get("/auth/{token}")
def portal_magic_auth(token: str, db: Session = Depends(get_db)):
    d = verify_magic_token(token, db)
    if not d:
        return RedirectResponse("/portal/login?error=1", status_code=303)
    # Token einmalig entwerten
    d.magic_token = None
    d.magic_token_expires = None
    db.commit()
    # 30-Tage-Session
    session_token = create_token(
        {"sub": str(d.id), "role": "dienstleister"},
        expires_minutes=60 * 24 * 30
    )
    resp = RedirectResponse("/portal", status_code=303)
    resp.set_cookie("portal_token", session_token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp

@router.get("/logout")
def portal_logout():
    resp = RedirectResponse("/portal/login", status_code=303)
    resp.delete_cookie("portal_token")
    return resp


# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def portal_dashboard(request: Request, db: Session = Depends(get_db),
                     user=Depends(get_portal_user)):
    did = int(user["sub"])
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    today = date.today()

    def parse_date(a):
        return a.event.datum or date.max

    def days_left(a):
        if not a.frist_datum:
            return None
        return (a.frist_datum - today).days

    # Offene Anfragen (inkl. abgelaufene anzeigen bis Dienstleister antwortet)
    anfragen_raw = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ausstehend"
    ).all()
    anfragen = sorted(anfragen_raw, key=parse_date)

    # Frist-Tage berechnen und ans Template übergeben
    anfragen_data = []
    for a in anfragen:
        dl = days_left(a)
        anfragen_data.append({"anfrage": a, "days_left": dl})

    confirmed = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ja"
    ).all()
    abgesagt = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Nein"
    ).all()

    upcoming = sorted([a for a in confirmed if parse_date(a) >= today], key=parse_date)
    past     = sorted([a for a in confirmed if parse_date(a) < today],  key=parse_date, reverse=True)
    abgesagt = sorted(abgesagt, key=parse_date, reverse=True)

    return templates.TemplateResponse("portal/dashboard.html",
        tpl_context(request, dienstleister=d,
                    anfragen_data=anfragen_data,
                    upcoming=upcoming, past=past, abgesagt=abgesagt))


# ── Antwort ────────────────────────────────────────────────────────────────────

@router.post("/antwort/{anfrage_id}")
def portal_antwort(anfrage_id: int, antwort: str = Form(...),
                   db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did
    ).first()
    if a and antwort in ("Ja", "Nein"):
        a.status = antwort
        db.commit()
        # Event-Status automatisch aktualisieren
        from routes.admin import auto_status
        ev = a.event
        ev.status = auto_status(ev, db)
        db.commit()
    return RedirectResponse("/portal", status_code=303)


# ── Frist verlängern ───────────────────────────────────────────────────────────

@router.post("/verlaengern/{anfrage_id}")
def portal_verlaengern(anfrage_id: int, db: Session = Depends(get_db),
                       user=Depends(get_portal_user)):
    did = int(user["sub"])
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ausstehend"
    ).first()
    if a:
        # Frist um 2 Tage verlängern
        frist = a.frist_datum or date.today()
        a.frist_datum = frist + timedelta(days=2)
        a.frist_verlaengert = True
        db.commit()
        # Admin benachrichtigen
        from email_service import send_frist_verlaengerung
        from config import get_config
        cfg = get_config()
        send_frist_verlaengerung(a.dienstleister, a.event, cfg["admin_email"])
    return RedirectResponse("/portal", status_code=303)
