"""Customer-Management (CRM).

Stufe 1: Kundenprofile (Stammdaten, Profil-Wissen, Tags) + Eventhistorie
inkl. der vom Teamleiter eingereichten Eventberichte. Pipeline-Kanban,
Aktivitäten und Wiedervorlagen folgen in späteren Stufen.
"""
from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
                     Request, UploadFile)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload
from datetime import datetime, date

from database import get_db
from models import (Kunde, KundeTag, Event, KUNDE_STATUS,
                    KundeAktivitaet, KundeWiedervorlage)
from auth import get_admin_user
from rechte import nur_inhaber
from config import get_config
from choices import de_date, weitere_ap_liste, weitere_ap_json

router = APIRouter(prefix="/admin/crm")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.globals["weitere_ap_liste"] = weitere_ap_liste

STATUS_LABEL = {
    "lead":     "Neuer Lead",
    "kontakt":  "Kontakt aufgenommen",
    "bedarf":   "Bedarf geklärt",
    "angebot":  "Angebot versendet",
    "gebucht":  "Gebucht",
    "verloren": "Verloren / Abgesagt",
}

# Farben für automatisch angelegte Tags (rotierend)
TAG_PALETTE = ["#1D4E89", "#1f7a44", "#b07d1a", "#c0473f",
               "#5b21b6", "#0e7490", "#be185d", "#3D7DBC"]

AKTIVITAET_TYPEN = {
    "notiz":   "Notiz",
    "anruf":   "Telefonat",
    "email":   "E-Mail",
    "meeting": "Meeting",
    "angebot": "Angebot",
}

PRIORITAET_LABEL = {"niedrig": "Niedrig", "mittel": "Mittel", "hoch": "Hoch"}


def tpl(request, **kw):
    return {"request": request, "cfg": get_config(),
            "STATUS": KUNDE_STATUS, "STATUS_LABEL": STATUS_LABEL,
            "AKTIVITAET_TYPEN": AKTIVITAET_TYPEN, "PRIORITAET_LABEL": PRIORITAET_LABEL,
            "heute": date.today(), **kw}


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s and s.strip() else None
    except ValueError:
        return None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _apply_tags(db: Session, kunde: Kunde, tag_str: str):
    """Komma-/Semikolon-getrennte Tags matchen oder neu anlegen (case-insensitiv)."""
    roh = (tag_str or "").replace(";", ",").split(",")
    seen = {}
    for t in roh:
        t = t.strip()
        if t:
            seen.setdefault(t.lower(), t)
    tags = []
    for low, name in seen.items():
        tag = db.query(KundeTag).filter(func.lower(KundeTag.name) == low).first()
        if not tag:
            farbe = TAG_PALETTE[db.query(KundeTag).count() % len(TAG_PALETTE)]
            tag = KundeTag(name=name, farbe=farbe)
            db.add(tag); db.flush()
        tags.append(tag)
    kunde.tags = tags


def _kunde_form_echo(raw, bestehend=None):
    """Formular-Echo nach einem Validierungsfehler: spiegelt die EINGEGEBENEN Werte
    zurück ins Template, damit nichts Getipptes verloren geht. `bestehend` = DB-Objekt
    beim Bearbeiten (liefert die id, die „Neu" von „Bearbeiten" unterscheidet)."""
    from types import SimpleNamespace

    def g(key, default=""):
        return (raw.get(key) or default).strip()

    status = raw.get("pipeline_status")
    return SimpleNamespace(
        id=getattr(bestehend, "id", None),
        firma=g("firma"), ansprechpartner=g("ansprechpartner"), branche=g("branche"),
        telefon=g("telefon"), email=g("email"), rechnung_email=g("rechnung_email"),
        strasse=g("strasse"), plz=g("plz"), ort=g("ort"), website=g("website"),
        pipeline_status=status if status in KUNDE_STATUS else "lead",
        marke=raw.get("marke") or "Kindsalabim",
        # Tags als Objekte mit .name – das Template rendert sie per map(attribute='name')
        tags=[SimpleNamespace(name=t.strip())
              for t in (raw.get("tags") or "").replace(";", ",").split(",") if t.strip()],
        notizen=g("notizen"), kommunikationsstil=g("kommunikationsstil"),
        besonderheiten=g("besonderheiten"),
        bevorzugte_eventarten=g("bevorzugte_eventarten"),
        typische_budgets=g("typische_budgets"),
        weitere_ansprechpartner=weitere_ap_json(raw.getlist("kap_name"),
                                                raw.getlist("kap_telefon"),
                                                raw.getlist("kap_email")),
    )


