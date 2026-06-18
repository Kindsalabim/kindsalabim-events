"""Baker-Ross-Recherche (Admin).

Admin gibt Motto/Saison ein → kuratierte Liste passender Bastelsets aus dem lokalen
Katalog (BastelProdukt) inkl. nachgeladenem BR-Preis und kalkuliertem Kundenpreis.
Treffer lassen sich an ein Event andocken (Bastelvorschlag). Quelle ist die offizielle
Sitemap; es wird nicht live via KI gescrapt (siehe bakerross_service / ingest_bakerross).
"""
from datetime import date, datetime

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import BastelProdukt, Bastelvorschlag, Event
from auth import get_admin_user
from config import get_config
from choices import de_date
import bakerross_service as br

router = APIRouter(prefix="/admin/bakerross")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date


def _faktor_default():
    try:
        return float(get_config().get("bakerross_markup_default", 2.5))
    except (TypeError, ValueError):
        return 2.5


def _katalog_status(db: Session):
    gesamt = db.query(BastelProdukt).filter(BastelProdukt.aktiv == True).count()  # noqa: E712
    letzter = db.query(BastelProdukt).order_by(
        BastelProdukt.aktualisiert_am.desc()).first()
    stand = None
    if letzter and letzter.aktualisiert_am:
        try:
            stand = date.fromisoformat(letzter.aktualisiert_am[:10])
        except ValueError:
            stand = None
    return {"gesamt": gesamt, "stand": stand}


def _events_liste(db: Session):
    return db.query(Event).order_by(Event.datum.desc()).limit(150).all()


def tpl(request, **kw):
    ctx = {"request": request, "cfg": get_config(), "active": "bakerross",
           "heute": date.today(), "ki_an": br.ki_verfuegbar(),
           "faktor_default": _faktor_default()}
    ctx.update(kw)
    return ctx


@router.get("", response_class=HTMLResponse)
def index(request: Request, event_id: int = None, db: Session = Depends(get_db),
          _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/bakerross.html", tpl(
        request, status=_katalog_status(db), events=_events_liste(db),
        event_id=event_id, treffer=None, query=""))


@router.post("/suche", response_class=HTMLResponse)
def suche(request: Request, query: str = Form(...), faktor: float = Form(None),
          max_results: int = Form(12), event_id: int = Form(None),
          db: Session = Depends(get_db), _=Depends(get_admin_user)):
    faktor = faktor or _faktor_default()
    max_results = max(1, min(max_results, 24))
    treffer = br.kurate(db, query.strip(), max_results=max_results, faktor=faktor)
    return templates.TemplateResponse("admin/bakerross.html", tpl(
        request, status=_katalog_status(db), events=_events_liste(db),
        event_id=event_id, treffer=treffer, query=query, faktor=faktor))


@router.post("/an-event")
def an_event(produkt_id: int = Form(...), event_id: int = Form(...),
             faktor: float = Form(None), grund: str = Form(""),
             db: Session = Depends(get_db), _=Depends(get_admin_user)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    p = db.query(BastelProdukt).filter(BastelProdukt.id == produkt_id).first()
    if not ev or not p:
        raise HTTPException(404)
    faktor = faktor or _faktor_default()
    br_preis = br.ensure_price(db, p)
    db.add(Bastelvorschlag(
        event_id=ev.id, name=p.name, url=p.url, bild_url=p.bild_url,
        br_preis=br_preis, kundenpreis=br.compute_kundenpreis(br_preis, faktor),
        begruendung=(grund or "").strip() or None,
        erstellt_am=datetime.now().isoformat(timespec="seconds"),
    ))
    db.commit()
    return RedirectResponse(f"/admin/events/{ev.id}#bastel", status_code=303)


@router.post("/vorschlag/{vid}/delete")
def vorschlag_delete(vid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    v = db.query(Bastelvorschlag).filter(Bastelvorschlag.id == vid).first()
    if not v:
        raise HTTPException(404)
    eid = v.event_id
    db.delete(v)
    db.commit()
    return RedirectResponse(f"/admin/events/{eid}#bastel", status_code=303)


@router.post("/refresh")
def refresh(db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Katalog manuell aus der Sitemap aktualisieren."""
    from ingest_bakerross import ingest_catalog
    try:
        result = ingest_catalog(db)
        msg = f"Katalog aktualisiert: {result['gesamt']} Produkte ({result['neu']} neu)."
    except Exception as e:
        msg = f"Aktualisierung fehlgeschlagen: {e}"
    return RedirectResponse(f"/admin/bakerross?msg={msg}", status_code=303)
