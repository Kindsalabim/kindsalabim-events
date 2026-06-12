from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta

from database import get_db
from models import Dienstleister, Verfuegbarkeitsanfrage, Event, EventDatei, DienstleisterSperrzeit
from routes.fotos import generate_presigned_url
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
    ziel = "/portal/onboarding" if not d.onboarding_abgeschlossen else "/portal"
    resp = RedirectResponse(ziel, status_code=303)
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

    # Offene Eventberichte: vergangene Einsätze, bei denen ich Teamleiter bin und noch kein Bericht vorliegt
    berichte_offen = [a for a in past
                      if a.event.teamleiter_id == did and not a.event.bericht_eingereicht_am]

    return templates.TemplateResponse("portal/dashboard.html",
        tpl_context(request, dienstleister=d,
                    anfragen_data=anfragen_data,
                    upcoming=upcoming, past=past, abgesagt=abgesagt,
                    berichte_offen=berichte_offen))


# ── Antwort ────────────────────────────────────────────────────────────────────

@router.post("/antwort/{anfrage_id}")
def portal_antwort(anfrage_id: int, antwort: str = Form(...),
                   notiz: str = Form(""),
                   db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did
    ).first()
    if a and antwort in ("Ja", "Nein"):
        a.status = antwort
        a.notiz = notiz.strip() or None
        db.commit()
        # Event-Status automatisch aktualisieren
        from routes.admin import auto_status
        ev = a.event
        ev.status = auto_status(ev, db)
        db.commit()
    return RedirectResponse("/portal", status_code=303)


# ── Nachträgliche Absage (bestätigte Einsätze) ────────────────────────────────

@router.post("/absage/{anfrage_id}")
def portal_absage(request: Request, anfrage_id: int, grund: str = Form(""),
                  db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ja"
    ).first()
    if a:
        a.status = "Nein"
        a.notiz = f"[Nachträgliche Absage] {grund}".strip() if grund else "[Nachträgliche Absage]"
        db.commit()
        from routes.admin import auto_status
        a.event.status = auto_status(a.event, db)
        db.commit()
        from email_service import send_absage_admin
        base_url = str(request.base_url).rstrip("/")
        send_absage_admin(a.dienstleister, a.event, grund, base_url)
    return RedirectResponse("/portal?absage=1", status_code=303)


# ── Eventbericht (nur Teamleiter) ───────────────────────────────────────────────

@router.get("/bericht/{event_id}", response_class=HTMLResponse)
def portal_bericht_form(request: Request, event_id: int,
                        db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev or ev.teamleiter_id != did:
        return RedirectResponse("/portal", status_code=303)
    fotos = db.query(EventDatei).filter(
        EventDatei.event_id == event_id, EventDatei.typ == "bericht_foto"
    ).order_by(EventDatei.uploaded_at).all()
    foto_urls = [(f, generate_presigned_url(f.r2_key)) for f in fotos]
    return templates.TemplateResponse("portal/bericht.html",
        tpl_context(request, ev=ev, foto_urls=foto_urls))


@router.post("/bericht/{event_id}")
def portal_bericht_save(event_id: int,
                        anzahl_kinder: str = Form(""),
                        verlauf: str = Form(""),
                        probleme: str = Form(""),
                        kundenfeedback: str = Form(""),
                        db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev or ev.teamleiter_id != did:
        return RedirectResponse("/portal", status_code=303)
    try:
        ev.bericht_anzahl_kinder = int(anzahl_kinder) if anzahl_kinder.strip() else None
    except ValueError:
        ev.bericht_anzahl_kinder = None
    ev.bericht_verlauf = verlauf.strip() or None
    ev.bericht_probleme = probleme.strip() or None
    ev.bericht_kundenfeedback = kundenfeedback.strip() or None
    ev.bericht_eingereicht_am = date.today().strftime("%d.%m.%Y")
    db.commit()
    # Automatischer Abschluss prüfen
    from routes.admin import auto_status
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse("/portal?bericht=1", status_code=303)


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


# ── Onboarding ────────────────────────────────────────────────────────────────

@router.get("/onboarding", response_class=HTMLResponse)
def portal_onboarding(request: Request, db: Session = Depends(get_db),
                      user=Depends(get_portal_user)):
    did = int(user["sub"])
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    # Wer Onboarding schon abgeschlossen hat, wird weitergeleitet
    if d and d.onboarding_abgeschlossen:
        return RedirectResponse("/portal", status_code=303)
    return templates.TemplateResponse("portal/onboarding.html",
        tpl_context(request, dienstleister=d))


@router.post("/onboarding/abschliessen")
def portal_onboarding_abschliessen(db: Session = Depends(get_db),
                                   user=Depends(get_portal_user)):
    did = int(user["sub"])
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if d:
        d.onboarding_abgeschlossen = True
        db.commit()
    return RedirectResponse("/portal", status_code=303)


# ── Sperrzeiten (Nicht-Verfügbarkeit) ─────────────────────────────────────────

@router.get("/verfuegbarkeit", response_class=HTMLResponse)
def portal_verfuegbarkeit(request: Request, db: Session = Depends(get_db),
                          user=Depends(get_portal_user)):
    did = int(user["sub"])
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    sperrzeiten = db.query(DienstleisterSperrzeit).filter(
        DienstleisterSperrzeit.dienstleister_id == did
    ).order_by(DienstleisterSperrzeit.von_datum).all()
    return templates.TemplateResponse("portal/verfuegbarkeit.html",
        tpl_context(request, dienstleister=d, sperrzeiten=sperrzeiten))


@router.post("/verfuegbarkeit/hinzufuegen")
def portal_sperrzeit_hinzufuegen(
    von_datum: str = Form(...),
    bis_datum: str = Form(...),
    grund: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_portal_user)
):
    did = int(user["sub"])
    try:
        von = date.fromisoformat(von_datum)
        bis = date.fromisoformat(bis_datum)
        if bis < von:
            von, bis = bis, von
        sz = DienstleisterSperrzeit(
            dienstleister_id=did,
            von_datum=von,
            bis_datum=bis,
            grund=grund.strip() or None
        )
        db.add(sz)
        db.commit()
    except (ValueError, Exception):
        pass
    return RedirectResponse("/portal/verfuegbarkeit?ok=1", status_code=303)


@router.post("/verfuegbarkeit/{sz_id}/loeschen")
def portal_sperrzeit_loeschen(sz_id: int, db: Session = Depends(get_db),
                               user=Depends(get_portal_user)):
    did = int(user["sub"])
    sz = db.query(DienstleisterSperrzeit).filter(
        DienstleisterSperrzeit.id == sz_id,
        DienstleisterSperrzeit.dienstleister_id == did
    ).first()
    if sz:
        db.delete(sz)
        db.commit()
    return RedirectResponse("/portal/verfuegbarkeit", status_code=303)
