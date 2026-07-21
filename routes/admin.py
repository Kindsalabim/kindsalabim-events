from fastapi import APIRouter, Request, Depends, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date, timedelta
import calendar as _calendar
from typing import Optional

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

from sqlalchemy import func
from database import get_db, SessionLocal
from models import Event, Dienstleister, Verfuegbarkeitsanfrage, EventDatei, Admin, Kunde, DienstleisterSperrzeit, Reservierung, ExternerTeamer
import secrets
from routes.fotos import generate_presigned_url, download_file
from auth import get_admin_user, verify_password, hash_password, create_token, COOKIE_SECURE
from config import get_config
from distance import rank_contractors, get_coords_for_address, get_coords_for_dienstleister
from email_service import send_verfuegbarkeitsanfrage, send_briefing, send_serie_anfrage, ANFRAGE_FRIST_TAGE
from choices import ZEITEN, de_date, de_month, de_euro
from validation import validate_event_form, validate_dienstleister_form

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_month"] = de_month
templates.env.filters["de_euro"] = de_euro
templates.env.globals["zeiten"] = ZEITEN
import ankunft as _ankunft
templates.env.globals["ankunft_anzeige"] = _ankunft.ankunft_anzeige
templates.env.globals["treffpunkt_anzeige"] = _ankunft.treffpunkt_anzeige

PRODUKTE_LIST = [
    "Bunter Bastelspaß", "Bastelaktion", "Glitzertattoos",
    "Fotoaktion", "Spieleland", "Mitmachzirkus", "Mini Mitmachzirkus", "Knusperhäuschen", "Lebkuchenherzen",
    "Ballonmodellage", "Kinderschminken", "Buttonmaschine", "Prickeln",
    "Bastelspaß Weihnachten", "Kleinkind Spieleland", "Walkact", "Hüpfburg",
    "Zaubershow", "Zauberworkshop", "Zaubershow + Ballonmodellage", "Kein Material"
]

ANLASS_LIST = [
    "Weihnachtsfeier", "Adventsfeier", "Osteraktion", "Sommerfest",
    "Konferenz / Tagung", "Messe", "Firmenjubiläum", "Hochzeit",
    "Kindergeburtstag", "Kids-Day", "Neueröffnung", "Promotion", "Sonstige"
]

def tpl_context(request: Request, **kwargs):
    cfg = get_config()
    return {"request": request, "cfg": cfg, **kwargs}


# Endzustände: gegen versehentliche Änderungen gesperrt (Bug 7); per ?entsperrt=1 temporär aufhebbar
GESPERRTE_STATUS = ("Abgeschlossen", "Abgesagt")


def event_gesperrt(ev, entsperrt: bool = False) -> bool:
    return ev.status in GESPERRTE_STATUS and not entsperrt


def vorschlag_ersatz(ev, db, rolle=None):
    """Bester freier Ersatz-Dienstleister für eine Lücke (für Nachbesetzungs-Hinweise).
    Berücksichtigt das Entfernungs-/Qualitäts-Ranking und schließt bereits Angefragte sowie
    am Eventtag Gebuchte/Gesperrte aus. rolle=None → die Rolle mit der größten Lücke
    (Teamer/Künstler). Gibt den Dienstleister (mit `rang_distanz_km`) oder None zurück."""
    if not ev or not ev.datum:
        return None
    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id).all()
    anfragen_ids = {a.dienstleister_id for a in anfragen}
    confirmed = [a for a in anfragen if a.status == "Ja"]
    conf_teamer = sum(1 for a in confirmed if a.rolle_anfrage == "Teamer") + len(ev.externe_teamer or [])
    conf_kuenstler = sum(1 for a in confirmed if a.rolle_anfrage == "Künstler")
    fehlend = {"Teamer":   max(0, (ev.anzahl_teamer or 0) - conf_teamer),
               "Künstler": max(0, (ev.anzahl_kuenstler or 0) - conf_kuenstler)}
    if rolle is None:
        rolle = max(fehlend, key=lambda r: fehlend[r])
    if fehlend.get(rolle, 0) <= 0:
        return None

    # Am Eventtag nicht verfügbar (anderweitig gebucht oder Sperrzeit/Urlaub)
    gebucht = db.query(Verfuegbarkeitsanfrage).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).filter(
        Verfuegbarkeitsanfrage.status == "Ja",
        Verfuegbarkeitsanfrage.event_id != ev.id,
        Event.datum == ev.datum).all()
    unavailable = {a.dienstleister_id for a in gebucht}
    sperr = db.query(DienstleisterSperrzeit).filter(
        DienstleisterSperrzeit.von_datum <= ev.datum,
        DienstleisterSperrzeit.bis_datum >= ev.datum).all()
    unavailable |= {s.dienstleister_id for s in sperr}

    rollen = ("Teamer", "Beides") if rolle == "Teamer" else ("Künstler", "Beides")
    active = db.query(Dienstleister).filter(
        Dienstleister.aktiv == True, Dienstleister.rolle.in_(rollen)).all()  # noqa: E712
    ranked = rank_contractors(active, ev.veranstaltungsort, bool(ev.material_mitnahme), unavailable)
    for d in ranked:
        if d.id not in anfragen_ids and d.id not in unavailable:
            return d
    return None


def ersatz_label(d) -> str:
    """Kurzes Label für einen Ersatz-Vorschlag, z. B. 'Max Muster (Essen · 8 km)'."""
    extra = []
    if getattr(d, "stadt", None):
        extra.append(d.stadt)
    km = getattr(d, "rang_distanz_km", None)
    if km is not None and km < 9000:   # 9999 = nicht verortbar → keine Distanz zeigen
        extra.append(f"{round(km)} km")
    name = f"{d.vorname} {d.nachname}"
    return name + (f" ({' · '.join(extra)})" if extra else "")


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


# ── Termin-Serie (mehrtägige Events) ─────────────────────────────────────────────

def _parse_extra_tage(extra_datum, extra_startzeit, extra_endzeit, base_start, base_end):
    """Parst weitere Termintage aus dem Formular (parallele Listen). Leere Datumszeilen
    werden übersprungen; fehlende Zeiten erben die Zeiten des Haupttags.
    Rückgabe: (liste[(date, startzeit, endzeit)], fehler_oder_None)."""
    tage = []
    for i, ds in enumerate(extra_datum or []):
        ds = (ds or "").strip()
        if not ds:
            continue
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            return [], "Ein zusätzlicher Termin hat ein ungültiges Datum."
        sz = (extra_startzeit[i] if i < len(extra_startzeit) else "") or base_start
        ez = (extra_endzeit[i] if i < len(extra_endzeit) else "") or base_end
        if sz and ez and ez <= sz:
            return [], f"Beim Zusatztermin am {d.strftime('%d.%m.%Y')} muss die Endzeit nach der Startzeit liegen."
        tage.append((d, sz, ez))
    return tage, None


