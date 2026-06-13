from fastapi import APIRouter, Request, Depends, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import calendar as _calendar
from typing import Optional

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

from sqlalchemy import func
from database import get_db
from models import Event, Dienstleister, Verfuegbarkeitsanfrage, EventDatei, Admin, Kunde, DienstleisterSperrzeit
import secrets
from routes.fotos import generate_presigned_url, download_file
from auth import get_admin_user, verify_password, hash_password, create_token, COOKIE_SECURE
from config import get_config
from distance import rank_contractors, get_coords_for_plz, get_coords_for_address
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


def link_kunde(db, ev, firma, kontakt, telefon, email, marke):
    """Verknüpft das Event mit einem CRM-Kunden (Match über Firma, sonst neu anlegen)."""
    firma = (firma or "").strip()
    if not firma:
        return
    k = db.query(Kunde).filter(func.lower(Kunde.firma) == firma.lower()).first()
    if not k:
        jetzt = datetime.now().isoformat(timespec="seconds")
        k = Kunde(firma=firma, ansprechpartner=(kontakt or "").strip() or None,
                  telefon=(telefon or "").strip() or None, email=(email or "").strip() or None,
                  marke=marke or "Kindsalabim", pipeline_status="gebucht",
                  erstellt_am=jetzt, aktualisiert_am=jetzt)
        db.add(k); db.flush()
    ev.kunde_id = k.id


# ── Login ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", tpl_context(request))

@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    a = db.query(Admin).filter(Admin.email == email, Admin.aktiv == True).first()
    if not a or not verify_password(password, a.password_hash):
        return templates.TemplateResponse("admin/login.html",
            tpl_context(request, error="Ungültige Zugangsdaten"))
    token = create_token({"sub": a.email, "role": "admin"})
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie("admin_token", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60*60*8)
    return resp

@router.get("/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_token")
    return resp


# ── Passwort vergessen / zurücksetzen ───────────────────────────────────────────

@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request, sent: str = ""):
    return templates.TemplateResponse("admin/forgot.html", tpl_context(request, sent=sent))

@router.post("/forgot")
def forgot_post(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    a = db.query(Admin).filter(Admin.email == email, Admin.aktiv == True).first()
    if a:
        token = secrets.token_urlsafe(32)
        a.reset_token = token
        a.reset_token_expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.commit()
        from email_service import send_admin_reset
        send_admin_reset(a, token, str(request.base_url).rstrip("/"))
    # Immer gleiche Antwort – keine Auskunft, ob die Adresse existiert
    return RedirectResponse("/admin/forgot?sent=1", status_code=303)

@router.get("/reset/{token}", response_class=HTMLResponse)
def reset_page(request: Request, token: str, db: Session = Depends(get_db)):
    a = db.query(Admin).filter(Admin.reset_token == token).first()
    gueltig = bool(a and a.reset_token_expires and
                   datetime.utcnow() <= datetime.fromisoformat(a.reset_token_expires))
    return templates.TemplateResponse("admin/reset.html",
        tpl_context(request, token=token, gueltig=gueltig))

@router.post("/reset/{token}")
def reset_post(request: Request, token: str, password: str = Form(...),
               db: Session = Depends(get_db)):
    a = db.query(Admin).filter(Admin.reset_token == token).first()
    if not a or not a.reset_token_expires or datetime.utcnow() > datetime.fromisoformat(a.reset_token_expires):
        return templates.TemplateResponse("admin/reset.html",
            tpl_context(request, token=token, gueltig=False))
    a.password_hash = hash_password(password)
    a.reset_token = None
    a.reset_token_expires = None
    db.commit()
    return RedirectResponse("/admin/login?reset=ok", status_code=303)


# ── Admin-Zugänge verwalten ──────────────────────────────────────────────────

@router.get("/admins", response_class=HTMLResponse)
def admins_list(request: Request, db: Session = Depends(get_db), user=Depends(get_admin_user)):
    admins = db.query(Admin).order_by(Admin.email).all()
    return templates.TemplateResponse("admin/admins.html",
        tpl_context(request, admins=admins, me=user.get("sub")))

@router.post("/admins/new")
def admins_create(request: Request, db: Session = Depends(get_db), user=Depends(get_admin_user),
                  email: str = Form(...), name: str = Form(""), password: str = Form(...)):
    email = email.strip().lower()
    if db.query(Admin).filter(Admin.email == email).first():
        return RedirectResponse("/admin/admins?fehler=vorhanden", status_code=303)
    db.add(Admin(email=email, name=name.strip() or None,
                 password_hash=hash_password(password), aktiv=True,
                 erstellt_am=datetime.now().isoformat(timespec="seconds")))
    db.commit()
    return RedirectResponse("/admin/admins?ok=angelegt", status_code=303)

@router.post("/admins/{aid}/delete")
def admins_delete(aid: int, db: Session = Depends(get_db), user=Depends(get_admin_user)):
    a = db.query(Admin).filter(Admin.id == aid).first()
    if not a:
        return RedirectResponse("/admin/admins", status_code=303)
    # Schutz: nicht sich selbst, nicht den letzten Admin löschen
    if a.email == user.get("sub") or db.query(Admin).count() <= 1:
        return RedirectResponse("/admin/admins?fehler=geschuetzt", status_code=303)
    db.delete(a); db.commit()
    return RedirectResponse("/admin/admins?ok=geloescht", status_code=303)


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
def event_new(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=None, produkte_list=PRODUKTE_LIST, anlass_list=ANLASS_LIST,
                    kunden=kunden, error=None))

