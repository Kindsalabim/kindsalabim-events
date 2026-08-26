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
from models import BastelProdukt, Bastelvorschlag, Event, Reservierung
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


def _reservierungen_liste(db: Session):
    """Offene Reservierungen als Andock-Ziel – Recherche läuft oft schon vor der Buchung."""
    return db.query(Reservierung).filter(
        Reservierung.datum >= date.today()).order_by(Reservierung.datum).limit(50).all()


def _ziel_event(db: Session, event_id):
    if not event_id:
        return None
    return db.query(Event).filter(Event.id == event_id).first()


def _ziel_reservierung(db: Session, reservierung_id):
    if not reservierung_id:
        return None
    return db.query(Reservierung).filter(Reservierung.id == reservierung_id).first()


def _suche_key(user) -> str:
    """Speicher-Schlüssel je Admin – jeder hat seine eigene letzte Recherche."""
    email = ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()
    return f"bakerross_suche:{email}"


def _suche_speichern(db, user, query, faktor, max_results, event_id, treffer,
                     reservierung_id=None):
    """Merkt sich die letzte Recherche, damit sie nach einem Seitenwechsel noch da ist.
    Gespeichert werden nur IDs + Preis-Snapshot – kein erneuter KI-Aufruf beim Laden."""
    from notifications import set_setting
    import json
    daten = {
        "query": query, "faktor": faktor, "max_results": max_results,
        "event_id": event_id, "reservierung_id": reservierung_id,
        "zeit": datetime.now().isoformat(timespec="seconds"),
        "treffer": [{"id": t["produkt"].id, "grund": t.get("grund") or "",
                     "br_preis": t.get("br_preis"), "stueckzahl": t.get("stueckzahl"),
                     "kundenpreis": t.get("kundenpreis")} for t in treffer],
    }
    try:
        set_setting(db, _suche_key(user), json.dumps(daten))
        db.commit()
    except Exception as e:      # Merken ist Komfort – darf die Suche nie sprengen
        db.rollback()
        print(f"Bastel-Recherche konnte nicht gemerkt werden: {e}")


def _suche_laden(db, user):
    """Letzte Recherche wiederherstellen → (daten, treffer) oder (None, None)."""
    from notifications import get_setting
    import json
    roh = get_setting(db, _suche_key(user), "")
    if not roh:
        return None, None
    try:
        daten = json.loads(roh)
    except (ValueError, TypeError):
        return None, None
    ids = [t.get("id") for t in daten.get("treffer", []) if t.get("id")]
    if not ids:
        return None, None
    produkte = {p.id: p for p in db.query(BastelProdukt).filter(BastelProdukt.id.in_(ids)).all()}
    treffer = []
    for t in daten["treffer"]:
        p = produkte.get(t.get("id"))
        if not p:
            continue        # Produkt inzwischen aus dem Katalog geflogen
        treffer.append({"produkt": p, "br_preis": t.get("br_preis"),
                        "stueckzahl": t.get("stueckzahl"),
                        "kundenpreis": t.get("kundenpreis"), "grund": t.get("grund") or ""})
    return (daten, treffer) if treffer else (None, None)


def tpl(request, **kw):
    ctx = {"request": request, "cfg": get_config(), "active": "bakerross",
           "heute": date.today(), "ki_an": br.ki_verfuegbar(),
           "faktor_default": _faktor_default()}
    ctx.update(kw)
    return ctx


@router.get("", response_class=HTMLResponse)
def index(request: Request, event_id: int = None, reservierung_id: int = None,
          db: Session = Depends(get_db), user=Depends(get_admin_user)):
    # Letzte Recherche wiederherstellen – sonst wäre sie nach einem Ausflug ins
    # Dashboard weg und müsste komplett neu gemacht werden.
    daten, treffer = _suche_laden(db, user)
    query = (daten or {}).get("query", "")
    faktor = (daten or {}).get("faktor") or _faktor_default()
    if event_id is None and reservierung_id is None and daten:
        event_id = daten.get("event_id")
        reservierung_id = daten.get("reservierung_id")
    return templates.TemplateResponse("admin/bakerross.html", tpl(
        request, status=_katalog_status(db), events=_events_liste(db),
        reservierungen=_reservierungen_liste(db),
        event_id=event_id, ziel_event=_ziel_event(db, event_id),
        reservierung_id=reservierung_id,
        ziel_reservierung=_ziel_reservierung(db, reservierung_id),
        treffer=treffer, query=query, faktor=faktor,
        gemerkt_seit=(daten or {}).get("zeit")))