def _neues_geschwister_event(base_ev, datum, startzeit, endzeit, serien_id, status=None):
    """Kopiert die Stammdaten eines Events auf einen weiteren Termintag (neue Event-Zeile).
    status=None erbt den Status des Basis-Events (Anlegen mehrtägiger Events, alle Tage
    starten gleich); ein nachträglich hinzugefügter Tag bekommt explizit „Gebucht"."""
    return Event(
        anlass=base_ev.anlass, datum=datum, startzeit=startzeit, endzeit=endzeit,
        veranstaltungsort=base_ev.veranstaltungsort, kunde_firma=base_ev.kunde_firma,
        kunde_adresse=base_ev.kunde_adresse,
        kunde_kontakt=base_ev.kunde_kontakt, kunde_telefon=base_ev.kunde_telefon,
        kunde_email=base_ev.kunde_email,
        vor_ort_name=base_ev.vor_ort_name, vor_ort_telefon=base_ev.vor_ort_telefon,
        produkte=base_ev.produkte,
        anzahl_teamer=base_ev.anzahl_teamer, anzahl_kuenstler=base_ev.anzahl_kuenstler,
        hinweise=base_ev.hinweise, material_mitnahme=base_ev.material_mitnahme,
        marke=base_ev.marke, status=status or base_ev.status, kunde_id=base_ev.kunde_id,
        serien_id=serien_id,
    )


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
    # 30 Tage Login (internes Single-User-Tool) – Token-Laufzeit und Cookie gleich lang
    token = create_token({"sub": a.email, "role": "admin"}, expires_minutes=60*24*30)
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie("admin_token", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60*60*24*30)
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
    if len(password) < 8:
        return templates.TemplateResponse("admin/reset.html",
            tpl_context(request, token=token, gueltig=True,
                        pw_fehler="Das Passwort muss mindestens 8 Zeichen lang sein."))
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
    if len(password) < 8:
        return RedirectResponse("/admin/admins?fehler=pw_kurz", status_code=303)
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

    # Termin-Serien: Anzahl Tage je serien_id (für die "Serie"-Markierung in der Liste)
    serien_count = {}
    for e in events:
        if e.serien_id:
            serien_count[e.serien_id] = serien_count.get(e.serien_id, 0) + 1

    def event_date(e):
        return e.datum or date.max

    # Abgesagte Events fliegen aus der Übersicht (bleiben aber als flamingo-Eintrag im Kalender)
    upcoming = sorted([e for e in events if e.status not in ("Abgeschlossen", "Abgesagt")], key=event_date)
    past     = sorted([e for e in events if e.status == "Abgeschlossen"], key=event_date, reverse=True)

    # Zusagen ("Ja") je Event/Rolle und externe Teamer je Event – je EINE Aggregat-Query
    # statt einer Query pro Event (früheres N+1 im Dashboard).
    ja_map = {}
    for eid, rolle, cnt in db.query(
            Verfuegbarkeitsanfrage.event_id, Verfuegbarkeitsanfrage.rolle_anfrage, func.count()).filter(
            Verfuegbarkeitsanfrage.status == "Ja").group_by(
            Verfuegbarkeitsanfrage.event_id, Verfuegbarkeitsanfrage.rolle_anfrage).all():
        ja_map.setdefault(eid, {})[rolle] = cnt
    ext_map = {}
    for eid, cnt in db.query(ExternerTeamer.event_id, func.count()).group_by(
            ExternerTeamer.event_id).all():
        ext_map[eid] = cnt

    def fehlende_dl(ev):
        """Gibt (fehlende_teamer, fehlende_kuenstler) zurück – aus den Aggregat-Maps."""
        ja = ja_map.get(ev.id, {})
        teamer    = ja.get("Teamer", 0) + ext_map.get(ev.id, 0)
        kuenstler = ja.get("Künstler", 0)
        return (max(0, (ev.anzahl_teamer or 0) - teamer),
                max(0, (ev.anzahl_kuenstler or 0) - kuenstler))

    # Offene Dienstleister-Rückmeldungen je Event (eine Query)
    pending_map = {}
    for eid, cnt in db.query(Verfuegbarkeitsanfrage.event_id, func.count()).filter(
            Verfuegbarkeitsanfrage.status == "Ausstehend").group_by(
            Verfuegbarkeitsanfrage.event_id).all():
        pending_map[eid] = cnt

    upcoming_data = []
    offene_rueckmeldungen = 0
    offene_checklisten = 0
    for ev in upcoming:
        ft, fk = fehlende_dl(ev)
        days_until = (event_date(ev) - today).days
        pending = pending_map.get(ev.id, 0)
        checkliste_offen = bool(ev.checklist_token and not ev.cl_eingereicht_am)
        urgent = 0 <= days_until <= 14
        offene_rueckmeldungen += pending
        if checkliste_offen:
            offene_checklisten += 1
        upcoming_data.append({"ev": ev, "fehlende_teamer": ft, "fehlende_kuenstler": fk,
                              "days_until": days_until, "pending": pending,
                              "checkliste_offen": checkliste_offen, "urgent": urgent})

    # Vergangene, aber noch nicht abgeschlossene Events aus der Hauptliste ausgruppieren
    # (sie machen sie sonst unübersichtlich) → eigene eingeklappte Gruppe oben im Dashboard.
    ueberfaellig_data = [d for d in upcoming_data if d["days_until"] < 0]
    upcoming_data     = [d for d in upcoming_data if d["days_until"] >= 0]

    reservierungen_count = db.query(Reservierung).count()
    dringend_count = sum(1 for d in upcoming_data if d["urgent"])

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
        if e.status == "Abgesagt":
            continue  # abgesagte Events nicht im Dashboard-Kalender markieren
        if e.datum and e.datum.year == cur.year and e.datum.month == cur.month:
            event_map.setdefault(e.datum.day, []).append(e)

    # Ausgewählter Tag (?day=JJJJ-MM-TT) -> Events an diesem Tag
    sel_day, sel_events = None, []
    if day:
        try:
            sel_day = date.fromisoformat(day)
            sel_events = sorted([e for e in events if e.datum == sel_day and e.status != "Abgesagt"],
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
                    ueberfaellig_data=ueberfaellig_data,
                    past=past, kalender=kalender,
                    reservierungen_count=reservierungen_count,
                    offene_rueckmeldungen=offene_rueckmeldungen,
                    offene_checklisten=offene_checklisten,
                    dringend_count=dringend_count, serien_count=serien_count))


# ── Reservierungen (unverbindliche Holds vor der Buchung) ───────────────────────

@router.get("/reservierungen", response_class=HTMLResponse)
def reservierungen_list(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    res = db.query(Reservierung).order_by(Reservierung.datum, Reservierung.frist.is_(None), Reservierung.frist).all()
    return templates.TemplateResponse("admin/reservierungen.html",
        tpl_context(request, reservierungen=res, today=date.today()))

@router.post("/reservierungen/new")
def reservierung_create(
    request: Request, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    datum: str = Form(...), kunde_firma: str = Form(...),
    startzeit: str = Form(""), endzeit: str = Form(""), art: str = Form("Div."),
    anlass: str = Form(""), veranstaltungsort: str = Form(""),
    kunde_kontakt: str = Form(""), kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    marke: str = Form("Kindsalabim"), frist: str = Form(""), notiz: str = Form(""),
):
    try:
        datum_d = date.fromisoformat(datum)
    except ValueError:
        return RedirectResponse("/admin/reservierungen?error=datum", status_code=303)
    frist_d = None
    if frist.strip():
        try: frist_d = date.fromisoformat(frist)
        except ValueError: frist_d = None
    if frist_d is None:
        frist_d = datum_d  # Fallback; wird sonst über das Formular gesetzt
    r = Reservierung(
        datum=datum_d, kunde_firma=kunde_firma, anlass=anlass.strip() or None,
        startzeit=startzeit.strip() or None, endzeit=endzeit.strip() or None, art=art.strip() or "Div.",
        veranstaltungsort=veranstaltungsort.strip() or None,
        kunde_kontakt=kunde_kontakt.strip() or None, kunde_telefon=kunde_telefon.strip() or None,
        kunde_email=kunde_email.strip() or None, marke=marke,
        frist=frist_d, notiz=notiz.strip() or None,
        erstellt_am=datetime.now().isoformat(timespec="seconds"),
    )
    db.add(r); db.commit(); db.refresh(r)
    import calendar_service
    background_tasks.add_task(calendar_service.sync_reservierung_async, r.id)
    return RedirectResponse("/admin/reservierungen", status_code=303)

@router.get("/reservierungen/{res_id}/edit", response_class=HTMLResponse)
def reservierung_edit_form(res_id: int, request: Request,
                           db: Session = Depends(get_db), _=Depends(get_admin_user)):
    r = db.query(Reservierung).filter(Reservierung.id == res_id).first()
    if not r:
        return RedirectResponse("/admin/reservierungen", status_code=303)
    return templates.TemplateResponse("admin/reservierung_edit.html",
        tpl_context(request, r=r))

@router.post("/reservierungen/{res_id}/edit")
def reservierung_edit_save(
    res_id: int, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    datum: str = Form(...), kunde_firma: str = Form(...),
    startzeit: str = Form(""), endzeit: str = Form(""), art: str = Form("Div."),
    anlass: str = Form(""), veranstaltungsort: str = Form(""),
    kunde_kontakt: str = Form(""), kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    marke: str = Form("Kindsalabim"), frist: str = Form(""), notiz: str = Form(""),
):
    r = db.query(Reservierung).filter(Reservierung.id == res_id).first()
    if not r:
        return RedirectResponse("/admin/reservierungen", status_code=303)
    try:
        r.datum = date.fromisoformat(datum)
    except ValueError:
        return RedirectResponse(f"/admin/reservierungen/{res_id}/edit?error=datum", status_code=303)
    frist_d = None
    if frist.strip():
        try: frist_d = date.fromisoformat(frist)
        except ValueError: frist_d = None
    r.frist = frist_d or r.datum
    r.kunde_firma = kunde_firma
    r.startzeit = startzeit.strip() or None
    r.endzeit = endzeit.strip() or None
    r.art = art.strip() or "Div."
    r.anlass = anlass.strip() or None
    r.veranstaltungsort = veranstaltungsort.strip() or None
    r.kunde_kontakt = kunde_kontakt.strip() or None
    r.kunde_telefon = kunde_telefon.strip() or None
    r.kunde_email = kunde_email.strip() or None
    r.marke = marke
    r.notiz = notiz.strip() or None
    db.commit()
    import calendar_service
    background_tasks.add_task(calendar_service.sync_reservierung_async, r.id)
    return RedirectResponse("/admin/reservierungen", status_code=303)

@router.post("/reservierungen/{res_id}/freigeben")
def reservierung_freigeben(res_id: int, background_tasks: BackgroundTasks,
                           db: Session = Depends(get_db), _=Depends(get_admin_user)):
    r = db.query(Reservierung).filter(Reservierung.id == res_id).first()
    if r:
        import calendar_service
        if r.kalender_event_id:
            background_tasks.add_task(calendar_service.delete_event_async, r.kalender_event_id, r.marke)
        db.delete(r); db.commit()
    return RedirectResponse("/admin/reservierungen", status_code=303)

@router.post("/reservierungen/{res_id}/umwandeln")
def reservierung_umwandeln(res_id: int, background_tasks: BackgroundTasks,
                           db: Session = Depends(get_db), _=Depends(get_admin_user)):
    r = db.query(Reservierung).filter(Reservierung.id == res_id).first()
    if not r:
        return RedirectResponse("/admin/reservierungen", status_code=303)
    ev = Event(
        anlass=r.anlass or "—", datum=r.datum,
        startzeit=r.startzeit or "10:00", endzeit=r.endzeit or "16:00",
        veranstaltungsort=r.veranstaltungsort or "—", kunde_firma=r.kunde_firma,
        kunde_kontakt=r.kunde_kontakt, kunde_telefon=r.kunde_telefon, kunde_email=r.kunde_email,
        marke=r.marke, status="Gebucht",
    )
    db.add(ev)
    import calendar_service
    if r.kalender_event_id:
        background_tasks.add_task(calendar_service.delete_event_async, r.kalender_event_id, r.marke)
    db.delete(r); db.commit(); db.refresh(ev)
    background_tasks.add_task(calendar_service.sync_event_async, ev.id)
    # Zum Bearbeiten öffnen – Uhrzeiten/Details vervollständigen
    return RedirectResponse(f"/admin/events/{ev.id}/edit", status_code=303)


# ── Events ─────────────────────────────────────────────────────────────────────

@router.get("/events/new", response_class=HTMLResponse)
def event_new(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=None, produkte_list=PRODUKTE_LIST, anlass_list=ANLASS_LIST,
                    kunden=kunden, error=None))