def _apply_form(db, k: Kunde, f: dict):
    def g(key):
        return (f.get(key) or "").strip()
    k.firma = g("firma")
    k.ansprechpartner = g("ansprechpartner") or None
    k.telefon = g("telefon") or None
    k.email = g("email") or None
    k.rechnung_email = g("rechnung_email") or None
    k.strasse = g("strasse") or None
    k.plz = g("plz") or None
    k.ort = g("ort") or None
    k.website = g("website") or None
    k.branche = g("branche") or None
    k.marke = f.get("marke") or "Kindsalabim"
    status = f.get("pipeline_status")
    k.pipeline_status = status if status in KUNDE_STATUS else "lead"
    k.notizen = g("notizen") or None
    k.kommunikationsstil = g("kommunikationsstil") or None
    k.besonderheiten = g("besonderheiten") or None
    k.bevorzugte_eventarten = g("bevorzugte_eventarten") or None
    k.typische_budgets = g("typische_budgets") or None
    _apply_tags(db, k, f.get("tags", ""))
    k.aktualisiert_am = _now()


# ── Liste ────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def kunden_list(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
                tag: str = "", status: str = ""):
    q = db.query(Kunde).filter(Kunde.herkunft != "akquise")
    if status in KUNDE_STATUS:
        q = q.filter(Kunde.pipeline_status == status)
    if tag:
        q = q.filter(Kunde.tags.any(KundeTag.name == tag))
    # Tags gleich mitladen – sonst holt das Template sie je Kunde einzeln nach (N+1)
    kunden = q.options(selectinload(Kunde.tags)).order_by(func.lower(Kunde.firma)).all()
    # Event-Anzahl je Kunde (eine Aggregat-Query statt N+1)
    counts = dict(db.query(Event.kunde_id, func.count(Event.id))
                  .filter(Event.kunde_id != None)  # noqa: E711
                  .group_by(Event.kunde_id).all())
    alle_tags = db.query(KundeTag).order_by(func.lower(KundeTag.name)).all()
    return templates.TemplateResponse("admin/crm_kunden.html",
        tpl(request, active="crm", kunden=kunden, counts=counts,
            alle_tags=alle_tags, filter_tag=tag, filter_status=status))


# ── Akquise: recherchierte Kontakte, Sperrliste, Not-Aus ─────────────────────

SPALTEN_HILFE = ("Organisation; Art; Ort; Kontaktweg; Quelle; Veranstaltung; "
                 "Ansprachemonat; Notiz")


