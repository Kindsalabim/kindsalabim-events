from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
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
    """Markdown -> sicheres HTML (gegen XSS gehärtet)."""
    raw = md.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return bleach.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def tpl_context(request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


# ── Admin ────────────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/admin/wissen")


@admin_router.get("", response_class=HTMLResponse)
def wissen_list(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    artikel = db.query(Wissensartikel).order_by(
        Wissensartikel.kategorie, Wissensartikel.sortierung, Wissensartikel.titel).all()
    # nach Kategorie gruppieren
    gruppen = {}
    for a in artikel:
        gruppen.setdefault(a.kategorie or "Allgemein", []).append(a)
    return templates.TemplateResponse("admin/wissen_list.html",
        tpl_context(request, gruppen=gruppen, anzahl=len(artikel)))


@admin_router.get("/new", response_class=HTMLResponse)
def wissen_new(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    kategorien = [k[0] for k in db.query(Wissensartikel.kategorie).distinct().all() if k[0]]
    return templates.TemplateResponse("admin/wissen_form.html",
        tpl_context(request, a=None, kategorien=kategorien))


@admin_router.post("/new")
def wissen_create(
    request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), inhalt: str = Form(""),
    kategorie: str = Form("Allgemein"), sichtbarkeit: str = Form("beide"),
    veroeffentlicht: bool = Form(False), sortierung: int = Form(0),
):
    now = datetime.now().isoformat(timespec="seconds")
    a = Wissensartikel(
        titel=titel.strip(), inhalt=inhalt,
        kategorie=kategorie.strip() or "Allgemein",
        sichtbarkeit=sichtbarkeit if sichtbarkeit in ("admin", "dienstleister", "beide") else "beide",
        veroeffentlicht=veroeffentlicht, sortierung=sortierung,
        erstellt_am=now, aktualisiert_am=now,
    )
    db.add(a); db.commit()
    return RedirectResponse("/admin/wissen", status_code=303)


@admin_router.get("/{aid}/edit", response_class=HTMLResponse)
def wissen_edit(request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    kategorien = [k[0] for k in db.query(Wissensartikel.kategorie).distinct().all() if k[0]]
    return templates.TemplateResponse("admin/wissen_form.html",
        tpl_context(request, a=a, kategorien=kategorien))


@admin_router.post("/{aid}/edit")
def wissen_update(
    request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), inhalt: str = Form(""),
    kategorie: str = Form("Allgemein"), sichtbarkeit: str = Form("beide"),
    veroeffentlicht: bool = Form(False), sortierung: int = Form(0),
):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    a.titel = titel.strip(); a.inhalt = inhalt
    a.kategorie = kategorie.strip() or "Allgemein"
    a.sichtbarkeit = sichtbarkeit if sichtbarkeit in ("admin", "dienstleister", "beide") else "beide"
    a.veroeffentlicht = veroeffentlicht; a.sortierung = sortierung
    a.aktualisiert_am = datetime.now().isoformat(timespec="seconds")
    db.commit()
    return RedirectResponse("/admin/wissen", status_code=303)


@admin_router.post("/{aid}/delete")
def wissen_delete(aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if a: db.delete(a); db.commit()
    return RedirectResponse("/admin/wissen", status_code=303)


@admin_router.get("/{aid}", response_class=HTMLResponse)
def wissen_detail_admin(request: Request, aid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    a = db.query(Wissensartikel).filter(Wissensartikel.id == aid).first()
    if not a: raise HTTPException(404)
    return templates.TemplateResponse("admin/wissen_detail.html",
        tpl_context(request, a=a, inhalt_html=render_markdown(a.inhalt)))


# ── Portal (Dienstleister) ─────────────────────────────────────────────────────

portal_router = APIRouter(prefix="/portal/wissen")


def _portal_filter(q):
    """Nur veröffentlichte Artikel für Dienstleister sichtbar."""
    return q.filter(
        Wissensartikel.veroeffentlicht == True,
        Wissensartikel.sichtbarkeit.in_(("dienstleister", "beide")),
    )


@portal_router.get("", response_class=HTMLResponse)
def portal_wissen_list(request: Request, db: Session = Depends(get_db), user=Depends(get_portal_user)):
    d = db.query(Dienstleister).filter(Dienstleister.id == int(user["sub"])).first()
    artikel = _portal_filter(db.query(Wissensartikel)).order_by(
        Wissensartikel.kategorie, Wissensartikel.sortierung, Wissensartikel.titel).all()
    gruppen = {}
    for a in artikel:
        gruppen.setdefault(a.kategorie or "Allgemein", []).append(a)
    return templates.TemplateResponse("portal/wissen_list.html",
        tpl_context(request, gruppen=gruppen, dienstleister=d))


@portal_router.get("/{aid}", response_class=HTMLResponse)
def portal_wissen_detail(request: Request, aid: int, db: Session = Depends(get_db), user=Depends(get_portal_user)):
    # Harte Filterung: Admin-only Artikel sind hier nie ladbar
    a = _portal_filter(db.query(Wissensartikel).filter(Wissensartikel.id == aid)).first()
    if not a:
        return RedirectResponse("/portal/wissen", status_code=303)
    return templates.TemplateResponse("portal/wissen_detail.html",
        tpl_context(request, a=a, inhalt_html=render_markdown(a.inhalt)))