def _event_form_echo(datum_d, datum, anlass, startzeit, endzeit, veranstaltungsort,
                     kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, produkte,
                     anzahl_teamer, anzahl_kuenstler, hinweise, material_mitnahme,
                     marke, status, event_id=None, serien_id=None,
                     checkliste_uebersprungen=False, zaubershow_event=False,
                     material_info="", transporter_angeboten=False,
                     ankunft_modus="auto", ankunft_text="", treffpunkt="",
                     kunde_adresse="", vor_ort_name="", vor_ort_telefon=""):
    """Baut ein leichtes Objekt mit den eingegebenen Werten, damit das Formular bei
    einem Validierungsfehler die Eingaben behält (statt sie zu verlieren)."""
    from types import SimpleNamespace
    d = datum_d
    if d is None:
        try:
            d = date.fromisoformat(datum)
        except (ValueError, TypeError):
            d = None
    return SimpleNamespace(
        id=event_id, serien_id=serien_id, anlass=anlass, datum=d,
        startzeit=startzeit, endzeit=endzeit, veranstaltungsort=veranstaltungsort,
        kunde_firma=kunde_firma, kunde_adresse=kunde_adresse, kunde_kontakt=kunde_kontakt,
        kunde_telefon=kunde_telefon, kunde_email=kunde_email,
        vor_ort_name=vor_ort_name, vor_ort_telefon=vor_ort_telefon,
        produkte=", ".join(produkte), anzahl_teamer=anzahl_teamer,
        anzahl_kuenstler=anzahl_kuenstler, hinweise=hinweise,
        material_mitnahme=material_mitnahme, marke=marke, status=status,
        checkliste_uebersprungen=checkliste_uebersprungen,
        zaubershow_event=zaubershow_event,
        material_info=material_info, transporter_angeboten=transporter_angeboten,
        ankunft_modus=ankunft_modus, ankunft_text=ankunft_text, treffpunkt=treffpunkt,
    )


@router.post("/events/new")
def event_create(
    request: Request, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(""),
    veranstaltungsort: str = Form(""), ort_abweichend: bool = Form(False),
    kunde_firma: str = Form(""), kunde_adresse: str = Form(""),
    kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    vor_ort_name: str = Form(""), vor_ort_telefon: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    material_info_choice: str = Form(""), material_info_text: str = Form(""),
    transporter_angeboten: bool = Form(False),
    ankunft_modus: str = Form("auto"), ankunft_text: str = Form(""), treffpunkt: str = Form(""),
    checkliste_uebersprungen: bool = Form(False), zaubershow_event: bool = Form(False),
    status: str = Form("Gebucht"),
    marke: str = Form("Kindsalabim"), crm_verknuepfen: bool = Form(False),
    extra_datum: list = Form([]), extra_startzeit: list = Form([]),
    extra_endzeit: list = Form([]),
):
    material_info = material_info_text.strip() if material_info_choice == "Sonstige" else material_info_choice
    # Veranstaltungsort = Firmenadresse, außer der Admin hat „andere Adresse" gewählt
    if not ort_abweichend:
        veranstaltungsort = (kunde_adresse or "").strip()
    datum_d, fehler = validate_event_form(datum, startzeit, endzeit, kunde_telefon, veranstaltungsort, produkte, zaubershow=zaubershow_event, abgesagt=(status == "Abgesagt"))
    extra_tage, extra_fehler = _parse_extra_tage(extra_datum, extra_startzeit, extra_endzeit, startzeit, endzeit)
    fehler = fehler or extra_fehler
    if fehler:
        kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
        echo = _event_form_echo(datum_d, datum, anlass, startzeit, endzeit, veranstaltungsort,
                                kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, produkte,
                                anzahl_teamer, anzahl_kuenstler, hinweise, material_mitnahme,
                                marke, status, checkliste_uebersprungen=checkliste_uebersprungen,
                                zaubershow_event=zaubershow_event,
                                material_info=material_info, transporter_angeboten=transporter_angeboten,
                                ankunft_modus=ankunft_modus, ankunft_text=ankunft_text, treffpunkt=treffpunkt,
                                kunde_adresse=kunde_adresse, vor_ort_name=vor_ort_name,
                                vor_ort_telefon=vor_ort_telefon)
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=echo, produkte_list=PRODUKTE_LIST, kunden=kunden,
                        anlass_list=ANLASS_LIST, error=fehler))
    ev = Event(
        anlass=anlass, datum=datum_d, startzeit=startzeit, endzeit=endzeit,
        veranstaltungsort=veranstaltungsort, kunde_firma=kunde_firma,
        kunde_adresse=kunde_adresse.strip() or None,
        kunde_kontakt=kunde_kontakt, kunde_telefon=kunde_telefon,
        kunde_email=kunde_email,
        vor_ort_name=vor_ort_name.strip() or None, vor_ort_telefon=vor_ort_telefon.strip() or None,
        produkte=", ".join(produkte),
        anzahl_teamer=anzahl_teamer, anzahl_kuenstler=anzahl_kuenstler,
        hinweise=hinweise, material_mitnahme=material_mitnahme,
        material_info=material_info, transporter_angeboten=transporter_angeboten,
        ankunft_modus=ankunft_modus, ankunft_text=ankunft_text.strip() or None,
        treffpunkt=treffpunkt.strip() or None,
        checkliste_uebersprungen=checkliste_uebersprungen,
        zaubershow_event=zaubershow_event,
        marke=marke, status=status
    )
    db.add(ev)
    if crm_verknuepfen:
        link_kunde(db, ev, kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, marke)
    db.commit(); db.refresh(ev)
    # Mehrtägiges Event: weitere Termintage als verknüpfte Geschwister-Events anlegen
    geschwister = []
    if extra_tage:
        ev.serien_id = secrets.token_hex(8)
        for (d, sz, ez) in extra_tage:
            sib = _neues_geschwister_event(ev, d, sz, ez, ev.serien_id)
            db.add(sib); geschwister.append(sib)
        db.commit()
    import calendar_service
    background_tasks.add_task(calendar_service.sync_event_async, ev.id)
    for sib in geschwister:
        background_tasks.add_task(calendar_service.sync_event_async, sib.id)
    return RedirectResponse(f"/admin/events/{ev.id}", status_code=303)

