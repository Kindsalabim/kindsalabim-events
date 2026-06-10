from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import calendar as _calendar
from typing import Optional

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

from database import get_db
from models import Event, Dienstleister, Verfuegbarkeitsanfrage, EventDatei
from routes.fotos import generate_presigned_url, download_file
from auth import get_admin_user, verify_password, hash_password, create_token, COOKIE_SECURE
from config import get_config
from distance import rank_contractors
from email_service import send_verfuegbarkeitsanfrage, send_briefing
from choices import ZEITEN, de_date, de_month, de_euro

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_month"] = de_month
templates.env.filters["de_euro"] = de_euro
templates.env.globals["zeiten"] = ZEITEN

PRODUKTE_LIST = [
    "Bunter Bastelspaß", "Spezielle Bastelaktionen (Bakerross)", "Glitzertattoos",
    "Fotoaktion", "Spieleland", "Mitmachzirkus", "Knusperhäuschen", "Lebkuchenherzen",
    "Ballonmodellage", "Kinderschminken", "Buttonmaschine", "Prickeln",
    "Bastelspaß Weihnachten", "Kleinkind Spieleland", "Walkact", "Hüpfburg",
    "Christbaumkugeln gestalten"
]

ANLASS_LIST = [
    "Weihnachtsfeier", "Adventsfeier", "Osteraktion", "Sommerfest",
    "Konferenz / Tagung", "Messe", "Firmenjubiläum", "Hochzeit",
    "Kindergeburtstag", "Kids-Day", "Neueröffnung", "Promotion", "Sonstige"
]

def tpl_context(request: Request, **kwargs):
    cfg = get_config()
    return {"request": request, "cfg": cfg, **kwargs}


# ── Login ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", tpl_context(request))

@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    cfg = get_config()
    if email != cfg["admin_email"]:
        return templates.TemplateResponse("admin/login.html",
            tpl_context(request, error="Ungültige Zugangsdaten"))
    if not cfg.get("admin_password_hash") or not verify_password(password, cfg["admin_password_hash"]):
        return templates.TemplateResponse("admin/login.html",
            tpl_context(request, error="Ungültige Zugangsdaten"))
    token = create_token({"sub": email, "role": "admin"})
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie("admin_token", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60*60*8)
    return resp

@router.get("/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_token")
    return resp


# ── Test E-Mail ────────────────────────────────────────────────────────────────
@router.get("/test-email")
def test_email(user=Depends(get_admin_user)):
    from email_service import send_email
    cfg = get_config()
    try:
        send_email(cfg["admin_email"], "Test E-Mail – Kindsalabim Events", "<p>Der E-Mail-Versand funktioniert! ✅</p>")
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>✅ E-Mail erfolgreich gesendet an <b>" + cfg["admin_email"] + "</b>. Bitte Postfach prüfen.</p>")
    except Exception as e:
        return HTMLResponse(f"<p style='font-family:sans-serif;padding:2rem;color:red'>❌ Fehler: <b>{e}</b></p>")

# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
              month: str = "", day: str = ""):
    today = date.today()
    events = db.query(Event).all()

    def event_date(e):
        return e.datum or date.max

    upcoming = sorted([e for e in events if e.status != "Abgeschlossen"], key=event_date)
    past     = sorted([e for e in events if e.status == "Abgeschlossen"], key=event_date, reverse=True)

    # Fehlende Dienstleister berechnen
    def fehlende_dl(ev):
        """Gibt (fehlende_teamer, fehlende_kuenstler) zurück."""
        anfragen = db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == ev.id,
            Verfuegbarkeitsanfrage.status == "Ja"
        ).all()
        teamer    = sum(1 for a in anfragen if a.rolle_anfrage == "Teamer")
        kuenstler = sum(1 for a in anfragen if a.rolle_anfrage == "Künstler")
        return max(0, ev.anzahl_teamer - teamer), max(0, ev.anzahl_kuenstler - kuenstler)

    upcoming_data = []
    for ev in upcoming:
        ft, fk = fehlende_dl(ev)
        days_until = (event_date(ev) - today).days
        upcoming_data.append({"ev": ev, "fehlende_teamer": ft,
                               "fehlende_kuenstler": fk, "days_until": days_until})

    # Angezeigter Kalendermonat (Navigation per ?month=JJJJ-MM)
    try:
        cur = date.fromisoformat(month + "-01") if month else today.replace(day=1)
    except ValueError:
        cur = today.replace(day=1)
    prev_m = (cur - timedelta(days=1)).replace(day=1)
    next_m = (cur.replace(day=28) + timedelta(days=10)).replace(day=1)

    # Events pro Tag im angezeigten Monat (für die Markierung im Kalender)
    event_map = {}
    for e in events:
        if e.datum and e.datum.year == cur.year and e.datum.month == cur.month:
            event_map.setdefault(e.datum.day, []).append(e)

    # Ausgewählter Tag (?day=JJJJ-MM-TT) -> Events an diesem Tag
    sel_day, sel_events = None, []
    if day:
        try:
            sel_day = date.fromisoformat(day)
            sel_events = sorted([e for e in events if e.datum == sel_day],
                                key=lambda e: e.startzeit or "")
        except ValueError:
            sel_day = None

    kalender = {
        "weeks": _calendar.Calendar(firstweekday=0).monthdayscalendar(cur.year, cur.month),
        "event_map": event_map,
        "year": cur.year, "month": cur.month,
        "label": f"{MONATE[cur.month - 1]} {cur.year}",
        "today": today,
        "prev": prev_m.strftime("%Y-%m"),
        "next": next_m.strftime("%Y-%m"),
        "sel_day": sel_day, "sel_events": sel_events,
    }

    return templates.TemplateResponse("admin/dashboard.html",
        tpl_context(request, upcoming_data=upcoming_data, upcoming=upcoming,
                    past=past, kalender=kalender))


# ── Events ─────────────────────────────────────────────────────────────────────

@router.get("/events/new", response_class=HTMLResponse)
def event_new(request: Request, _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=None, produkte_list=PRODUKTE_LIST, anlass_list=ANLASS_LIST, error=None))

@router.post("/events/new")
def event_create(
    request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(...),
    veranstaltungsort: str = Form(...),
    kunde_firma: str = Form(...), kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    marke: str = Form("Kindsalabim"),
):
    try:
        datum_d = date.fromisoformat(datum)
    except ValueError:
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=None, produkte_list=PRODUKTE_LIST,
                        anlass_list=ANLASS_LIST, error="Bitte ein gültiges Datum wählen."))
    ev = Event(
        anlass=anlass, datum=datum_d, startzeit=startzeit, endzeit=endzeit,
        veranstaltungsort=veranstaltungsort, kunde_firma=kunde_firma,
        kunde_kontakt=kunde_kontakt, kunde_telefon=kunde_telefon,
        kunde_email=kunde_email, produkte=", ".join(produkte),
        anzahl_teamer=anzahl_teamer, anzahl_kuenstler=anzahl_kuenstler,
        hinweise=hinweise, material_mitnahme=material_mitnahme,
        marke=marke, status="Entwurf"
    )
    db.add(ev); db.commit(); db.refresh(ev)
    return RedirectResponse(f"/admin/events/{ev.id}", status_code=303)

@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404)
    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == event_id).all()

    # Ranked contractors
    active = db.query(Dienstleister).filter(Dienstleister.aktiv == True).all()
    ranked_teamer = rank_contractors([d for d in active if d.rolle in ("Teamer", "Beides")], ev.veranstaltungsort)
    ranked_kuenstler = rank_contractors([d for d in active if d.rolle in ("Künstler", "Beides")], ev.veranstaltungsort)

    anfragen_ids = {a.dienstleister_id: a for a in anfragen}

    # Doppelbuchung: bestätigte Einsätze anderer Events am selben Tag
    gebucht_map = {}
    if ev.datum:
        konflikte = db.query(Verfuegbarkeitsanfrage).join(
            Event, Verfuegbarkeitsanfrage.event_id == Event.id).filter(
            Verfuegbarkeitsanfrage.status == "Ja",
            Verfuegbarkeitsanfrage.event_id != ev.id,
            Event.datum == ev.datum,
        ).all()
        for a in konflikte:
            gebucht_map[a.dienstleister_id] = a.event

    planungsdateien = db.query(EventDatei).filter(
        EventDatei.event_id == event_id,
        EventDatei.typ == "planung"
    ).order_by(EventDatei.uploaded_at).all()
    planungs_urls = [(d, generate_presigned_url(d.r2_key)) for d in planungsdateien]

    return templates.TemplateResponse("admin/event_detail.html",
        tpl_context(request, ev=ev, anfragen=anfragen, anfragen_ids=anfragen_ids,
                    ranked_teamer=ranked_teamer, ranked_kuenstler=ranked_kuenstler,
                    gebucht_map=gebucht_map, planungs_urls=planungs_urls))