@router.post("/events/new")
def event_create(
    request: Request, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(...),
    veranstaltungsort: str = Form(...),
    kunde_firma: str = Form(...), kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    marke: str = Form("Kindsalabim"), crm_verknuepfen: bool = Form(False),
):
    try:
        datum_d = date.fromisoformat(datum)
    except ValueError:
        kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=None, produkte_list=PRODUKTE_LIST, kunden=kunden,
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
    db.add(ev)
    if crm_verknuepfen:
        link_kunde(db, ev, kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, marke)
    db.commit(); db.refresh(ev)
    import calendar_service
    background_tasks.add_task(calendar_service.sync_event_async, ev.id)
    return RedirectResponse(f"/admin/events/{ev.id}", status_code=303)

@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404)
    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == event_id).all()

    anfragen_ids = {a.dienstleister_id: a for a in anfragen}

    active = db.query(Dienstleister).filter(Dienstleister.aktiv == True).all()

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

    # Sperrzeiten-Konflikte: welche Dienstleister haben am Event-Datum eine Sperrzeit?
    sperrzeit_map = {}
    if ev.datum:
        sperrzeiten = db.query(DienstleisterSperrzeit).filter(
            DienstleisterSperrzeit.von_datum <= ev.datum,
            DienstleisterSperrzeit.bis_datum >= ev.datum,
        ).all()
        for sz in sperrzeiten:
            sperrzeit_map[sz.dienstleister_id] = sz

    # Empfehlungs-Ranking: nicht verfügbare (gebucht/Sperrzeit) ans Ende
    unavailable_ids = set(gebucht_map) | set(sperrzeit_map)
    needs_material = bool(ev.material_mitnahme)
    ranked_teamer = rank_contractors([d for d in active if d.rolle in ("Teamer", "Beides")],
                                     ev.veranstaltungsort, needs_material, unavailable_ids)
    ranked_kuenstler = rank_contractors([d for d in active if d.rolle in ("Künstler", "Beides")],
                                        ev.veranstaltungsort, needs_material, unavailable_ids)

    # "Länger nicht angefragt": letzte Anfrage je Dienstleister älter als 6 Monate
    grenze = date.today() - timedelta(days=180)
    letzte = db.query(Verfuegbarkeitsanfrage.dienstleister_id, func.max(Event.datum)).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).group_by(
        Verfuegbarkeitsanfrage.dienstleister_id).all()
    lange_her_ids = {did for did, last in letzte if last and last < grenze}

    # Kartendaten (Leaflet/OpenStreetMap)
    event_coords = get_coords_for_address(ev.veranstaltungsort)
    karte_dienstleister = []
    for d in active:
        c = get_coords_for_plz(d.plz or "")
        if c:
            karte_dienstleister.append({
                "name": f"{d.vorname} {d.nachname}", "lat": c[0], "lon": c[1],
                "rolle": d.rolle, "logistiker": bool(d.logistiker), "stadt": d.stadt or "",
                "distanz": round(getattr(d, "rang_distanz_km", None)) if getattr(d, "rang_distanz_km", None) is not None else None,
            })
    karte_data = {
        "event": list(event_coords) if event_coords else None,
        "ort": ev.veranstaltungsort or "",
        "dienstleister": karte_dienstleister,
    }

    planungsdateien = db.query(EventDatei).filter(
        EventDatei.event_id == event_id,
        EventDatei.typ == "planung"
    ).order_by(EventDatei.uploaded_at).all()
    planungs_urls = [(d, generate_presigned_url(d.r2_key)) for d in planungsdateien]

    ab_dateien = db.query(EventDatei).filter(
        EventDatei.event_id == event_id,
        EventDatei.typ == "auftragsbestaetigung"
    ).order_by(EventDatei.uploaded_at).all()
    ab_urls = [(d, generate_presigned_url(d.r2_key)) for d in ab_dateien]

    # Logistiker-Warnung: Material-Mitnahme nötig, aber kein Logistiker zugesagt
    logistiker_zugesagt = any(
        a.dienstleister.logistiker for a in anfragen
        if a.status == "Ja" and a.dienstleister)
    logistiker_warnung = bool(ev.material_mitnahme and not logistiker_zugesagt)

    return templates.TemplateResponse("admin/event_detail.html",
        tpl_context(request, ev=ev, anfragen=anfragen, anfragen_ids=anfragen_ids,
                    ranked_teamer=ranked_teamer, ranked_kuenstler=ranked_kuenstler,
                    gebucht_map=gebucht_map, planungs_urls=planungs_urls,
                    ab_urls=ab_urls, logistiker_warnung=logistiker_warnung,
                    sperrzeit_map=sperrzeit_map, lange_her_ids=lange_her_ids,
                    karte_data=karte_data, needs_material=needs_material))