def _workflow_steps(ev, anfragen):
    """Berechnet die 5 Workflow-Stufen samt Status für die Chevron-Leiste im Event-Detail.
    state: 'done' (grün/erledigt) · 'doing' (in Arbeit, grau) · 'todo' (offen, grau) · 'na' (nicht nötig)."""
    confirmed = [a for a in anfragen if a.status == "Ja"]
    externe_n = len(ev.externe_teamer or [])
    teamer_ok    = (sum(1 for a in confirmed if a.rolle_anfrage == "Teamer") + externe_n) >= ev.anzahl_teamer
    kuenstler_ok = sum(1 for a in confirmed if a.rolle_anfrage == "Künstler") >= ev.anzahl_kuenstler
    logistiker_ok = (not ev.material_mitnahme) or bool(ev.logistiker_id) or any(
        a.dienstleister.logistiker for a in confirmed if a.dienstleister)
    team_komplett = (bool(confirmed) or externe_n > 0) and teamer_ok and kuenstler_ok and logistiker_ok

    if (ev.zaubershow_event or ev.checkliste_uebersprungen) and not ev.cl_eingereicht_am:
                                  checkliste = ("na", "nicht nötig")
    elif ev.cl_eingereicht_am:    checkliste = ("done", "eingegangen")
    elif ev.checklist_token:      checkliste = ("doing", "abgeschickt")
    else:                         checkliste = ("todo", "offen")

    if ev.zaubershow_event:       team = ("na", "nicht nötig")
    elif team_komplett:           team = ("done", "Team komplett")
    elif anfragen:                team = ("doing", "angefragt")
    else:                         team = ("todo", "offen")

    if ev.zaubershow_event or not ev.material_mitnahme:  bestellungen = ("na", "nicht nötig")
    elif ev.material_bestellt:    bestellungen = ("done", "bestellt")
    else:                         bestellungen = ("todo", "offen")

    if ev.zaubershow_event:       briefing = ("na", "nicht nötig")
    elif ev.status in ("Briefing gesendet", "Abgeschlossen"): briefing = ("done", "gesendet")
    else:                         briefing = ("todo", "offen")
    abschluss = ("done", "abgeschlossen") if ev.status == "Abgeschlossen" else ("todo", "offen")

    steps = [
        {"key": "checkliste",   "label": "Checkliste",    "target": "wf-checkliste", "state": checkliste[0],   "tag": checkliste[1]},
        {"key": "team",         "label": "Verfügbarkeit", "target": "wf-team",       "state": team[0],         "tag": team[1], "open_anfragen": True},
        {"key": "bestellungen", "label": "Bestellungen",  "target": "wf-material",   "state": bestellungen[0], "tag": bestellungen[1]},
        {"key": "briefing",     "label": "Briefing",      "target": "wf-briefing",   "state": briefing[0],     "tag": briefing[1]},
        {"key": "abschluss",    "label": "Abschluss",     "target": "wf-abschluss",  "state": abschluss[0],    "tag": abschluss[1]},
    ]
    aktiv_idx = next((i for i, s in enumerate(steps) if s["state"] in ("todo", "doing")), len(steps) - 1)
    for i, s in enumerate(steps):
        s["active"] = (i == aktiv_idx)
    return steps


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404)
    anfragen = db.query(Verfuegbarkeitsanfrage).options(
        joinedload(Verfuegbarkeitsanfrage.dienstleister)).filter(
        Verfuegbarkeitsanfrage.event_id == event_id).all()

    anfragen_ids = {a.dienstleister_id: a for a in anfragen}
    workflow = _workflow_steps(ev, anfragen)

    # Termin-Serie (mehrtägiges Event): alle Geschwister-Termine, chronologisch
    serie_events = []
    if ev.serien_id:
        serie_events = db.query(Event).filter(
            Event.serien_id == ev.serien_id).order_by(Event.datum).all()

    active = db.query(Dienstleister).filter(Dienstleister.aktiv == True).all()

    # Doppelbuchung: bestätigte Einsätze anderer Events am selben Tag
    gebucht_map = {}
    if ev.datum:
        konflikte = db.query(Verfuegbarkeitsanfrage).join(
            Event, Verfuegbarkeitsanfrage.event_id == Event.id).options(
            joinedload(Verfuegbarkeitsanfrage.event)).filter(
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

    # Auto-Nachbesetzung (Vorschlag mit 1-Klick): offene Lücken + bester freier Ersatz.
    # Greift bei jeder Lücke (Absage, abgelaufene Anfrage, Aufstockung) auf einem aktiven,
    # kommenden Event. Der Vorschlag ist nur eine Vorauswahl – die volle Auswahlliste bleibt darunter.
    confirmed_ja = [a for a in anfragen if a.status == "Ja"]
    conf_teamer = sum(1 for a in confirmed_ja if a.rolle_anfrage == "Teamer") + len(ev.externe_teamer or [])
    conf_kuenstler = sum(1 for a in confirmed_ja if a.rolle_anfrage == "Künstler")
    fehlend_teamer = max(0, (ev.anzahl_teamer or 0) - conf_teamer)
    fehlend_kuenstler = max(0, (ev.anzahl_kuenstler or 0) - conf_kuenstler)

    def _erster_freier(ranked):
        for d in ranked:
            if d.id not in anfragen_ids and d.id not in unavailable_ids:
                return d
        return None

    nachbesetzung_aktiv = (ev.status not in GESPERRTE_STATUS and not ev.zaubershow_event
                           and bool(ev.datum) and ev.datum >= date.today())
    vorschlag_teamer = _erster_freier(ranked_teamer) if (nachbesetzung_aktiv and fehlend_teamer) else None
    vorschlag_kuenstler = _erster_freier(ranked_kuenstler) if (nachbesetzung_aktiv and fehlend_kuenstler) else None

    # "Länger nicht angefragt": letzte Anfrage je Dienstleister älter als 6 Monate
    grenze = date.today() - timedelta(days=180)
    letzte = db.query(Verfuegbarkeitsanfrage.dienstleister_id, func.max(Event.datum)).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).group_by(
        Verfuegbarkeitsanfrage.dienstleister_id).all()
    lange_her_ids = {did for did, last in letzte if last and last < grenze}

    # Kartendaten (Leaflet/OpenStreetMap) – Verortung: PLZ → PLZ in Straße → Stadtname
    event_coords = get_coords_for_address(ev.veranstaltungsort)
    karte_dienstleister = []
    karte_ohne_standort = []
    for d in active:
        c = get_coords_for_dienstleister(d)
        if c:
            karte_dienstleister.append({
                "name": f"{d.vorname} {d.nachname}", "lat": c[0], "lon": c[1],
                "rolle": d.rolle, "sparte": d.kuenstler_sparte or "", "logistiker": bool(d.logistiker),
                "stadt": d.stadt or "",
                "distanz": round(getattr(d, "rang_distanz_km", None)) if getattr(d, "rang_distanz_km", None) is not None else None,
            })
        else:
            karte_ohne_standort.append(f"{d.vorname} {d.nachname}")
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
                    karte_data=karte_data, karte_ohne_standort=karte_ohne_standort,
                    needs_material=needs_material, serie_events=serie_events,
                    nachbesetzung_aktiv=nachbesetzung_aktiv,
                    fehlend_teamer=fehlend_teamer, fehlend_kuenstler=fehlend_kuenstler,
                    vorschlag_teamer=vorschlag_teamer, vorschlag_kuenstler=vorschlag_kuenstler,
                    workflow=workflow))