@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
def event_edit(request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=ev, produkte_list=PRODUKTE_LIST,
                    anlass_list=ANLASS_LIST, error=None))

@router.post("/events/{event_id}/edit")
def event_update(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(...),
    veranstaltungsort: str = Form(...),
    kunde_firma: str = Form(...), kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    status: str = Form("Entwurf"),
    marke: str = Form("Kindsalabim"),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    try:
        ev.datum = date.fromisoformat(datum)
    except ValueError:
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=ev, produkte_list=PRODUKTE_LIST,
                        anlass_list=ANLASS_LIST, error="Bitte ein gültiges Datum wählen."))
    ev.anlass = anlass; ev.startzeit = startzeit
    ev.endzeit = endzeit; ev.veranstaltungsort = veranstaltungsort
    ev.kunde_firma = kunde_firma; ev.kunde_kontakt = kunde_kontakt
    ev.kunde_telefon = kunde_telefon; ev.kunde_email = kunde_email
    ev.produkte = ", ".join(produkte); ev.anzahl_teamer = anzahl_teamer
    ev.anzahl_kuenstler = anzahl_kuenstler; ev.hinweise = hinweise
    ev.material_mitnahme = material_mitnahme; ev.marke = marke; ev.status = status
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/delete")
def event_delete(event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if ev:
        db.delete(ev); db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


# ── Status-Automatik ───────────────────────────────────────────────────────────

def auto_status(ev, db) -> str:
    """Berechnet automatischen Event-Status basierend auf dem Fortschritt."""
    # "Abgeschlossen" ist final (schützt auch Altdaten ohne Bericht/Rechnung)
    if ev.status == "Abgeschlossen":
        return ev.status
    # Nach dem Briefing: automatischer Abschluss, sobald Bericht da UND Rechnung gestellt
    if ev.status == "Briefing gesendet":
        if ev.bericht_eingereicht_am and ev.rechnung_gestellt:
            return "Abgeschlossen"
        return ev.status

    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id).all()
    confirmed = [a for a in anfragen if a.status == "Ja"]

    teamer_ok    = sum(1 for a in confirmed if a.rolle_anfrage == "Teamer")    >= ev.anzahl_teamer
    kuenstler_ok = sum(1 for a in confirmed if a.rolle_anfrage == "Künstler")  >= ev.anzahl_kuenstler

    # Logistiker: mind. 1 bestätigter Logistiker nötig (außer nur Künstler)
    nur_kuenstler = (ev.anzahl_teamer == 0 and ev.anzahl_kuenstler > 0)
    logistiker_ok = nur_kuenstler or any(
        a.dienstleister.logistiker for a in confirmed if a.dienstleister)

    # Material: wenn Mitnahme nötig, muss es auch bestellt sein
    material_ok = (not ev.material_mitnahme) or ev.material_bestellt

    if teamer_ok and kuenstler_ok and logistiker_ok and material_ok and ev.cl_eingereicht_am:
        return "Planung fertig"
    if ev.cl_eingereicht_am:
        return "Checkliste eingegangen"
    if ev.checklist_token and not ev.cl_eingereicht_am:
        return "Checkliste geschickt"
    if anfragen:
        return "Dienstleister angefragt"
    return ev.status  # bleibt "Entwurf" / manuell gesetzt


# ── Verfügbarkeitsanfragen ─────────────────────────────────────────────────────

