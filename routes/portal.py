from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date, time, timedelta

from database import get_db
from models import Dienstleister, Verfuegbarkeitsanfrage, Event, EventDatei, DienstleisterSperrzeit, ExternerTeamer
from routes.fotos import generate_presigned_url
from auth import get_portal_user, create_token, create_magic_token, verify_magic_token, COOKIE_SECURE
from config import get_config
from choices import anfrage_ort, de_date, de_month, plz_ort, de_euro

router = APIRouter(prefix="/portal")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_month"] = de_month
templates.env.filters["plz_ort"] = plz_ort
templates.env.globals["anfrage_ort"] = anfrage_ort
templates.env.filters["de_euro"] = de_euro

def tpl_context(request: Request, **kwargs):
    return {"request": request, "cfg": get_config(), **kwargs}


# Absage-Dringlichkeit (bestätigte Einsätze)
ABSAGE_SPERRE_STUNDEN = 48     # darunter: keine App-Absage – Teamer muss telefonisch absagen
ABSAGE_MAIL_STUNDEN   = 7 * 24 # darunter: Büro wird in JEDEM Fall per Mail informiert (ignoriert Schalter)


def _stunden_bis_event(ev) -> float | None:
    """Stunden bis zum Eventbeginn (negativ = schon vorbei, None ohne Datum)."""
    if not ev or not ev.datum:
        return None
    try:
        h, m = (ev.startzeit or "00:00").split(":")
        start = datetime.combine(ev.datum, time(int(h), int(m)))
    except (ValueError, TypeError):
        start = datetime.combine(ev.datum, time(0, 0))
    return (start - datetime.now()).total_seconds() / 3600


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
def portal_magic_auth(token: str, next: str = "", db: Session = Depends(get_db)):
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
    # Sprungziel nur erlauben, wenn interner Portal-Pfad (kein Open-Redirect)
    if next.startswith("/portal/") and "//" not in next[1:]:
        ziel = next
    elif not d.onboarding_abgeschlossen:
        ziel = "/portal/onboarding"
    else:
        ziel = "/portal"
    resp = RedirectResponse(ziel, status_code=303)
    resp.set_cookie("portal_token", session_token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp

@router.get("/dev-preview-onboarding", response_class=HTMLResponse)
def portal_dev_preview(request: Request, db: Session = Depends(get_db)):
    """Nur lokal: Onboarding ohne Login direkt anzeigen."""
    import os
    if os.environ.get("RENDER"):
        from fastapi import HTTPException
        raise HTTPException(404)
    from models import Dienstleister as DL
    d = db.query(DL).first()
    return templates.TemplateResponse("portal/onboarding.html",
        tpl_context(request, dienstleister=d))


@router.get("/logout")
def portal_logout():
    resp = RedirectResponse("/portal/login", status_code=303)
    resp.delete_cookie("portal_token")
    return resp


@router.get("/events/{event_id}/briefing.pdf")
def portal_briefing_pdf(event_id: int, db: Session = Depends(get_db),
                        user=Depends(get_portal_user)):
    """Briefing als PDF für den zugesagten Dienstleister (Download aufs Handy).
    Zugriff nur, wenn der eingeloggte Teamer diesem Event zugesagt hat oder Teamleiter ist."""
    import io
    from briefing_pdf import build_briefing_pdf
    did = int(user["sub"])
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404)
    zugesagt = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == event_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ja").first()
    if not zugesagt and ev.teamleiter_id != did:
        raise HTTPException(403)
    # Gleiche Team-/Regel-Zusammenstellung wie in der Admin-PDF-Route.
    confirmed = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == event_id,
        Verfuegbarkeitsanfrage.status == "Ja").all()
    dienstleister = [a.dienstleister for a in confirmed if a.dienstleister]
    externe = db.query(ExternerTeamer).filter(ExternerTeamer.event_id == event_id).all()
    from notifications import get_setting
    from choices import BRIEFING_REGELN_DEFAULT
    regeln = get_setting(db, "briefing_regeln", BRIEFING_REGELN_DEFAULT).strip() or None
    pdf = build_briefing_pdf(ev, dienstleister, externe, regeln=regeln)
    fname = f"Briefing_{(ev.anlass or 'Event').replace(' ', '_')}_{ev.datum.strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


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

    # Event je Anfrage eager laden – sonst je Anfrage eine Extra-Query (parse_date/Template).
    _mit_event = joinedload(Verfuegbarkeitsanfrage.event)

    # Offene Anfragen (inkl. abgelaufene anzeigen bis Dienstleister antwortet)
    anfragen_raw = db.query(Verfuegbarkeitsanfrage).options(_mit_event).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status.in_(["Ausstehend", "Abgelaufen"])
    ).all()
    anfragen = sorted(anfragen_raw, key=parse_date)

    # Frist-Tage berechnen und ans Template übergeben
    anfragen_data = []
    for a in anfragen:
        dl = days_left(a)
        anfragen_data.append({"anfrage": a, "days_left": dl})

    confirmed = db.query(Verfuegbarkeitsanfrage).options(_mit_event).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ja"
    ).all()
    abgesagt = db.query(Verfuegbarkeitsanfrage).options(_mit_event).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Nein"
    ).all()

    upcoming = sorted([a for a in confirmed if parse_date(a) >= today], key=parse_date)
    past     = sorted([a for a in confirmed if parse_date(a) < today],  key=parse_date, reverse=True)
    abgesagt = sorted(abgesagt, key=parse_date, reverse=True)

    # Extrem kurzfristig (< 48 h): App-Absage gesperrt – Hinweis statt Button
    absage_gesperrt = set()
    for a in upcoming:
        h = _stunden_bis_event(a.event)
        if h is not None and h < ABSAGE_SPERRE_STUNDEN:
            absage_gesperrt.add(a.id)

    # Offene Eventberichte: vergangene Einsätze, bei denen ich Teamleiter bin und noch kein Bericht vorliegt
    berichte_offen = [a for a in past
                      if a.event.teamleiter_id == did and not a.event.bericht_eingereicht_am]

    return templates.TemplateResponse("portal/dashboard.html",
        tpl_context(request, dienstleister=d,
                    anfragen_data=anfragen_data,
                    upcoming=upcoming, past=past, abgesagt=abgesagt,
                    absage_gesperrt=absage_gesperrt,
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
    # Logistiker-Antworten (kombinierte Buttons) auf Status + Transportart abbilden
    transport = None
    if antwort in ("ja_auto", "ja_transporter", "ja_ohne"):
        transport = {"ja_auto": "eigenes_auto", "ja_transporter": "transporter",
                     "ja_ohne": "ohne"}[antwort]
        antwort = "Ja"
    if a and antwort in ("Ja", "Nein"):
        a.status = antwort
        a.notiz = notiz.strip() or None
        from routes.admin import auto_status
        ev = a.event
        # Logistiker-Transportart festhalten und Event-Logistiker setzen/lösen
        transport_text = ""
        if a.als_logistiker and antwort == "Ja" and transport:
            a.logistik_transport = transport
            if transport == "eigenes_auto":
                ev.logistiker_id = a.dienstleister_id
                transport_text = " · 🚚 Material mit eigenem Auto"
            elif transport == "transporter":
                ev.logistiker_id = a.dienstleister_id
                transport_text = " · 🚚 Material mit unserem Transporter"
            else:  # ohne
                if ev.logistiker_id == a.dienstleister_id:
                    ev.logistiker_id = None
                transport_text = " · ⚠ kann das Material NICHT mitnehmen"
        elif antwort == "Nein" and ev.logistiker_id == a.dienstleister_id:
            ev.logistiker_id = None
        db.commit()
        ev.status = auto_status(ev, db)
        # Glocke: Zu-/Absage auf eine Verfügbarkeitsanfrage
        from notifications import notify
        d = a.dienstleister
        name = f"{d.vorname} {d.nachname}" if d else "Ein Dienstleister"
        datum = ev.datum.strftime("%d.%m.%Y")
        if antwort == "Ja":
            notify(db, "dl_zusage", f"Zusage: {name}",
                   f"{name} hat für {ev.anlass} am {datum} zugesagt.{transport_text}",
                   f"/admin/events/{ev.id}")
        else:
            from routes.admin import vorschlag_ersatz, ersatz_label
            v = vorschlag_ersatz(ev, db, a.rolle_anfrage)
            vorschlag = f" Vorschlag: {ersatz_label(v)}." if v else ""
            notify(db, "dl_absage", f"Absage auf Anfrage: {name}",
                   f"{name} hat die Anfrage für {ev.anlass} am {datum} abgelehnt.{vorschlag}",
                   f"/admin/events/{ev.id}")
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
        stunden = _stunden_bis_event(a.event)
        # Extrem kurzfristig (< 48 h): keine App-Absage – der Teamer muss telefonisch absagen,
        # damit das Büro sofort reagieren kann. Status bleibt unverändert.
        if stunden is not None and stunden < ABSAGE_SPERRE_STUNDEN:
            return RedirectResponse("/portal?absage_gesperrt=1", status_code=303)
        a.status = "Nein"
        a.notiz = f"[Nachträgliche Absage] {grund}".strip() if grund else "[Nachträgliche Absage]"
        db.commit()
        from routes.admin import auto_status
        a.event.status = auto_status(a.event, db)
        # Glocke: nachträgliche Absage eines bestätigten Einsatzes
        from notifications import notify, mail_enabled
        d, ev = a.dienstleister, a.event
        name = f"{d.vorname} {d.nachname}" if d else "Ein Dienstleister"
        datum = ev.datum.strftime("%d.%m.%Y")
        zusatz = f" Grund: {grund}" if grund else ""
        from routes.admin import vorschlag_ersatz, ersatz_label
        v = vorschlag_ersatz(ev, db, a.rolle_anfrage)
        vorschlag = f" Vorschlag zum Nachbesetzen: {ersatz_label(v)}." if v else ""
        notify(db, "dl_absage", f"Nachträgliche Absage: {name}",
               f"{name} hat den bestätigten Einsatz {ev.anlass} am {datum} abgesagt.{zusatz}{vorschlag}",
               f"/admin/events/{ev.id}")
        db.commit()
        # Absage-Mail ans Büro: < 7 Tage vor dem Event IMMER (Schalter wird ignoriert –
        # eine kurzfristige Absage darf nie still untergehen), sonst nach Einstellung.
        dringend = stunden is not None and stunden < ABSAGE_MAIL_STUNDEN
        if dringend or mail_enabled(db, "dl_absage"):
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

    def _split(val, sep="\n\n"):
        if not val:
            return "", ""
        teile = val.split(sep, 1)
        return teile[0], (teile[1] if len(teile) > 1 else "")
    kinder_choice, kinder_extra = _split(ev.bericht_kinder, " — ")
    verlauf_choice, verlauf_extra = _split(ev.bericht_verlauf)
    feedback_choice, feedback_extra = _split(ev.bericht_kundenfeedback)
    # "Wie gelaufen" ist Mehrfachauswahl → die gespeicherte Auswahl in eine Liste zerlegen
    verlauf_choices = [c.strip() for c in verlauf_choice.split(",") if c.strip()] if verlauf_choice else []

    return templates.TemplateResponse("portal/bericht.html",
        tpl_context(request, ev=ev, foto_urls=foto_urls,
                    kinder_choice=kinder_choice, kinder_extra=kinder_extra,
                    verlauf_choices=verlauf_choices, verlauf_extra=verlauf_extra,
                    feedback_choice=feedback_choice, feedback_extra=feedback_extra))


def _bericht_combine(choice: str, text: str, sep: str = "\n\n"):
    """Auswahl + optionaler Freitext zu einem Feldwert (oder None, wenn beides leer)."""
    choice, text = choice.strip(), text.strip()
    if choice and text:
        return f"{choice}{sep}{text}"
    return choice or text or None


@router.post("/bericht/{event_id}")
def portal_bericht_save(event_id: int,
                        kinder: str = Form(""), kinder_text: str = Form(""),
                        verlauf: list = Form([]), verlauf_text: str = Form(""),
                        feedback: str = Form(""), feedback_text: str = Form(""),
                        db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev or ev.teamleiter_id != did:
        return RedirectResponse("/portal", status_code=303)
    ev.bericht_kinder = _bericht_combine(kinder, kinder_text, sep=" — ")
    ev.bericht_verlauf = _bericht_combine(", ".join(verlauf), verlauf_text)
    ev.bericht_kundenfeedback = _bericht_combine(feedback, feedback_text)
    ev.bericht_anzahl_kinder = None   # Bucket ersetzt die Freitext-Zahl
    ev.bericht_probleme = None        # in „Wie gelaufen" aufgegangen
    ev.bericht_eingereicht_am = date.today().strftime("%d.%m.%Y")
    db.commit()
    # Automatischer Abschluss prüfen
    from routes.admin import auto_status
    ev.status = auto_status(ev, db)
    # Glocke: Eventbericht eingereicht
    tl = ev.teamleiter
    name = f"{tl.vorname} {tl.nachname}" if tl else "Der Teamleiter"
    from notifications import notify
    notify(db, "bericht", f"Eventbericht: {ev.anlass}",
           f"{name} hat den Bericht für {ev.anlass} am {ev.datum.strftime('%d.%m.%Y')} eingereicht.",
           f"/admin/events/{ev.id}")
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
        Verfuegbarkeitsanfrage.status.in_(["Ausstehend", "Abgelaufen"])
    ).first()
    if a:
        # Frist um 2 Tage verlängern (eine abgelaufene Anfrage wird damit reaktiviert)
        a.status = "Ausstehend"
        frist = a.frist_datum or date.today()
        a.frist_datum = max(frist, date.today()) + timedelta(days=2)
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
    # Direkt aufrufbar — auch wer es schon abgeschlossen hat, kann die Tour erneut ansehen.
    # (Neue Nutzer werden nach dem ersten Login automatisch hierher geleitet.)
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
        # Glocke: Dienstleister hat Urlaub/Sperrzeit eingetragen
        d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
        name = f"{d.vorname} {d.nachname}" if d else "Ein Dienstleister"
        zr = von.strftime("%d.%m.%Y") + (f"–{bis.strftime('%d.%m.%Y')}" if bis != von else "")
        from notifications import notify
        notify(db, "dl_urlaub", f"Urlaub/Sperrzeit: {name}",
               f"{name} ist nicht verfügbar: {zr}." + (f" ({grund.strip()})" if grund.strip() else ""),
               "/admin/dienstleister")
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