@router.post("/events/{event_id}/serie/add")
def serie_tag_add(event_id: int, background_tasks: BackgroundTasks,
                  db: Session = Depends(get_db), _=Depends(get_admin_user),
                  neu_datum: str = Form(""), neu_startzeit: str = Form(""),
                  neu_endzeit: str = Form("")):
    """Fügt einem bestehenden Event nachträglich einen weiteren Termintag hinzu
    (legt eine Serie an, falls noch keine besteht)."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    tage, fehler = _parse_extra_tage([neu_datum], [neu_startzeit], [neu_endzeit],
                                     ev.startzeit, ev.endzeit)
    if fehler or not tage:
        return RedirectResponse(f"/admin/events/{event_id}?error=serie_datum", status_code=303)
    if not ev.serien_id:
        ev.serien_id = secrets.token_hex(8)
        db.flush()
    d, sz, ez = tage[0]
    # Neuer Termintag startet frisch als „Gebucht" – nicht den (evtl. weit fortgeschrittenen)
    # Status des Basis-Events erben, sonst wäre der neue Tag sofort „fertig"/gesperrt. (Review M2)
    sib = _neues_geschwister_event(ev, d, sz, ez, ev.serien_id, status="Gebucht")
    db.add(sib); db.commit(); db.refresh(sib)
    import calendar_service
    background_tasks.add_task(calendar_service.sync_event_async, sib.id)
    return RedirectResponse(f"/admin/events/{sib.id}", status_code=303)


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
def event_edit(request: Request, event_id: int, entsperrt: bool = False,
               db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if event_gesperrt(ev, entsperrt):
        return RedirectResponse(f"/admin/events/{event_id}?error=gesperrt", status_code=303)
    kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
    serie_count = db.query(Event).filter(Event.serien_id == ev.serien_id).count() if ev.serien_id else 0
    return templates.TemplateResponse("admin/event_form.html",
        tpl_context(request, event=ev, produkte_list=PRODUKTE_LIST, kunden=kunden,
                    anlass_list=ANLASS_LIST, error=None, entsperrt=entsperrt,
                    serie_count=serie_count))

@router.post("/events/{event_id}/edit")
def event_update(
    request: Request, event_id: int, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    anlass: str = Form(...), datum: str = Form(...),
    startzeit: str = Form(...), endzeit: str = Form(""),
    veranstaltungsort: str = Form(""), ort_abweichend: bool = Form(False),
    kunde_firma: str = Form(""), kunde_adresse: str = Form(""),
    kunde_kontakt: str = Form(""),
    kunde_telefon: str = Form(""), kunde_email: str = Form(""),
    vor_ort_name: str = Form(""), vor_ort_telefon: str = Form(""),
    produkte: list = Form([]),
    anzahl_teamer: int = Form(0), anzahl_kuenstler: int = Form(0),
    hinweise: str = Form(""), material_mitnahme: bool = Form(False),
    material_info_choice: str = Form(""), material_info_text: str = Form(""),
    transporter_angeboten: bool = Form(False),
    ankunft_modus: str = Form("auto"), ankunft_text: str = Form(""), treffpunkt: str = Form(""),
    checkliste_uebersprungen: bool = Form(False), zaubershow_event: bool = Form(False),
    status: str = Form("Gebucht"),
    marke: str = Form("Kindsalabim"), crm_verknuepfen: bool = Form(False),
    entsperrt: bool = Form(False), serie_propagieren: bool = Form(False),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if event_gesperrt(ev, entsperrt):
        return RedirectResponse(f"/admin/events/{event_id}?error=gesperrt", status_code=303)
    material_info = material_info_text.strip() if material_info_choice == "Sonstige" else material_info_choice
    if not ort_abweichend:
        veranstaltungsort = (kunde_adresse or "").strip()
    datum_d, fehler = validate_event_form(datum, startzeit, endzeit, kunde_telefon, veranstaltungsort, produkte, zaubershow=zaubershow_event, abgesagt=(status == "Abgesagt"))
    if fehler:
        kunden = db.query(Kunde).order_by(func.lower(Kunde.firma)).all()
        serie_count = db.query(Event).filter(Event.serien_id == ev.serien_id).count() if ev.serien_id else 0
        # Eingaben als Echo zurückgeben, damit nichts verloren geht (kein commit -> DB unberührt)
        echo = _event_form_echo(datum_d, datum, anlass, startzeit, endzeit, veranstaltungsort,
                                kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, produkte,
                                anzahl_teamer, anzahl_kuenstler, hinweise, material_mitnahme,
                                marke, status, event_id=ev.id, serien_id=ev.serien_id,
                                checkliste_uebersprungen=checkliste_uebersprungen,
                                zaubershow_event=zaubershow_event,
                                material_info=material_info, transporter_angeboten=transporter_angeboten,
                                ankunft_modus=ankunft_modus, ankunft_text=ankunft_text, treffpunkt=treffpunkt,
                                kunde_adresse=kunde_adresse, vor_ort_name=vor_ort_name,
                                vor_ort_telefon=vor_ort_telefon)
        return templates.TemplateResponse("admin/event_form.html",
            tpl_context(request, event=echo, produkte_list=PRODUKTE_LIST, kunden=kunden,
                        anlass_list=ANLASS_LIST, error=fehler, serie_count=serie_count))
    alter_status = ev.status
    ev.datum = datum_d
    ev.anlass = anlass; ev.startzeit = startzeit
    ev.endzeit = endzeit; ev.veranstaltungsort = veranstaltungsort
    ev.kunde_firma = kunde_firma; ev.kunde_adresse = kunde_adresse.strip() or None
    ev.kunde_kontakt = kunde_kontakt
    ev.kunde_telefon = kunde_telefon; ev.kunde_email = kunde_email
    ev.vor_ort_name = vor_ort_name.strip() or None
    ev.vor_ort_telefon = vor_ort_telefon.strip() or None
    ev.produkte = ", ".join(produkte); ev.anzahl_teamer = anzahl_teamer
    ev.anzahl_kuenstler = anzahl_kuenstler; ev.hinweise = hinweise
    ev.material_mitnahme = material_mitnahme; ev.marke = marke; ev.status = status
    ev.material_info = material_info; ev.transporter_angeboten = transporter_angeboten
    ev.ankunft_modus = ankunft_modus; ev.ankunft_text = ankunft_text.strip() or None
    ev.treffpunkt = treffpunkt.strip() or None
    ev.checkliste_uebersprungen = checkliste_uebersprungen
    ev.zaubershow_event = zaubershow_event
    if crm_verknuepfen:
        link_kunde(db, ev, kunde_firma, kunde_kontakt, kunde_telefon, kunde_email, marke)
    db.commit()
    # Status automatisch neu berechnen – aber nur, wenn er im Formular NICHT bewusst geändert
    # wurde (sonst würde eine manuelle Status-Wahl überschrieben). So schließt z. B. das
    # nachträgliche Setzen von „Zaubershow-Event" bei bereits gestellter Rechnung sofort ab.
    if status == alter_status:
        neu = auto_status(ev, db)
        if neu != ev.status:
            ev.status = neu
            db.commit()
    # Termin-Serie: gemeinsame Stammdaten auf die anderen Tage übernehmen (tagesspezifische
    # Felder – Datum/Uhrzeit/Status/Teamleiter/Checkliste/Bericht/Anfragen – bleiben unberührt)
    geschwister_sync = []
    if serie_propagieren and ev.serien_id:
        geschwister = db.query(Event).filter(
            Event.serien_id == ev.serien_id, Event.id != ev.id).all()
        for g in geschwister:
            g.kunde_firma = ev.kunde_firma; g.kunde_adresse = ev.kunde_adresse
            g.kunde_kontakt = ev.kunde_kontakt
            g.kunde_telefon = ev.kunde_telefon; g.kunde_email = ev.kunde_email
            g.vor_ort_name = ev.vor_ort_name; g.vor_ort_telefon = ev.vor_ort_telefon
            g.veranstaltungsort = ev.veranstaltungsort
            g.anlass = ev.anlass; g.marke = ev.marke; g.kunde_id = ev.kunde_id
            # Zaubershow-Kennzeichen gilt für die ganze Buchung – mit übernehmen (sonst
            # müsste man es pro Termintag einzeln setzen). Der Status bleibt pro Tag.
            g.zaubershow_event = ev.zaubershow_event
            geschwister_sync.append(g.id)
        db.commit()
    import calendar_service
    background_tasks.add_task(calendar_service.sync_event_async, event_id)
    for gid in geschwister_sync:
        background_tasks.add_task(calendar_service.sync_event_async, gid)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/delete")
def event_delete(event_id: int, background_tasks: BackgroundTasks,
                 db: Session = Depends(get_db), user=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if ev:
        import calendar_service
        from papierkorb import archive_event
        archive_event(db, ev, user.get("sub") or user.get("email"))  # Notfall-Sicherung vor dem Löschen
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
    # "Abgeschlossen" und "Abgesagt" sind final – nie automatisch überschreiben
    if ev.status in ("Abgeschlossen", "Abgesagt"):
        return ev.status
    # Reines Zaubershow-Event: kein Team/Briefing/Eventbericht – Abschluss allein über die Rechnung
    if ev.zaubershow_event and ev.rechnung_gestellt:
        return "Abgeschlossen"
    # Nach dem Briefing: automatischer Abschluss, sobald Bericht da UND Rechnung gestellt
    if ev.status == "Briefing gesendet":
        if ev.bericht_eingereicht_am and ev.rechnung_gestellt:
            return "Abgeschlossen"
        return ev.status

    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id).all()
    confirmed = [a for a in anfragen if a.status == "Ja"]

    teamer_ok    = (sum(1 for a in confirmed if a.rolle_anfrage == "Teamer") + len(ev.externe_teamer or [])) >= ev.anzahl_teamer
    kuenstler_ok = sum(1 for a in confirmed if a.rolle_anfrage == "Künstler")  >= ev.anzahl_kuenstler

    # Logistiker: nur nötig, wenn Material transportiert werden muss
    logistiker_ok = (not ev.material_mitnahme) or bool(ev.logistiker_id) or any(
        a.dienstleister.logistiker for a in confirmed if a.dienstleister)

    # Material: wenn Mitnahme nötig, muss es auch bestellt sein
    material_ok = (not ev.material_mitnahme) or ev.material_bestellt

    checkliste_ok = bool(ev.cl_eingereicht_am or ev.checkliste_uebersprungen or ev.zaubershow_event)
    if teamer_ok and kuenstler_ok and logistiker_ok and material_ok and checkliste_ok:
        return "Planung fertig"
    if ev.cl_eingereicht_am:
        return "Checkliste eingegangen"
    if ev.checklist_token and not ev.cl_eingereicht_am:
        return "Checkliste geschickt"
    if anfragen:
        return "Dienstleister angefragt"
    return ev.status  # bleibt "Gebucht" / manuell gesetzt


# ── Verfügbarkeitsanfragen ─────────────────────────────────────────────────────

@router.post("/events/{event_id}/anfragen")
def send_anfragen(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    dienstleister_ids: list = Form([]),
    logistiker_ids: list = Form([]),
    rolle: str = Form("Teamer"),
    entsperrt: bool = Form(False),
    serie: bool = Form(False),
    direkt: bool = Form(False),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if event_gesperrt(ev, entsperrt):
        return RedirectResponse(f"/admin/events/{event_id}?error=gesperrt", status_code=303)
    if not dienstleister_ids:
        return RedirectResponse(f"/admin/events/{event_id}?error=keine_auswahl", status_code=303)
    logi_ids = {int(x) for x in logistiker_ids}  # als Logistiker (Materialtransport) angefragt

    # Ziel-Termine: ganze Serie (alle Tage gleichzeitig anfragen) oder nur dieses Event.
    # Abgesagte/abgeschlossene Serientage überspringen – dafür braucht es keine Anfragen. (Review M3)
    if serie and ev.serien_id:
        ziel_events = db.query(Event).filter(
            Event.serien_id == ev.serien_id,
            Event.status.notin_(GESPERRTE_STATUS)).order_by(Event.datum).all()
    else:
        ziel_events = [ev]

    base_url = str(request.base_url).rstrip("/")
    gesendet, fehler = 0, 0
    for did in dienstleister_ids:
        did = int(did)
        d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
        if not d:
            continue
        # "Ohne Mail" (Altbestand): nur bei echtem Versand wird eine gültige E-Mail benötigt.
        if not direkt and (not d.email or "@" not in d.email):
            fehler += 1
            print(f"[ANFRAGE] übersprungen, keine gültige E-Mail: DL {did}")
            continue
        # Auf welchen Ziel-Tagen besteht noch keine Anfrage für diesen Dienstleister?
        offene_tage = [ze for ze in ziel_events if not db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == ze.id,
            Verfuegbarkeitsanfrage.dienstleister_id == did).first()]
        if not offene_tage:
            continue
        # Direkt-Eintrag ohne Mail: als bereits zugesagt anlegen (Personal aus dem alten System).
        if direkt:
            for ze in offene_tage:
                db.add(Verfuegbarkeitsanfrage(
                    event_id=ze.id, dienstleister_id=did,
                    rolle_anfrage=rolle, status="Ja", als_logistiker=(did in logi_ids),
                    erstellt_am=datetime.now().strftime("%d.%m.%Y %H:%M"),
                    notiz="Manuell als zugesagt eingetragen (ohne Mail)",
                ))
                if did in logi_ids:
                    ze.logistiker_id = did  # direkt eingetragener Logistiker
            db.commit()
            gesendet += 1
            continue
        # Versand pro Dienstleister absichern: ein einzelner Mailfehler darf weder die
        # ganze Aktion zum 500 bringen noch andere Anfragen zurückrollen. Die Anfragen
        # werden nur bei erfolgreichem Versand persistiert -> Fehlgeschlagene sind erneut sendbar.
        try:
            from auth import create_magic_token
            token = create_magic_token(d, db)
            magic_url = f"{base_url}/portal/auth/{token}"
            neue = []
            for ze in offene_tage:
                a = Verfuegbarkeitsanfrage(
                    event_id=ze.id, dienstleister_id=did,
                    rolle_anfrage=rolle, status="Ausstehend", als_logistiker=(did in logi_ids),
                    erstellt_am=datetime.now().strftime("%d.%m.%Y %H:%M"),
                    frist_datum=date.today() + timedelta(days=ANFRAGE_FRIST_TAGE),
                )
                db.add(a); db.flush()  # a.id für die Antwort-Links verfügbar machen
                neue.append((ze, a))
            # Eine Mail pro Dienstleister: bei mehreren Tagen die kombinierte Serien-Mail
            if len(neue) == 1:
                ze, a = neue[0]
                send_verfuegbarkeitsanfrage(d, ze, a.id, base_url, magic_url=magic_url,
                                            als_logistiker=(did in logi_ids))
            else:
                send_serie_anfrage(d, [ze for ze, a in neue], base_url, magic_url=magic_url)
            db.commit()
            gesendet += 1
        except Exception as e:
            db.rollback()
            fehler += 1
            print(f"[ANFRAGE-MAIL FEHLER] DL {did} ({d.email}): {e}")
    for ze in ziel_events:
        ze.status = auto_status(ze, db)
    db.commit()
    if fehler:
        return RedirectResponse(
            f"/admin/events/{event_id}?gesendet={gesendet}&mailfehler={fehler}",
            status_code=303)
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
    wert = (gestellt == "1")
    # Die Rechnung gehört zur ganzen Buchung: bei einer Serie für ALLE Termintage setzen,
    # damit man nicht pro Tag klicken muss. auto_status schließt danach jeden Tag ab, sobald
    # DESSEN Bedingungen erfüllt sind (reine Zaubershow sofort, sonst weiter erst mit Bericht).
    ziel = (db.query(Event).filter(Event.serien_id == ev.serien_id).all()
            if ev.serien_id else [ev])
    for e in ziel:
        e.rechnung_gestellt = wert
    db.commit()
    for e in ziel:
        e.status = auto_status(e, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/anfrage/{anfrage_id}/entfernen")
def anfrage_entfernen(
    event_id: int, anfrage_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
):
    """Einen Dienstleister vom Event entfernen (Anfrage löschen) – z. B. wenn er
    versehentlich eingetragen wurde. Betrifft nur diesen einen Termin(-tag); bei einer
    Serie bleiben die anderen Tage unberührt. War die Person Teamleiter/Logistiker
    dieses Events, werden diese Zuordnungen mitgelöst."""
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.event_id == event_id).first()
    if not a:
        raise HTTPException(404)
    ev = db.query(Event).filter(Event.id == event_id).first()
    did = a.dienstleister_id
    if ev and ev.teamleiter_id == did:
        ev.teamleiter_id = None
    if ev and ev.logistiker_id == did:
        ev.logistiker_id = None
    db.delete(a)
    db.commit()
    if ev:
        ev.status = auto_status(ev, db)
        db.commit()
    return RedirectResponse(f"/admin/events/{event_id}#wf-team", status_code=303)

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

@router.post("/events/{event_id}/logistiker")
def set_logistiker(
    event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    logistiker_id: str = Form(""),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.logistiker_id = int(logistiker_id) if logistiker_id else None
    db.commit()
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}#wf-material", status_code=303)

@router.post("/events/{event_id}/material-bereit")
def material_bereit(
    request: Request, event_id: int, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
):
    """Markiert das Material als abholbereit und benachrichtigt den zugeteilten Logistiker."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if not ev.logistiker_id:
        return RedirectResponse(f"/admin/events/{event_id}?error=kein_logistiker#wf-material", status_code=303)
    ev.material_bereit = True
    mail_ok = False
    log = ev.logistiker
    if log and log.email and "@" in log.email and not ev.material_bereit_gesendet:
        try:
            from email_service import send_material_bereit
            send_material_bereit(ev, log)
            ev.material_bereit_gesendet = True
            mail_ok = True
        except Exception as e:
            print(f"[MATERIAL-BEREIT-MAIL FEHLER] Event {ev.id}: {e}")
    db.commit()
    flag = "material_bereit=1" if mail_ok else "material_bereit_nomail=1"
    return RedirectResponse(f"/admin/events/{event_id}?{flag}#wf-material", status_code=303)