@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
def event_edit(request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=ev, produkte_list=PRODUKTE_LIST, kunden=kunden,
                    anlass_list=ANLASS_LIST, error=None))

@router.post("/events/{event_id}/edit")
def event_update(
    request: Request, event_id: int, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(...),
    veranstaltungsort: str = Form(...),
    kunde_firma: str = Form(...), kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    status: str = Form("Entwurf"),
    marke: str = Form("Kindsalabim"), crm_verknuepfen: bool = Form(False),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    try:
        ev.datum = date.fromisoformat(datum)
    except ValueError:
        kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=ev, produkte_list=PRODUKTE_LIST, kunden=kunden,
                        anlass_list=ANLASS_LIST, error="Bitte ein gültiges Datum wählen."))
    ev.anlass = anlass; ev.startzeit = startzeit
    ev.endzeit = endzeit; ev.veranstaltungsort = veranstaltungsort
    ev.kunde_firma = kunde_firma; ev.kunde_kontakt = kunde_kontakt
    ev.kunde_telefon = kunde_telefon; ev.kunde_email = kunde_email
    ev.produkte = ", ".join(produkte); ev.anzahl_teamer = anzahl_teamer
    ev.anzahl_kuenstler = anzahl_kuenstler; ev.hinweise = hinweise
    ev.material_mitnahme = material_mitnahme; ev.marke = marke; ev.status = status
    if crm_verknuepfen:
        link_kunde(db, ev, kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, marke)
    db.commit()
    import calendar_service
    background_tasks.add_task(calendar_service.sync_event_async, event_id)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/delete")
