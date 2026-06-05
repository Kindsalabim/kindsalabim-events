from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from typing import Optional

from database import get_db
from models import Event, Dienstleister, Verfuegbarkeitsanfrage
from auth import get_admin_user, verify_password, hash_password, create_token
from config import get_config
from distance import rank_contractors
from email_service import send_verfuegbarkeitsanfrage, send_briefing

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

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
    resp.set_cookie("admin_token", token, httponly=True, max_age=60*60*8)
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
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    today = datetime.today().strftime("%d.%m.%Y")
    events = db.query(Event).all()
    # Sort by date ascending
    def parse_date(e):
        try:
            return datetime.strptime(e.datum, "%d.%m.%Y")
        except:
            return datetime.max
    upcoming = sorted([e for e in events if e.status != "Abgeschlossen"], key=parse_date)
    past = sorted([e for e in events if e.status == "Abgeschlossen"], key=parse_date, reverse=True)
    return templates.TemplateResponse("admin/dashboard.html",
        tpl_context(request, upcoming=upcoming, past=past, today=today))


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
    hinweise: str = Form(""), aufbau_ab: str = Form(""),
    parkplatz: str = Form(""), outdoor_indoor: str = Form(""),
    verpflegung: bool = Form(False), teamkleidung: bool = Form(True),
):
    ev = Event(
        anlass=anlass, datum=datum, startzeit=startzeit, endzeit=endzeit,
        veranstaltungsort=veranstaltungsort, kunde_firma=kunde_firma,
        kunde_kontakt=kunde_kontakt, kunde_telefon=kunde_telefon,
        kunde_email=kunde_email, produkte=", ".join(produkte),
        anzahl_teamer=anzahl_teamer, anzahl_kuenstler=anzahl_kuenstler,
        hinweise=hinweise, aufbau_ab=aufbau_ab, parkplatz=parkplatz,
        outdoor_indoor=outdoor_indoor, verpflegung=verpflegung,
        teamkleidung=teamkleidung, status="Entwurf"
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
    return templates.TemplateResponse("admin/event_detail.html",
        tpl_context(request, ev=ev, anfragen=anfragen, anfragen_ids=anfragen_ids,
                    ranked_teamer=ranked_teamer, ranked_kuenstler=ranked_kuenstler))

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
    hinweise: str = Form(""), aufbau_ab: str = Form(""),
    parkplatz: str = Form(""), outdoor_indoor: str = Form(""),
    verpflegung: bool = Form(False), teamkleidung: bool = Form(True),
    status: str = Form("Entwurf"),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.anlass = anlass; ev.datum = datum; ev.startzeit = startzeit
    ev.endzeit = endzeit; ev.veranstaltungsort = veranstaltungsort
    ev.kunde_firma = kunde_firma; ev.kunde_kontakt = kunde_kontakt
    ev.kunde_telefon = kunde_telefon; ev.kunde_email = kunde_email
    ev.produkte = ", ".join(produkte); ev.anzahl_teamer = anzahl_teamer
    ev.anzahl_kuenstler = anzahl_kuenstler; ev.hinweise = hinweise
    ev.aufbau_ab = aufbau_ab; ev.parkplatz = parkplatz
    ev.outdoor_indoor = outdoor_indoor; ev.verpflegung = verpflegung
    ev.teamkleidung = teamkleidung; ev.status = status
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/delete")
def event_delete(event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if ev:
        db.delete(ev); db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


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
            frist = (datetime.now() + timedelta(days=3)).strftime("%d.%m.%Y")
            a = Verfuegbarkeitsanfrage(
                event_id=event_id, dienstleister_id=did,
                rolle_anfrage=rolle, status="Ausstehend",
                erstellt_am=datetime.now().strftime("%d.%m.%Y %H:%M"),
                frist_datum=frist
            )
            db.add(a)
            d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
            if d:
                send_verfuegbarkeitsanfrage(d, ev, a.id, base_url)
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
    send_briefing(dienstleister, ev, base_url)
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
    aktiv: bool = Form(True), portal_passwort: str = Form(""),
):
    existing = db.query(Dienstleister).filter(Dienstleister.email == email).first()
    if existing:
        return templates.TemplateResponse("admin/contractor_form.html",
            tpl_context(request, d=None, error="E-Mail bereits vorhanden"))
    pw_hash = hash_password(portal_passwort) if portal_passwort else None
    d = Dienstleister(
        vorname=vorname, nachname=nachname, email=email, telefon=telefon,
        strasse=strasse, plz=plz, stadt=stadt, rolle=rolle,
        erfahrungspunkte=erfahrungspunkte, mobilitaet=mobilitaet,
        kleidergroesse=kleidergroesse, aktiv=aktiv, password_hash=pw_hash
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
    aktiv: bool = Form(True), portal_passwort: str = Form(""),
):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)
    d.vorname = vorname; d.nachname = nachname; d.email = email
    d.telefon = telefon; d.strasse = strasse; d.plz = plz; d.stadt = stadt
    d.rolle = rolle; d.erfahrungspunkte = erfahrungspunkte
    d.mobilitaet = mobilitaet; d.kleidergroesse = kleidergroesse; d.aktiv = aktiv
    if portal_passwort:
        d.password_hash = hash_password(portal_passwort)
    db.commit()
    return RedirectResponse("/admin/dienstleister", status_code=303)

@router.post("/dienstleister/{did}/delete")
def dienstleister_delete(did: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if d: db.delete(d); db.commit()
    return RedirectResponse("/admin/dienstleister", status_code=303)