@router.post("/events/{event_id}/checklist")
def send_checklist(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    entsperrt: bool = Form(False),
):
    import uuid
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if event_gesperrt(ev, entsperrt):
        return RedirectResponse(f"/admin/events/{event_id}?error=gesperrt", status_code=303)
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


def _briefing_versenden_async(event_id: int, base_url: str):
    """Lädt die Planungsdateien aus R2 und verschickt das Briefing an alle Zusagen.
    Läuft als BackgroundTask mit eigener DB-Session – der R2-Download (bis 20 MB je
    Datei) und der Versand pro Empfänger blockieren so nicht mehr den Request. (Review H6)"""
    db = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.id == event_id).first()
        if not ev:
            return
        confirmed = db.query(Verfuegbarkeitsanfrage).options(
            joinedload(Verfuegbarkeitsanfrage.dienstleister)).filter(
            Verfuegbarkeitsanfrage.event_id == event_id,
            Verfuegbarkeitsanfrage.status == "Ja").all()
        dienstleister = [a.dienstleister for a in confirmed if a.dienstleister]
        planung = db.query(EventDatei).filter(
            EventDatei.event_id == event_id, EventDatei.typ == "planung").all()
        anhaenge = [(d.filename, download_file(d.r2_key)) for d in planung]
        anhaenge = [(fn, data) for fn, data in anhaenge if data]
        externe = db.query(ExternerTeamer).filter(ExternerTeamer.event_id == event_id).all()
        from notifications import get_setting
        from choices import BRIEFING_REGELN_DEFAULT
        regeln = get_setting(db, "briefing_regeln", BRIEFING_REGELN_DEFAULT).strip() or None
        # Briefing zusätzlich als PDF an die Mail hängen – so kann der Teamer es
        # direkt aufs Handy speichern (offline, ohne Login).
        pdf_dabei = False
        try:
            from briefing_pdf import build_briefing_pdf
            pdf = build_briefing_pdf(ev, dienstleister, externe, regeln=regeln)
            pdf_name = f"Briefing_{(ev.anlass or 'Event').replace(' ', '_')}_{ev.datum.strftime('%Y-%m-%d')}.pdf"
            anhaenge = (anhaenge or []) + [(pdf_name, pdf)]
            pdf_dabei = True
        except Exception as e:
            print(f"[BRIEFING-PDF FEHLER] Event {event_id}: {e}")
        try:
            send_briefing(dienstleister, ev, base_url, anhaenge or None, externe=externe,
                          regeln=regeln, pdf_hinweis=pdf_dabei)
        except Exception as e:
            print(f"[BRIEFING-VERSAND FEHLER] Event {event_id}: {e}")
    finally:
        db.close()