def event_delete(event_id: int, background_tasks: BackgroundTasks,
                 db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if ev:
        import calendar_service
        background_tasks.add_task(calendar_service.delete_event_async, ev.kalender_event_id, ev.marke)
        db.delete(ev); db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


@router.get("/calendar-test")
def calendar_test(_=Depends(get_admin_user)):
    """Diagnose des Google-Kalender-Sync: zeigt, ob Credentials lesbar sind und
    ob der Zugriff auf den Kindsalabim-Kalender funktioniert."""
    import calendar_service as cs
    cfg = get_config()
    out = {
        "credentials_gesetzt": bool(cfg.get("google_calendar_credentials")),
        "kalender_kindsalabim": cfg.get("calendar_id_kindsalabim"),
        "kalender_knallfrosch": cfg.get("calendar_id_knallfrosch"),
    }
    try:
        svc = cs._service()
        out["service_gebaut"] = bool(svc)
        if svc:
            cid = cfg.get("calendar_id_kindsalabim")
            r = svc.events().list(calendarId=cid, maxResults=1).execute()
            out["kalender_zugriff"] = "ok"
            out["kalender_name"] = r.get("summary")
    except Exception as e:
        out["fehler"] = f"{type(e).__name__}: {e}"
    return JSONResponse(out)


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

    # Logistiker: nur nötig, wenn Material transportiert werden muss
    logistiker_ok = (not ev.material_mitnahme) or any(
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

@router.get("/dienstleister/export.csv")
def dienstleister_export(db: Session = Depends(get_db), _=Depends(get_admin_user)):
    import io, csv
    from fastapi.responses import StreamingResponse
    alle = db.query(Dienstleister).order_by(Dienstleister.nachname).all()
    out = io.StringIO()
    out.write("sep=;\n")  # Excel-Hint
    w = csv.writer(out, delimiter=";")
    w.writerow([
        "Vorname", "Nachname", "E-Mail", "Telefon", "Straße", "PLZ", "Stadt",
        "Rolle", "Erfahrungspunkte", "Mobilität", "Kleidergröße", "Gebiet",
        "Verfügbarkeit", "Vertragstyp", "Stundensatz Teamer", "Stundensatz Künstler",
        "DSGVO", "Logistiker", "Führerschein", "Website", "Aktiv", "Notizen",
    ])
    for d in alle:
        def euro(v):
            return f"{v:.2f}".replace(".", ",") if v else ""
        w.writerow([
            d.vorname or "", d.nachname or "", d.email or "", d.telefon or "",
            d.strasse or "", d.plz or "", d.stadt or "", d.rolle or "",
            d.erfahrungspunkte or 0, d.mobilitaet or "", d.kleidergroesse or "",
            d.gebiet or "", d.verfuegbarkeit or "", d.vertragstyp or "",
            euro(d.stundensatz_teamer), euro(d.stundensatz_kuenstler),
            "ja" if d.dsgvo_unterzeichnet else "nein",
            "ja" if d.logistiker else "nein",
            "ja" if d.fuehrerschein else "nein",
            d.website or "", "ja" if d.aktiv else "nein", d.notizen or "",
        ])
    content = "﻿" + out.getvalue()
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dienstleister.csv"},
    )

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
    qualitaet: str = Form(""),
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

    def _qual(s):
        return int(s) if s.strip() in ("1", "2", "3", "4", "5") else None

    d = Dienstleister(
        vorname=vorname, nachname=nachname, email=email, telefon=telefon,
        strasse=strasse, plz=plz, stadt=stadt, rolle=rolle,
        erfahrungspunkte=erfahrungspunkte, qualitaet=_qual(qualitaet),
        mobilitaet=mobilitaet,
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

@router.get("/dienstleister/{did}", response_class=HTMLResponse)
def dienstleister_detail(request: Request, did: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)
    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did
    ).all()
    anfragen = sorted(anfragen, key=lambda a: a.event.datum or date.min, reverse=True)
    return templates.TemplateResponse("admin/contractor_detail.html",
        tpl_context(request, d=d, anfragen=anfragen))

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
    qualitaet: str = Form(""),
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
    d.qualitaet = int(qualitaet) if qualitaet.strip() in ("1", "2", "3", "4", "5") else None
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
    if d:
        # Verknüpfte Daten zuerst lösen, sonst blockiert der Fremdschlüssel die Löschung
        db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.dienstleister_id == did).delete(synchronize_session=False)
        db.query(DienstleisterSperrzeit).filter(
            DienstleisterSperrzeit.dienstleister_id == did).delete(synchronize_session=False)
        # Teamleiter-Verknüpfung an Events lösen (FK ohne Cascade)
        db.query(Event).filter(Event.teamleiter_id == did).update(
            {Event.teamleiter_id: None}, synchronize_session=False)
        db.delete(d)
        db.commit()
    return RedirectResponse("/admin/dienstleister?geloescht=1", status_code=303)
