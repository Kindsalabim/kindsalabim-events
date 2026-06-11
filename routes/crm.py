"""Customer-Management (CRM).

Stufe 1: Kundenprofile (Stammdaten, Profil-Wissen, Tags) + Eventhistorie
inkl. der vom Teamleiter eingereichten Eventberichte. Pipeline-Kanban,
Aktivitäten und Wiedervorlagen folgen in späteren Stufen.
"""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, date

from database import get_db
from models import (Kunde, KundeTag, Event, KUNDE_STATUS,
                    KundeAktivitaet, KundeWiedervorlage)
from auth import get_admin_user
from config import get_config
from choices import de_date

router = APIRouter(prefix="/admin/crm")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date

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


def _apply_form(db, k: Kunde, f: dict):
    def g(key):
        return (f.get(key) or "").strip()
    k.firma = g("firma")
    k.ansprechpartner = g("ansprechpartner") or None
    k.telefon = g("telefon") or None
    k.email = g("email") or None
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
    q = db.query(Kunde)
    if status in KUNDE_STATUS:
        q = q.filter(Kunde.pipeline_status == status)
    if tag:
        q = q.filter(Kunde.tags.any(KundeTag.name == tag))
    kunden = q.order_by(func.lower(Kunde.firma)).all()
    # Event-Anzahl je Kunde (eine Aggregat-Query statt N+1)
    counts = dict(db.query(Event.kunde_id, func.count(Event.id))
                  .filter(Event.kunde_id != None)  # noqa: E711
                  .group_by(Event.kunde_id).all())
    alle_tags = db.query(KundeTag).order_by(func.lower(KundeTag.name)).all()
    return templates.TemplateResponse("admin/crm_kunden.html",
        tpl(request, active="crm", kunden=kunden, counts=counts,
            alle_tags=alle_tags, filter_tag=tag, filter_status=status))


# ── Dashboard (handlungsorientiert) ──────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    from datetime import timedelta
    heute = date.today()
    grenze = heute - timedelta(days=30)

    # Offene Wiedervorlagen (mit zugehörigem Kunden)
    wv = db.query(KundeWiedervorlage).filter(KundeWiedervorlage.erledigt == False).all()  # noqa: E712
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
    form = dict(await request.form())
    if not form.get("firma", "").strip():
        return templates.TemplateResponse("admin/crm_kunde_form.html",
            tpl(request, active="crm", kunde=None, error="Firma / Name ist erforderlich."))
    k = Kunde(erstellt_am=_now())
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
    form = dict(await request.form())
    if not form.get("firma", "").strip():
        return templates.TemplateResponse("admin/crm_kunde_form.html",
            tpl(request, active="crm", kunde=k, error="Firma / Name ist erforderlich."))
    _apply_form(db, k, form)
    db.commit()
    return RedirectResponse(f"/admin/crm/{kid}", status_code=303)


@router.post("/{kid}/delete")
def kunde_delete(kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    k = db.query(Kunde).filter(Kunde.id == kid).first()
    if k:
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