@router.get("/akquise", response_class=HTMLResponse)
def akquise(request: Request, db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    """Kaltakquise-Kontakte aus der Recherche, getrennt von den Bestandskunden."""
    import vertrieb
    from models import VertriebSperre
    kontakte = (db.query(Kunde).filter(Kunde.herkunft == "akquise")
                .order_by(Kunde.ansprachemonat.is_(None), Kunde.ansprachemonat,
                          func.lower(Kunde.firma)).all())
    offen = [k for k in kontakte if k.pipeline_status == "lead"]
    sperren = db.query(VertriebSperre).order_by(VertriebSperre.id.desc()).all()
    return templates.TemplateResponse("admin/crm_akquise.html",
        tpl(request, active="crm", kontakte=kontakte, offen=offen, sperren=sperren,
            gestoppt=vertrieb.versand_gestoppt(db), gruende=vertrieb.GRUENDE,
            rest_heute=vertrieb.rest_heute(db), limit_tag=vertrieb.tageslimit(db),
            ebenen=vertrieb.EBENEN, spalten=SPALTEN_HILFE,
            monat_namen=["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                         "August", "September", "Oktober", "November", "Dezember"]))


@router.post("/akquise/import")
async def akquise_import(request: Request, datei: UploadFile = File(...),
                         db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    """Recherche-Liste als CSV einlesen. Ohne Quelle kein Eintrag – geraten wird nichts.
    Gesperrte und schon vorhandene Organisationen werden übersprungen."""
    import csv as _csv
    import io
    import re
    import vertrieb
    roh = (await datei.read()).decode("utf-8-sig", errors="replace")
    trenner = ";" if roh.count(";") >= roh.count(",") else ","
    neu = uebersprungen = gesperrt = ohne_quelle = 0
    for zeile in _csv.DictReader(io.StringIO(roh), delimiter=trenner):
        werte = { (k or "").strip().lower(): (v or "").strip() for k, v in zeile.items() }

        def hol(*namen):
            for n in namen:
                if werte.get(n):
                    return werte[n]
            return ""

        firma = hol("organisation", "firma", "kunde", "name")
        quelle = hol("quelle", "quelle (link)", "link", "beleg")
        if not firma:
            continue
        if not quelle:
            ohne_quelle += 1
            continue
        # Kontaktweg enthält oft Mail UND Telefon in einer Zelle
        kontakt_roh = hol("mail", "e-mail", "email", "kontaktweg", "weg")
        treffer = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", kontakt_roh)
        mail = treffer.group(0).rstrip(".,;") if treffer else ""
        tel = re.search(r"0[\d/ ()\-]{6,}", kontakt_roh)
        darf, _grund = vertrieb.darf_kontaktieren(db, email=mail, firma=firma)
        if not darf:
            gesperrt += 1
            continue
        if db.query(Kunde).filter(func.lower(Kunde.firma) == firma.lower()).first():
            uebersprungen += 1
            continue
        # „3", „März" oder ein Bereich wie „Okt–Dez" (dann zählt der erste Monat)
        monat = hol("ansprachemonat", "monat").strip()
        zahl = int(monat) if monat.isdigit() and 1 <= int(monat) <= 12 else None
        if zahl is None:
            zahl = MONATE.get(monat.lower().replace("ä", "ä")[:3])
        db.add(Kunde(
            firma=firma, email=mail or None, telefon=(tel.group(0).strip() if tel else None),
            ort=hol("ort") or None,
            branche=hol("typ/spur", "typ", "branche", "spur") or None,
            quelle_beleg=(hol("beleg", "verlaesslichkeit", "verlässlichkeit") or "").lower() or None,
            herkunft="akquise", pipeline_status="lead",
            akquise_art=hol("art", "typ") or None, quelle=quelle,
            anlass=hol("veranstaltung", "anlass") or None, ansprachemonat=zahl,
            kontaktweg=hol("kontaktweg", "weg") or None,
            notizen=hol("warum passt das", "notiz", "begruendung") or None,
            erstellt_am=datetime.now().isoformat(timespec="seconds")))
        neu += 1
    db.commit()
    from urllib.parse import urlencode
    return RedirectResponse("/admin/crm/akquise?" + urlencode(
        {"neu": neu, "doppelt": uebersprungen, "gesperrt": gesperrt,
         "ohne_quelle": ohne_quelle}), status_code=303)


MONATE = {"jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12}


@router.post("/akquise/uebergeben")
def akquise_uebergeben(background_tasks: BackgroundTasks, kunde_ids: list = Form([]),
                       db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    """Ausgewählte Kontakte an den E-Mail-Assistenten übergeben, der daraus Entwürfe
    baut und sie nach Aykuts Freigabe über die eigene Vertriebsadresse verschickt.

    Hier wird entschieden, WER angeschrieben werden darf: Sperrliste, Not-Aus und
    Tageslimit. Der Assistent fragt vor dem Versand noch einmal nach (siehe
    /api/vertrieb/pruefen), damit eine Sperre auch zwischen Entwurf und Versand greift."""
    import vertrieb
    ids = {int(x) for x in kunde_ids if str(x).isdigit()}
    kontakte = db.query(Kunde).filter(Kunde.id.in_(ids)).all() if ids else []
    rest = vertrieb.rest_heute(db)
    uebergeben = gesperrt = ohne_mail = 0
    for k in kontakte:
        if uebergeben >= rest:
            break
        if not (k.email or "").strip():
            ohne_mail += 1
            continue
        darf, _grund = vertrieb.darf_kontaktieren(db, email=k.email, firma=k.firma)
        if not darf:
            gesperrt += 1
            continue
        background_tasks.add_task(entwurf_anfordern, k.id)
        uebergeben += 1
    from urllib.parse import urlencode
    return RedirectResponse("/admin/crm/akquise?" + urlencode(
        {"uebergeben": uebergeben, "gesperrt_u": gesperrt, "ohne_mail": ohne_mail,
         "limit": max(0, len(kontakte) - uebergeben - gesperrt - ohne_mail)}), status_code=303)


def entwurf_anfordern(kunde_id: int):
    """Hintergrund: Kontaktdaten an den Assistenten geben, der den Entwurf schreibt."""
    import json
    import urllib.request
    from database import SessionLocal
    cfg = get_config()
    url, secret = cfg.get("assistent_api_url"), cfg.get("assistent_api_secret")
    db = SessionLocal()
    try:
        k = db.query(Kunde).filter(Kunde.id == kunde_id).first()
        if not k:
            return
        if not url or not secret:
            print("[VERTRIEB] assistent_api_url/_secret fehlen – kein Entwurf angefordert")
            return
        daten = {"kunde_id": k.id, "firma": k.firma, "email": k.email, "ort": k.ort or "",
                 "branche": k.branche or "", "art": k.akquise_art or "",
                 "anlass": k.anlass or "", "quelle": k.quelle or "",
                 "ansprachemonat": k.ansprachemonat, "notiz": k.notizen or ""}
        req = urllib.request.Request(
            url.rstrip("/") + "/api/vertrieb/entwurf",
            data=json.dumps(daten).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Vertrieb-Secret": secret})
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        import vertrieb
        vertrieb.protokollieren(db, k, "entwurf", "An den E-Mail-Assistenten übergeben")
    except Exception as e:
        print(f"[VERTRIEB] Entwurf für Kunde {kunde_id} fehlgeschlagen: {e}")
    finally:
        db.close()


# ── Schnittstelle für den E-Mail-Assistenten (Secret im Header) ──────────────

def _assistent_erlaubt(request: Request) -> bool:
    secret = get_config().get("assistent_api_secret")
    return bool(secret) and request.headers.get("X-Vertrieb-Secret") == secret


@router.get("/api/vertrieb/pruefen")
def api_pruefen(request: Request, email: str = "", firma: str = "",
                db: Session = Depends(get_db)):
    """Der Assistent fragt unmittelbar VOR dem Versand: Darf ich? Antwort ist
    verbindlich, auch wenn der Entwurf längst geschrieben ist."""
    import vertrieb
    if not _assistent_erlaubt(request):
        raise HTTPException(401)
    darf, grund = vertrieb.darf_kontaktieren(db, email=email, firma=firma)
    rest = vertrieb.rest_heute(db)
    if darf and rest <= 0:
        # Entwürfe können tagelang liegen bleiben – ohne diese Prüfung gingen sie
        # später alle auf einmal raus und das Tageslimit wäre wirkungslos.
        darf, grund = False, (f"Tageslimit erreicht ({vertrieb.tageslimit(db)} Mails). "
                              "Morgen geht es weiter.")
    return {"darf": darf, "grund": grund, "rest_heute": rest}


@router.post("/api/vertrieb/gesendet")
async def api_gesendet(request: Request, db: Session = Depends(get_db)):
    """Der Assistent meldet: Mail ist raus. Wir protokollieren und rücken die
    Pipeline eine Stufe weiter."""
    import vertrieb
    if not _assistent_erlaubt(request):
        raise HTTPException(401)
    daten = await request.json()
    k = db.query(Kunde).filter(Kunde.id == daten.get("kunde_id")).first()
    if not k:
        raise HTTPException(404)
    vertrieb.protokollieren(db, k, "mail", daten.get("betreff") or "",
                            daten.get("empfaenger") or k.email or "")
    if k.pipeline_status == "lead":
        k.pipeline_status = "kontakt"
    db.commit()
    return {"ok": True, "rest_heute": vertrieb.rest_heute(db)}


@router.post("/api/vertrieb/sperren")
async def api_sperren(request: Request, db: Session = Depends(get_db)):
    """Der Assistent erkennt einen Widerspruch („bitte keine Mails mehr") und meldet
    ihn. Gesperrt wird auf allen Ebenen, nicht nur die eine Adresse."""
    import vertrieb
    if not _assistent_erlaubt(request):
        raise HTTPException(401)
    daten = await request.json()
    grund = daten.get("grund") or "widerspruch"
    k = (db.query(Kunde).filter(Kunde.id == daten["kunde_id"]).first()
         if daten.get("kunde_id") else None)
    if k:
        vertrieb.sperren_fuer_kunde(db, k, grund, daten.get("notiz") or "")
        k.pipeline_status = "verloren"
        db.commit()
    elif daten.get("email"):
        vertrieb.sperren(db, "adresse", daten["email"], grund, daten.get("notiz") or "")
    if grund in ("abmahnung", "unterlassung"):
        vertrieb.versand_stoppen(db, True)      # Not-Aus bei Anwaltspost
        from notifications import notify
        notify(db, "vertrieb_stopp", "Vertriebsversand gestoppt",
               "Der E-Mail-Assistent hat Anwaltspost gemeldet. Der automatische Versand "
               "steht still, bis du ihn unter Kunden → Akquise wieder freigibst.",
               "/admin/crm/akquise")
        db.commit()
    return {"ok": True, "gestoppt": vertrieb.versand_gestoppt(db)}


@router.post("/akquise/sperre")
def akquise_sperre(ebene: str = Form("adresse"), wert: str = Form(""),
                   grund: str = Form("widerspruch"), notiz: str = Form(""),
                   db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    import vertrieb
    vertrieb.sperren(db, ebene, wert, grund, notiz)
    return RedirectResponse("/admin/crm/akquise", status_code=303)


@router.post("/akquise/{kid}/sperren")
def akquise_kunde_sperren(kid: int, grund: str = Form("widerspruch"),
                          db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    """„Bitte nie wieder" – sperrt Adresse, Domain und Unternehmen zugleich."""
    import vertrieb
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if k:
        vertrieb.sperren_fuer_kunde(db, k, grund)
        k.pipeline_status = "verloren"
        db.commit()
    return RedirectResponse("/admin/crm/akquise", status_code=303)


@router.post("/akquise/limit")
def akquise_limit(limit: str = Form(""), db: Session = Depends(get_db), _=Depends(nur_inhaber)):
    """Tageslimit ändern. In der Aufwärmphase einer neuen Absenderadresse klein halten
    (erste Woche 5, dann 10), sonst fällt die Domain auf."""
    import vertrieb
    from notifications import set_setting
    wert = limit.strip()
    if wert.isdigit() and 1 <= int(wert) <= 500:
        set_setting(db, vertrieb.LIMIT_KEY, wert)
        db.commit()
    return RedirectResponse("/admin/crm/akquise", status_code=303)


@router.post("/akquise/notaus")
def akquise_notaus(stoppen: str = Form("1"), db: Session = Depends(get_db),
                   _=Depends(nur_inhaber)):
    import vertrieb
    vertrieb.versand_stoppen(db, stoppen == "1")
    return RedirectResponse("/admin/crm/akquise", status_code=303)


# ── Dashboard (handlungsorientiert) ──────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    from datetime import timedelta
    heute = date.today()
    grenze = heute - timedelta(days=30)

    # Offene Wiedervorlagen (mit zugehörigem Kunden – eager, sonst Query je Zeile im Template)
    wv = db.query(KundeWiedervorlage).options(
        joinedload(KundeWiedervorlage.kunde)).filter(KundeWiedervorlage.erledigt == False).all()  # noqa: E712
    wv_faellig = sorted([w for w in wv if w.faellig and w.faellig <= heute],
                        key=lambda w: w.faellig)
    wv_demnaechst = sorted([w for w in wv if w.faellig and w.faellig > heute],
                           key=lambda w: w.faellig)[:8]
    anzahl_ueberfaellig = sum(1 for w in wv if w.faellig and w.faellig < heute)

    # Letzte Aktivität je Kunde
    last_akt = dict(db.query(KundeAktivitaet.kunde_id, func.max(KundeAktivitaet.datum))
                    .group_by(KundeAktivitaet.kunde_id).all())

    # Angebote, die auf Rückmeldung warten
    angebote = db.query(Kunde).filter(Kunde.pipeline_status == "angebot").all()

    # Aktive Leads (frühe Pipeline-Stufen)
    aktive_leads = db.query(Kunde).filter(
        Kunde.pipeline_status.in_(["lead", "kontakt", "bedarf"])).count()

    # Kunden ohne Kontakt seit >30 Tagen (nur aktive Pipeline, nicht gebucht/verloren)
    aktive = db.query(Kunde).filter(
        Kunde.pipeline_status.in_(["lead", "kontakt", "bedarf", "angebot"])).all()
    ohne_kontakt = []
    for k in aktive:
        la = last_akt.get(k.id)
        if la is None or la < grenze:
            ohne_kontakt.append((k, la))
    ohne_kontakt.sort(key=lambda t: (t[1] is not None, t[1] or heute))
    ohne_kontakt = ohne_kontakt[:8]

    # Anstehende Events
    anstehend = db.query(Event).filter(Event.datum >= heute).order_by(Event.datum).limit(6).all()

    return templates.TemplateResponse("admin/crm_dashboard.html",
        tpl(request, active="crm",
            wv_faellig=wv_faellig, wv_demnaechst=wv_demnaechst,
            anzahl_ueberfaellig=anzahl_ueberfaellig, offene_wv=len(wv),
            angebote=angebote, aktive_leads=aktive_leads,
            ohne_kontakt=ohne_kontakt, anstehend=anstehend, last_akt=last_akt))


# ── Pipeline (Kanban) ────────────────────────────────────────────────────────

@router.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    kunden = db.query(Kunde).order_by(Kunde.pipeline_reihenfolge, func.lower(Kunde.firma)).all()
    spalten = {s: [] for s in KUNDE_STATUS}
    for k in kunden:
        spalten.get(k.pipeline_status, spalten["lead"]).append(k)
    counts = dict(db.query(Event.kunde_id, func.count(Event.id))
                  .filter(Event.kunde_id != None)  # noqa: E711
                  .group_by(Event.kunde_id).all())
    return templates.TemplateResponse("admin/crm_pipeline.html",
        tpl(request, active="crm", spalten=spalten, counts=counts))


@router.post("/{kid}/move")
def kunde_move(kid: int, status: str = Form(...), order: str = Form(""),
               db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Pipeline-Drag: Status ändern + Reihenfolge der Zielspalte setzen."""
    from fastapi.responses import JSONResponse
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        return JSONResponse({"ok": False}, status_code=404)
    if status in KUNDE_STATUS:
        k.pipeline_status = status
        k.aktualisiert_am = _now()
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    for i, oid in enumerate(ids):
        db.query(Kunde).filter(Kunde.id == oid).update({"pipeline_reihenfolge": i})
    db.commit()
    return JSONResponse({"ok": True})


# ── Detail ───────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
def kunde_new(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/crm_kunde_form.html",
        tpl(request, active="crm", kunde=None, error=None))


@router.post("/new")
async def kunde_create(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    raw = await request.form()
    form = dict(raw)
    if not form.get("firma", "").strip():
        return templates.TemplateResponse("admin/crm_kunde_form.html",
            tpl(request, active="crm", kunde=_kunde_form_echo(raw),
                error="Firma / Name ist erforderlich."))
    k = Kunde(erstellt_am=_now())
    k.weitere_ansprechpartner = weitere_ap_json(
        raw.getlist("kap_name"), raw.getlist("kap_telefon"), raw.getlist("kap_email"))
    _apply_form(db, k, form)
    db.add(k); db.commit(); db.refresh(k)
    return RedirectResponse(f"/admin/crm/{k.id}", status_code=303)


@router.get("/{kid}", response_class=HTMLResponse)
def kunde_detail(request: Request, kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        raise HTTPException(404)
    events = db.query(Event).filter(Event.kunde_id == kid).order_by(Event.datum.desc()).all()
    berichte = [ev for ev in events if ev.bericht_eingereicht_am]
    wv_offen = [w for w in k.wiedervorlagen if not w.erledigt]
    wv_erledigt = [w for w in k.wiedervorlagen if w.erledigt]
    return templates.TemplateResponse("admin/crm_kunde_detail.html",
        tpl(request, active="crm", kunde=k, events=events, berichte=berichte,
            wv_offen=wv_offen, wv_erledigt=wv_erledigt))


@router.get("/{kid}/edit", response_class=HTMLResponse)
def kunde_edit(request: Request, kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        raise HTTPException(404)
    return templates.TemplateResponse("admin/crm_kunde_form.html",
        tpl(request, active="crm", kunde=k, error=None))


@router.post("/{kid}/edit")
async def kunde_update(request: Request, kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        raise HTTPException(404)
    raw = await request.form()
    form = dict(raw)
    if not form.get("firma", "").strip():
        return templates.TemplateResponse("admin/crm_kunde_form.html",
            tpl(request, active="crm", kunde=_kunde_form_echo(raw, k),
                error="Firma / Name ist erforderlich."))
    k.weitere_ansprechpartner = weitere_ap_json(
        raw.getlist("kap_name"), raw.getlist("kap_telefon"), raw.getlist("kap_email"))
    _apply_form(db, k, form)
    db.commit()
    return RedirectResponse(f"/admin/crm/{kid}", status_code=303)


@router.post("/{kid}/delete")
def kunde_delete(kid: int, db: Session = Depends(get_db), user=Depends(nur_inhaber)):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if k:
        from papierkorb import archive_kunde
        archive_kunde(db, k, user.get("sub") or user.get("email"))  # Notfall-Sicherung (inkl. Aktivitäten/Wiedervorlagen)
        # Events bleiben erhalten, nur die Verknüpfung wird gelöst.
        for ev in db.query(Event).filter(Event.kunde_id == kid).all():
            ev.kunde_id = None
        db.delete(k); db.commit()
    return RedirectResponse("/admin/crm", status_code=303)


# ── Aktivitäten ──────────────────────────────────────────────────────────────

@router.post("/{kid}/aktivitaet")
def aktivitaet_add(kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
                   typ: str = Form("notiz"), datum: str = Form(""), notiz: str = Form("")):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        raise HTTPException(404)
    if (notiz or "").strip():
        db.add(KundeAktivitaet(
            kunde_id=kid,
            typ=typ if typ in AKTIVITAET_TYPEN else "notiz",
            datum=_parse_date(datum) or date.today(),
            notiz=notiz.strip(),
            erstellt_am=_now(),
        ))
        db.commit()
    return RedirectResponse(f"/admin/crm/{kid}#aktivitaeten", status_code=303)


@router.post("/{kid}/aktivitaet/{aid}/delete")
def aktivitaet_delete(kid: int, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(KundeAktivitaet).filter(
        KundeAktivitaet.id == aid, KundeAktivitaet.kunde_id == kid).first()
    if a:
        db.delete(a); db.commit()
    return RedirectResponse(f"/admin/crm/{kid}#aktivitaeten", status_code=303)


# ── Wiedervorlagen ───────────────────────────────────────────────────────────

@router.post("/{kid}/wiedervorlage")
def wiedervorlage_add(kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
                      titel: str = Form(""), faellig: str = Form(""),
                      prioritaet: str = Form("mittel")):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if not k:
        raise HTTPException(404)
    if (titel or "").strip():
        db.add(KundeWiedervorlage(
            kunde_id=kid,
            titel=titel.strip(),
            faellig=_parse_date(faellig),
            prioritaet=prioritaet if prioritaet in PRIORITAET_LABEL else "mittel",
            erstellt_am=_now(),
        ))
        db.commit()
    return RedirectResponse(f"/admin/crm/{kid}#wiedervorlagen", status_code=303)


@router.post("/{kid}/wiedervorlage/{wid}/toggle")
def wiedervorlage_toggle(kid: int, wid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    w = db.query(KundeWiedervorlage).filter(
        KundeWiedervorlage.id == wid, KundeWiedervorlage.kunde_id == kid).first()
    if w:
        w.erledigt = not w.erledigt
        w.erledigt_am = _now() if w.erledigt else None
        db.commit()
    return RedirectResponse(f"/admin/crm/{kid}#wiedervorlagen", status_code=303)


@router.post("/{kid}/wiedervorlage/{wid}/delete")
def wiedervorlage_delete(kid: int, wid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    w = db.query(KundeWiedervorlage).filter(
        KundeWiedervorlage.id == wid, KundeWiedervorlage.kunde_id == kid).first()
    if w:
        db.delete(w); db.commit()
    return RedirectResponse(f"/admin/crm/{kid}#wiedervorlagen", status_code=303)