@router.post("/events/{event_id}/briefing")
def send_briefing_route(
    request: Request, event_id: int, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), _=Depends(get_admin_user),
    entsperrt: bool = Form(False),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if event_gesperrt(ev, entsperrt):
        return RedirectResponse(f"/admin/events/{event_id}?error=gesperrt", status_code=303)
    base_url = str(request.base_url).rstrip("/")
    ev.status = "Briefing gesendet"
    db.commit()
    # Versand (R2-Download + Mails) im Hintergrund – die Seite kehrt sofort zurück.
    background_tasks.add_task(_briefing_versenden_async, event_id, base_url)
    return RedirectResponse(f"/admin/events/{event_id}?briefing_sent=1", status_code=303)


@router.get("/events/{event_id}/briefing/pdf")
def briefing_pdf_download(event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Briefing als PDF zum Download (z. B. für externe Agentur-Leute ohne Portal)."""
    from fastapi.responses import StreamingResponse
    from briefing_pdf import build_briefing_pdf
    import io
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
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


@router.post("/events/{event_id}/extern-teamer")
def extern_teamer_add(event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
                      name: str = Form(""), telefon: str = Form("")):
    """Einmaligen (externen) Teamer fürs Event eintragen – erscheint in der Team-Liste."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    if name.strip():
        db.add(ExternerTeamer(event_id=event_id, name=name.strip(), telefon=telefon.strip() or None))
        db.commit()
    return RedirectResponse(f"/admin/events/{event_id}#wf-briefing", status_code=303)


@router.post("/events/{event_id}/extern-teamer/{teamer_id}/delete")
def extern_teamer_delete(event_id: int, teamer_id: int,
                         db: Session = Depends(get_db), _=Depends(get_admin_user)):
    t = db.query(ExternerTeamer).filter(
        ExternerTeamer.id == teamer_id, ExternerTeamer.event_id == event_id).first()
    if t:
        db.delete(t); db.commit()
    return RedirectResponse(f"/admin/events/{event_id}#wf-briefing", status_code=303)


def _letztes_briefing_event(db: Session, ev: Event):
    """Jüngstes anderes Event desselben Kunden, das schon Briefing-Daten hat.
    Quelle für „Briefing übernehmen" bei Stammkunden (gleicher Ort/Ablauf wie immer).
    Kundenzuordnung über die CRM-Verknüpfung, sonst über den Firmennamen."""
    q = db.query(Event).filter(Event.id != ev.id,
                               Event.cl_eingereicht_am.isnot(None))
    if ev.kunde_id:
        q = q.filter(Event.kunde_id == ev.kunde_id)
    elif ev.kunde_firma:
        q = q.filter(Event.kunde_firma == ev.kunde_firma)
    else:
        return None
    return q.order_by(Event.datum.desc()).first()


@router.get("/events/{event_id}/checklist/edit", response_class=HTMLResponse)
def briefing_edit(request: Request, event_id: int, uebernehmen: int = 0,
                  db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Admin-Formular, um die Checklisten-/Briefing-Daten (cl_*) selbst auszufüllen
    oder zu korrigieren – falls der Kunde die Checkliste nicht (rechtzeitig) schickt.
    Leere Felder werden aus den Event-Daten vorbelegt (Checklisten-Werte haben Vorrang).
    Mit ?uebernehmen=1 werden die Felder aus dem letzten Event desselben Kunden
    vorbefüllt – gespeichert wird erst beim Absenden des Formulars."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    # Veranstaltungsort grob in Straße / PLZ+Ort aufteilen (erster Komma-Trenner)
    ort = (ev.veranstaltungsort or "").strip()
    strasse_def, plz_ort_def = (ort.split(",", 1) + [""])[:2] if "," in ort else (ort, "")
    vor = {
        "ansprechpartner_name":  ev.cl_ansprechpartner_name  or ev.vor_ort_name or ev.kunde_kontakt or "",
        "ansprechpartner_mobil": ev.cl_ansprechpartner_mobil or ev.vor_ort_telefon or ev.kunde_telefon or "",
        "firma_name":            ev.cl_firma_name or ev.kunde_firma or "",
        "strasse":               ev.cl_strasse  or strasse_def.strip(),
        "plz_ort":               ev.cl_plz_ort  or plz_ort_def.strip(),
        "aufbauort":   ev.cl_aufbauort  or (ev.outdoor_indoor or ""),
        "verpflegung": ev.cl_verpflegung or "",
        "teamkleidung": ev.cl_teamkleidung or ("Ja" if ev.teamkleidung else ""),
        "parkplatz":   ev.cl_parkplatz or (ev.parkplatz or ""),
        "weitere_details": ev.cl_weitere_details or "",
    }
    quelle = _letztes_briefing_event(db, ev)
    uebernommen = bool(uebernehmen and quelle)
    if uebernommen:
        # Werte des Vorgänger-Events gewinnen – leere Felder dort lassen die Vorbelegung stehen.
        for ziel, feld in [
            ("ansprechpartner_name", "cl_ansprechpartner_name"),
            ("ansprechpartner_mobil", "cl_ansprechpartner_mobil"),
            ("firma_name", "cl_firma_name"), ("strasse", "cl_strasse"),
            ("plz_ort", "cl_plz_ort"), ("aufbauort", "cl_aufbauort"),
            ("verpflegung", "cl_verpflegung"), ("teamkleidung", "cl_teamkleidung"),
            ("parkplatz", "cl_parkplatz"), ("weitere_details", "cl_weitere_details"),
        ]:
            wert = getattr(quelle, feld, None)
            if wert:
                vor[ziel] = wert
    return templates.TemplateResponse("admin/briefing_edit.html", tpl_context(
        request, ev=ev, vor=vor, quelle=quelle, uebernommen=uebernommen))


@router.post("/events/{event_id}/checklist/edit")
def briefing_edit_save(
    request: Request, event_id: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    ansprechpartner_name: str = Form(""), ansprechpartner_mobil: str = Form(""),
    firma_name: str = Form(""), strasse: str = Form(""), plz_ort: str = Form(""),
    aufbauort: list = Form([]), verpflegung: str = Form(""),
    teamkleidung: str = Form(""), parkplatz: str = Form(""),
    weitere_details: str = Form(""),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev: raise HTTPException(404)
    ev.cl_ansprechpartner_name  = ansprechpartner_name
    ev.cl_ansprechpartner_mobil = ansprechpartner_mobil
    ev.cl_firma_name            = firma_name
    ev.cl_strasse               = strasse
    ev.cl_plz_ort               = plz_ort
    # Auf-/Abbauzeiten (cl_aufbau_*/cl_abbau_*) bleiben unangetastet – sie gehören der
    # Kunden-Checkliste; das Briefing nutzt sie nicht mehr.
    ev.cl_aufbauort             = ", ".join(aufbauort)
    ev.cl_verpflegung           = verpflegung
    ev.cl_teamkleidung          = teamkleidung
    ev.cl_parkplatz             = parkplatz
    ev.cl_weitere_details       = weitere_details.strip() or None
    # Markiert die Daten als vorhanden (Workflow „eingegangen"); Kunden-Einreichzeit bleibt erhalten
    if not ev.cl_eingereicht_am:
        ev.cl_eingereicht_am = datetime.now().strftime("%d.%m.%Y %H:%M") + " (selbst ausgefüllt)"
    db.commit()
    ev.status = auto_status(ev, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?briefing_edit=1", status_code=303)


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
        "Rolle", "Künstler-Sparte", "Erfahrungspunkte", "Mobilität", "Kleidergröße", "Gebiet",
        "Verfügbarkeit", "Vertragstyp", "Stundensatz Teamer", "Stundensatz Künstler",
        "DSGVO", "Logistiker", "Führerschein", "Website", "Aktiv", "Notizen",
    ])
    for d in alle:
        def euro(v):
            return f"{v:.2f}".replace(".", ",") if v else ""
        w.writerow([
            d.vorname or "", d.nachname or "", d.email or "", d.telefon or "",
            d.strasse or "", d.plz or "", d.stadt or "", d.rolle or "",
            d.kuenstler_sparte or "",
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
    rolle: str = Form("Teamer"), kuenstler_sparte: str = Form(""),
    erfahrungspunkte: int = Form(0),
    qualitaet: str = Form(""),
    mobilitaet: str = Form("Auto"), kleidergroesse: str = Form(""),
    aktiv: bool = Form(False), logistiker: bool = Form(False),
    fuehrerschein: bool = Form(False),
    teamshirt_kindsalabim: bool = Form(False), teamshirt_knallfrosch: bool = Form(False),
    portal_passwort: str = Form(""),
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
    fehler = validate_dienstleister_form(telefon, plz, stundensatz_teamer,
                                         stundensatz_kuenstler, portal_passwort)
    if fehler:
        return templates.TemplateResponse("admin/contractor_form.html",
            tpl_context(request, d=None, error=fehler))
    pw_hash = hash_password(portal_passwort) if portal_passwort else None

    def _f(s):
        try: return float(s.replace(",", ".")) if s.strip() else None
        except: return None

    def _qual(s):
        return int(s) if s.strip() in ("1", "2", "3", "4", "5") else None

    d = Dienstleister(
        vorname=vorname, nachname=nachname, email=email, telefon=telefon,
        strasse=strasse, plz=plz, stadt=stadt, rolle=rolle,
        kuenstler_sparte=kuenstler_sparte.strip() or None,
        erfahrungspunkte=erfahrungspunkte, qualitaet=_qual(qualitaet),
        mobilitaet=mobilitaet,
        kleidergroesse=kleidergroesse, aktiv=aktiv, logistiker=logistiker,
        fuehrerschein=fuehrerschein,
        teamshirt_kindsalabim=teamshirt_kindsalabim, teamshirt_knallfrosch=teamshirt_knallfrosch,
        password_hash=pw_hash,
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
    anfragen = db.query(Verfuegbarkeitsanfrage).options(
        joinedload(Verfuegbarkeitsanfrage.event)).filter(
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
    rolle: str = Form("Teamer"), kuenstler_sparte: str = Form(""),
    erfahrungspunkte: int = Form(0),
    qualitaet: str = Form(""),
    mobilitaet: str = Form("Auto"), kleidergroesse: str = Form(""),
    aktiv: bool = Form(False), logistiker: bool = Form(False),
    fuehrerschein: bool = Form(False),
    teamshirt_kindsalabim: bool = Form(False), teamshirt_knallfrosch: bool = Form(False),
    portal_passwort: str = Form(""),
    gebiet: str = Form(""), verfuegbarkeit: str = Form(""),
    vertragstyp: str = Form(""), stundensatz_teamer: str = Form(""),
    stundensatz_kuenstler: str = Form(""),
    dsgvo_unterzeichnet: bool = Form(False),
    website: str = Form(""), notizen: str = Form(""),
):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if not d: raise HTTPException(404)

    fehler = validate_dienstleister_form(telefon, plz, stundensatz_teamer,
                                         stundensatz_kuenstler, portal_passwort)
    if fehler:
        return templates.TemplateResponse("admin/contractor_form.html",
            tpl_context(request, d=d, error=fehler))

    def _f(s):
        try: return float(s.replace(",", ".")) if s.strip() else None
        except: return None

    d.vorname = vorname; d.nachname = nachname; d.email = email
    d.telefon = telefon; d.strasse = strasse; d.plz = plz; d.stadt = stadt
    d.rolle = rolle; d.kuenstler_sparte = kuenstler_sparte.strip() or None
    d.erfahrungspunkte = erfahrungspunkte
    d.qualitaet = int(qualitaet) if qualitaet.strip() in ("1", "2", "3", "4", "5") else None
    d.mobilitaet = mobilitaet; d.kleidergroesse = kleidergroesse
    d.aktiv = aktiv; d.logistiker = logistiker; d.fuehrerschein = fuehrerschein
    d.teamshirt_kindsalabim = teamshirt_kindsalabim
    d.teamshirt_knallfrosch = teamshirt_knallfrosch
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
def dienstleister_delete(did: int, db: Session = Depends(get_db), user=Depends(get_admin_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    if d:
        from papierkorb import archive_dienstleister
        archive_dienstleister(db, d, user.get("sub") or user.get("email"))  # Notfall-Sicherung (inkl. Anfragen/Sperrzeiten)
        # Verknüpfte Daten zuerst lösen, sonst blockiert der Fremdschlüssel die Löschung
        db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.dienstleister_id == did).delete(synchronize_session=False)
        db.query(DienstleisterSperrzeit).filter(
            DienstleisterSperrzeit.dienstleister_id == did).delete(synchronize_session=False)
        # Teamleiter- und Logistiker-Verknüpfung an Events lösen (FK ohne Cascade)
        db.query(Event).filter(Event.teamleiter_id == did).update(
            {Event.teamleiter_id: None}, synchronize_session=False)
        db.query(Event).filter(Event.logistiker_id == did).update(
            {Event.logistiker_id: None}, synchronize_session=False)
        db.delete(d)
        db.commit()
    return RedirectResponse("/admin/dienstleister?geloescht=1", status_code=303)