@router.post("/suche", response_class=HTMLResponse)
def suche(request: Request, query: str = Form(...), faktor: float = Form(None),
          max_results: int = Form(12), event_id: int = Form(None),
          reservierung_id: int = Form(None),
          db: Session = Depends(get_db), user=Depends(get_admin_user)):
    faktor = faktor or _faktor_default()
    max_results = max(1, min(max_results, 24))
    treffer = br.kurate(db, query.strip(), max_results=max_results, faktor=faktor)
    _suche_speichern(db, user, query.strip(), faktor, max_results, event_id, treffer,
                     reservierung_id)
    return templates.TemplateResponse("admin/bakerross.html", tpl(
        request, status=_katalog_status(db), events=_events_liste(db),
        reservierungen=_reservierungen_liste(db),
        event_id=event_id, ziel_event=_ziel_event(db, event_id),
        reservierung_id=reservierung_id,
        ziel_reservierung=_ziel_reservierung(db, reservierung_id),
        treffer=treffer, query=query, faktor=faktor))


@router.post("/verwerfen")
def suche_verwerfen(db: Session = Depends(get_db), user=Depends(get_admin_user)):
    """Gemerkte Recherche löschen (Knopf „Ergebnis verwerfen")."""
    from notifications import set_setting
    set_setting(db, _suche_key(user), "")
    db.commit()
    return RedirectResponse("/admin/bakerross", status_code=303)


@router.post("/an-event")
def an_event(event_id: str = Form(...), name: str = Form(...), url: str = Form(""),
             bild_url: str = Form(""), br_preis: float = Form(None),
             stueckzahl: int = Form(None), faktor: float = Form(None),
             grund: str = Form(""), db: Session = Depends(get_db),
             _=Depends(get_admin_user)):
    """Bastelset an ein Event ODER eine Reservierung andocken.
    Das Auswahlfeld liefert „e<id>" (Event) bzw. „r<id>" (Reservierung); eine reine
    Zahl bleibt aus Kompatibilität ein Event."""
    ziel = (event_id or "").strip()
    ist_reservierung = ziel.startswith("r")
    try:
        ziel_id = int(ziel[1:] if ziel[:1] in ("e", "r") else ziel)
    except ValueError:
        raise HTTPException(400, "Ungültiges Ziel")

    if ist_reservierung:
        res = db.query(Reservierung).filter(Reservierung.id == ziel_id).first()
        if not res:
            raise HTTPException(404)
        ziel_param = f"reservierung_id={res.id}"
        felder = {"reservierung_id": res.id}
    else:
        ev = db.query(Event).filter(Event.id == ziel_id).first()
        if not ev:
            raise HTTPException(404)
        ziel_param = f"event_id={ev.id}"
        felder = {"event_id": ev.id}

    faktor = faktor or _faktor_default()
    db.add(Bastelvorschlag(
        name=name.strip(), url=url.strip() or None,
        bild_url=bild_url.strip() or None,
        br_preis=br_preis, stueckzahl=stueckzahl,
        kundenpreis=br.compute_kundenpreis(br_preis, faktor, stueckzahl),
        begruendung=(grund or "").strip() or None,
        erstellt_am=datetime.now().isoformat(timespec="seconds"),
        **felder,
    ))
    db.commit()
    return RedirectResponse(f"/admin/bakerross?{ziel_param}&msg=Bastelset+angedockt",
                            status_code=303)


@router.get("/bild")
def bild_download(url: str, _=Depends(get_admin_user)):
    """Lädt ein BR-Produktbild herunter (Proxy mit Download-Header, damit der
    Klick zuverlässig speichert statt nur einen Tab zu öffnen)."""
    import httpx
    from urllib.parse import urlparse
    from fastapi.responses import StreamingResponse
    if not url.startswith("https://www.bakerross.de/"):
        raise HTTPException(400, "Nur Baker-Ross-Bilder erlaubt")
    try:
        r = httpx.get(url, headers={"User-Agent": br.USER_AGENT}, timeout=20,
                      follow_redirects=True)
        r.raise_for_status()
    except Exception:
        raise HTTPException(502, "Bild konnte nicht geladen werden")
    name = (urlparse(url).path.rsplit("/", 1)[-1] or "bastelset").split("?")[0]
    if "." not in name:
        name += ".jpg"
    return StreamingResponse(
        iter([r.content]),
        media_type=r.headers.get("content-type", "image/jpeg"),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/vorschlag/{vid}/delete")
def vorschlag_delete(vid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    v = db.query(Bastelvorschlag).filter(Bastelvorschlag.id == vid).first()
    if not v:
        raise HTTPException(404)
    eid = v.event_id
    db.delete(v)
    db.commit()
    return RedirectResponse(f"/admin/bakerross?event_id={eid}", status_code=303)


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