@router.post("/events/{event_id}/anfragen")
def send_anfragen(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    dienstleister_ids: list = Form([]),
    rolle: str = Form("Teamer"),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    base_url = str(request.base_url).rstrip("/")
    for did in dienstleister_ids:
        did = int(did)
        existing = db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == event_id,
            Verfuegbarkeitsanfrage.dienstleister_id == did
        ).first()
        if not existing:
            frist = date.today() + timedelta(days=3)
            a = Verfuegbarkeitsanfrage(
                event_id=event_id, dienstleister_id=did,
                rolle_anfrage=rolle, status="Ausstehend",
                erstellt_am=datetime.now().strftime("%d.%m.%Y %H:%M"),
                frist_datum=frist
            )
            db.add(a)
            d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
            if d:
                from auth import create_magic_token
                token = create_magic_token(d, db)
                magic_url = f"{base_url}/portal/auth/{token}"
                send_verfuegbarkeitsanfrage(d, ev, a.id, base_url, magic_url=magic_url)
    db.commit()
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/material-bestellt")
def toggle_material_bestellt(
    event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    bestellt: str = Form(""),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.material_bestellt = (bestellt == "1")
    db.commit()
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/rechnung-gestellt")
def toggle_rechnung_gestellt(
    event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    gestellt: str = Form(""),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.rechnung_gestellt = (gestellt == "1")
    db.commit()
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/teamleiter")
def set_teamleiter(
    event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    teamleiter_id: str = Form(""),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.teamleiter_id = int(teamleiter_id) if teamleiter_id else None
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/checklist")
def send_checklist(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)
):
    import uuid
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if not ev.kunde_email:
        return RedirectResponse(f"/admin/events/{event_id}?error=keine_email", status_code=303)
    if not ev.checklist_token:
        ev.checklist_token = str(uuid.uuid4())
    db.commit()
    base_url = str(request.base_url).rstrip("/")
    from email_service import send_checklist_email
    send_checklist_email(ev, base_url)
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?checklist_sent=1", status_code=303)


@router.post("/events/{event_id}/briefing")
def send_briefing_route(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    confirmed = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == event_id,
        Verfuegbarkeitsanfrage.status == "Ja"
    ).all()
    dienstleister = [a.dienstleister for a in confirmed]
    base_url = str(request.base_url).rstrip("/")
    # Planungsdateien (Lageplan etc.) als Anhang mitschicken
    planung = db.query(EventDatei).filter(
        EventDatei.event_id == event_id, EventDatei.typ == "planung"
    ).all()
    anhaenge = [(d.filename, download_file(d.r2_key)) for d in planung]
    anhaenge = [(fn, data) for fn, data in anhaenge if data]
    send_briefing(dienstleister, ev, base_url, anhaenge or None)
    ev.status = "Briefing gesendet"
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)


# ── Dienstleister Einladung ────────────────────────────────────────────────────

@router.post("/dienstleister/{did}/einladung")
def dienstleister_einladung(request: Request, did: int,
                             db: Session = Depends(get_db), _=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)
    base_url = str(request.base_url).rstrip("/")
    from email_service import send_einladung
    send_einladung(d, base_url)
    return RedirectResponse(f"/admin/dienstleister?einladung_sent={d.id}", status_code=303)


# ── Dienstleister ──────────────────────────────────────────────────────────────

@router.get("/dienstleister", response_class=HTMLResponse)
def dienstleister_list(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    all_d = db.query(Dienstleister).order_by(Dienstleister.nachname).all()
    return templates.TemplateResponse("admin/contractors.html",
        tpl_context(request, dienstleister=all_d))

@router.get("/dienstleister/new", response_class=HTMLResponse)
def dienstleister_new(request: Request, _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/contractor_form.html",
        tpl_context(request, d=None, error=None))

@router.post("/dienstleister/new")
def dienstleister_create(
    request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
    vorname: str = Form(...), nachname: str = Form(...),
    email: str = Form(...), telefon: str = Form(""),
    strasse: str = Form(""), plz: str = Form(""), stadt: str = Form(""),
    rolle: str = Form("Teamer"), erfahrungspunkte: int = Form(0),
    mobilitaet: str = Form("Auto"), kleidergroesse: str = Form(""),
    aktiv: bool = Form(False), logistiker: bool = Form(False),
    fuehrerschein: bool = Form(False), portal_passwort: str = Form(""),
    gebiet: str = Form(""), verfuegbarkeit: str = Form(""),
    vertragstyp: str = Form(""), stundensatz_teamer: str = Form(""),
    stundensatz_kuenstler: str = Form(""),
    dsgvo_unterzeichnet: bool = Form(False),
    website: str = Form(""), notizen: str = Form(""),
):
    existing = db.query(Dienstleister).filter(Dienstleister.email == email).first()
    if existing:
        return templates.TemplateResponse("admin/contractor_form.html",
            tpl_context(request, d=None, error="E-Mail bereits vorhanden"))
    pw_hash = hash_password(portal_passwort) if portal_passwort else None

    def _f(s):
        try: return float(s.replace(",", ".")) if s.strip() else None
        except: return None

    d = Dienstleister(
        vorname=vorname, nachname=nachname, email=email, telefon=telefon,
        strasse=strasse, plz=plz, stadt=stadt, rolle=rolle,
        erfahrungspunkte=erfahrungspunkte, mobilitaet=mobilitaet,
        kleidergroesse=kleidergroesse, aktiv=aktiv, logistiker=logistiker,
        fuehrerschein=fuehrerschein, password_hash=pw_hash,
        gebiet=gebiet.strip() or None, verfuegbarkeit=verfuegbarkeit.strip() or None,
        vertragstyp=vertragstyp.strip() or None,
        stundensatz_teamer=_f(stundensatz_teamer),
        stundensatz_kuenstler=_f(stundensatz_kuenstler),
        dsgvo_unterzeichnet=dsgvo_unterzeichnet,
        website=website.strip() or None, notizen=notizen.strip() or None,
    )
    db.add(d); db.commit()
    return RedirectResponse("/admin/dienstleister", status_code=303)

@router.get("/dienstleister/{did}/edit", response_class=HTMLResponse)
def dienstleister_edit(request: Request, did: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)
    return templates.TemplateResponse("admin/contractor_form.html",
        tpl_context(request, d=d, error=None))

@router.post("/dienstleister/{did}/edit")
def dienstleister_update(
    request: Request, did: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    vorname: str = Form(...), nachname: str = Form(...),
    email: str = Form(...), telefon: str = Form(""),
    strasse: str = Form(""), plz: str = Form(""), stadt: str = Form(""),
    rolle: str = Form("Teamer"), erfahrungspunkte: int = Form(0),
    mobilitaet: str = Form("Auto"), kleidergroesse: str = Form(""),
    aktiv: bool = Form(False), logistiker: bool = Form(False),
    fuehrerschein: bool = Form(False), portal_passwort: str = Form(""),
    gebiet: str = Form(""), verfuegbarkeit: str = Form(""),
    vertragstyp: str = Form(""), stundensatz_teamer: str = Form(""),
    stundensatz_kuenstler: str = Form(""),
    dsgvo_unterzeichnet: bool = Form(False),
    website: str = Form(""), notizen: str = Form(""),
):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)

    def _f(s):
        try: return float(s.replace(",", ".")) if s.strip() else None
        except: return None

    d.vorname = vorname; d.nachname = nachname; d.email = email
    d.telefon = telefon; d.strasse = strasse; d.plz = plz; d.stadt = stadt
    d.rolle = rolle; d.erfahrungspunkte = erfahrungspunkte
    d.mobilitaet = mobilitaet; d.kleidergroesse = kleidergroesse
    d.aktiv = aktiv; d.logistiker = logistiker; d.fuehrerschein = fuehrerschein
    d.gebiet = gebiet.strip() or None
    d.verfuegbarkeit = verfuegbarkeit.strip() or None
    d.vertragstyp = vertragstyp.strip() or None
    d.stundensatz_teamer = _f(stundensatz_teamer)
    d.stundensatz_kuenstler = _f(stundensatz_kuenstler)
    d.dsgvo_unterzeichnet = dsgvo_unterzeichnet
    d.website = website.strip() or None
    d.notizen = notizen.strip() or None
    if portal_passwort:
        d.password_hash = hash_password(portal_passwort)
    db.commit()
    return RedirectResponse("/admin/dienstleister", status_code=303)

@router.post("/dienstleister/{did}/delete")
def dienstleister_delete(did: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if d: db.delete(d); db.commit()
    return RedirectResponse("/admin/dienstleister", status_code=303)
