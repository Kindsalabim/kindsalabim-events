from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import json
from pathlib import Path
import markdown as md
import bleach

from database import get_db
from models import Wissensartikel, Dienstleister
from auth import get_admin_user, get_portal_user
from config import get_config

templates = Jinja2Templates(directory="templates")

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "hr", "br",
    "img", "table", "thead", "tbody", "tr", "th", "td", "span", "div",
]
ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width"],
}


def render_markdown(text: str) -> str:
    raw = md.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return bleach.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def tpl_context(request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


def breadcrumb(db, artikel):
    """Liste vom Wurzel-Element bis zum aktuellen (für Brotkrümel-Navigation)."""
    chain = []
    cur = artikel
    seen = set()
    while cur and cur.id not in seen:
        seen.add(cur.id)
        chain.insert(0, cur)
        cur = db.query(Wissensartikel).filter(Wissensartikel.id == cur.parent_id).first() if cur.parent_id else None
    return chain


# ── Admin ────────────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/admin/wissen")


@admin_router.get("", response_class=HTMLResponse)
def wissen_browse_root(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    kinder = db.query(Wissensartikel).filter(Wissensartikel.parent_id == None).order_by(
        Wissensartikel.sortierung, Wissensartikel.titel).all()
    gesamt = db.query(Wissensartikel).count()
    return templates.TemplateResponse("admin/wissen_browse.html",
        tpl_context(request, aktuell=None, kinder=kinder, pfad=[], inhalt_html=None, gesamt=gesamt))


@admin_router.get("/b/{aid}", response_class=HTMLResponse)
def wissen_browse(request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    kinder = db.query(Wissensartikel).filter(Wissensartikel.parent_id == aid).order_by(
        Wissensartikel.sortierung, Wissensartikel.titel).all()
    return templates.TemplateResponse("admin/wissen_browse.html",
        tpl_context(request, aktuell=a, kinder=kinder, pfad=breadcrumb(db, a),
                    inhalt_html=render_markdown(a.inhalt) if a.inhalt else None, gesamt=None))


def _alle_als_parent_optionen(db):
    return db.query(Wissensartikel).order_by(Wissensartikel.titel).all()


@admin_router.get("/new", response_class=HTMLResponse)
def wissen_new(request: Request, parent: int = 0, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/wissen_form.html",
        tpl_context(request, a=None, parent_vorauswahl=parent or None,
                    alle=_alle_als_parent_optionen(db)))


@admin_router.post("/new")
def wissen_create(
    request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), inhalt: str = Form(""),
    parent_id: str = Form(""), sichtbarkeit: str = Form("beide"),
    veroeffentlicht: bool = Form(False), sortierung: int = Form(0),
    cover_bild: str = Form(""),
):
    now = datetime.now().isoformat(timespec="seconds")
    a = Wissensartikel(
        titel=titel.strip(), inhalt=inhalt,
        parent_id=int(parent_id) if parent_id.strip().isdigit() else None,
        sichtbarkeit=sichtbarkeit if sichtbarkeit in ("admin", "dienstleister", "beide") else "beide",
        veroeffentlicht=veroeffentlicht, sortierung=sortierung,
        cover_bild=cover_bild.strip() or None,
        erstellt_am=now, aktualisiert_am=now,
    )
    db.add(a); db.commit()
    ziel = f"/admin/wissen/b/{a.parent_id}" if a.parent_id else "/admin/wissen"
    return RedirectResponse(ziel, status_code=303)


@admin_router.get("/{aid}/edit", response_class=HTMLResponse)
def wissen_edit(request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    return templates.TemplateResponse("admin/wissen_form.html",
        tpl_context(request, a=a, parent_vorauswahl=a.parent_id,
                    alle=[x for x in _alle_als_parent_optionen(db) if x.id != aid]))


@admin_router.post("/{aid}/edit")
def wissen_update(
    request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), inhalt: str = Form(""),
    parent_id: str = Form(""), sichtbarkeit: str = Form("beide"),
    veroeffentlicht: bool = Form(False), sortierung: int = Form(0),
    cover_bild: str = Form(""),
):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    a.titel = titel.strip(); a.inhalt = inhalt
    a.parent_id = int(parent_id) if parent_id.strip().isdigit() else None
    a.sichtbarkeit = sichtbarkeit if sichtbarkeit in ("admin", "dienstleister", "beide") else "beide"
    a.veroeffentlicht = veroeffentlicht; a.sortierung = sortierung
    a.cover_bild = cover_bild.strip() or None
    a.aktualisiert_am = datetime.now().isoformat(timespec="seconds")
    db.commit()
    ziel = f"/admin/wissen/b/{a.parent_id}" if a.parent_id else "/admin/wissen"
    return RedirectResponse(ziel, status_code=303)


@admin_router.post("/{aid}/delete")
def wissen_delete(aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    parent = a.parent_id if a else None
    if a: db.delete(a); db.commit()
    return RedirectResponse(f"/admin/wissen/b/{parent}" if parent else "/admin/wissen", status_code=303)


@admin_router.post("/sichtbarkeit/{aid}")
def wissen_set_sichtbarkeit(aid: int, sichtbarkeit: str = Form(...),
                            db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Schnell-Umschalter inkl. aller Unterseiten."""
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    if sichtbarkeit not in ("admin", "dienstleister", "beide"):
        sichtbarkeit = "admin"
    # rekursiv auf alle Nachfahren anwenden
    stapel = [a]
    while stapel:
        cur = stapel.pop()
        cur.sichtbarkeit = sichtbarkeit
        stapel.extend(db.query(Wissensartikel).filter(Wissensartikel.parent_id == cur.id).all())
    db.commit()
    return RedirectResponse(f"/admin/wissen/b/{aid}", status_code=303)


# ── Einmaliger Confluence-Import (aus wissen_seed.json) ───────────────────────

@admin_router.post("/import-seed")
def wissen_import_seed(db: Session = Depends(get_db), _=Depends(get_admin_user)):
    if db.query(Wissensartikel).count() > 0:
        return RedirectResponse("/admin/wissen?fehler=nicht_leer", status_code=303)
    seed_path = Path(__file__).parent.parent / "wissen_seed.json"
    if not seed_path.exists():
        return RedirectResponse("/admin/wissen?fehler=kein_seed", status_code=303)
    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    # Wurzel (parent_id None) ermitteln – deren Kinder werden Top-Level
    root_pid = next((s["page_id"] for s in seed if s["parent_id"] is None), None)
    now = datetime.now().isoformat(timespec="seconds")
    pid_to_db = {}

    # Pass 1: alle außer Wurzel anlegen
    for s in seed:
        if s["page_id"] == root_pid:
            continue
        a = Wissensartikel(
            titel=s["title"], inhalt=s.get("inhalt") or "",
            sichtbarkeit="admin",          # sicherer Default – nichts an Dienstleister geleakt
            veroeffentlicht=True,
            sortierung=s.get("order", 0),
            cover_bild=s.get("cover_bild"),
            erstellt_am=now, aktualisiert_am=now,
        )
        db.add(a); db.flush()
        pid_to_db[s["page_id"]] = a.id

    # Pass 2: Eltern verknüpfen (Kinder der Wurzel bleiben Top-Level)
    for s in seed:
        if s["page_id"] == root_pid or s["page_id"] not in pid_to_db:
            continue
        ppid = s["parent_id"]
        if ppid and ppid != root_pid and ppid in pid_to_db:
            db.query(Wissensartikel).filter(Wissensartikel.id == pid_to_db[s["page_id"]]).update(
                {"parent_id": pid_to_db[ppid]})
    db.commit()
    return RedirectResponse("/admin/wissen?import=ok", status_code=303)


# ── Portal (Dienstleister) ─────────────────────────────────────────────────────

portal_router = APIRouter(prefix="/portal/wissen")


def _portal_filter(q):
    return q.filter(
        Wissensartikel.veroeffentlicht == True,
        Wissensartikel.sichtbarkeit.in_(("dienstleister", "beide")),
    )


@portal_router.get("", response_class=HTMLResponse)
def portal_wissen_root(request: Request, db: Session = Depends(get_db), user=Depends(get_portal_user)):
    kinder = _portal_filter(db.query(Wissensartikel).filter(Wissensartikel.parent_id == None)).order_by(
        Wissensartikel.sortierung, Wissensartikel.titel).all()
    return templates.TemplateResponse("portal/wissen_browse.html",
        tpl_context(request, aktuell=None, kinder=kinder, pfad=[], inhalt_html=None))


@portal_router.get("/{aid}", response_class=HTMLResponse)
def portal_wissen_node(request: Request, aid: int, db: Session = Depends(get_db), user=Depends(get_portal_user)):
    a = _portal_filter(db.query(Wissensartikel).filter(Wissensartikel.id == aid)).first()
    if not a:
        return RedirectResponse("/portal/wissen", status_code=303)
    kinder = _portal_filter(db.query(Wissensartikel).filter(Wissensartikel.parent_id == aid)).order_by(
        Wissensartikel.sortierung, Wissensartikel.titel).all()
    # Brotkrümel nur über sichtbare Vorfahren
    pfad = [x for x in breadcrumb(db, a) if x.veroeffentlicht and x.sichtbarkeit in ("dienstleister", "beide")]
    return templates.TemplateResponse("portal/wissen_browse.html",
        tpl_context(request, aktuell=a, kinder=kinder, pfad=pfad,
                    inhalt_html=render_markdown(a.inhalt) if a.inhalt else None))
