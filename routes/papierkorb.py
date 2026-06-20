"""Papierkorb: Übersicht der gelöschten Datensätze, Wiederherstellen, Download als JSON,
endgültiges Entfernen aus der Sicherung."""
from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import GeloeschtesObjekt
from auth import get_admin_user
from config import get_config

router = APIRouter(prefix="/admin/papierkorb")
templates = Jinja2Templates(directory="templates")

TYP_LABEL = {"event": "Event", "dienstleister": "Dienstleister", "kunde": "Kunde"}


def tpl_context(request: Request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def papierkorb(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    eintraege = db.query(GeloeschtesObjekt).order_by(GeloeschtesObjekt.id.desc()).all()
    return templates.TemplateResponse("admin/papierkorb.html",
        tpl_context(request, eintraege=eintraege, typ_label=TYP_LABEL))


@router.get("/{eid}/download")
def papierkorb_download(eid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    e = db.query(GeloeschtesObjekt).filter(GeloeschtesObjekt.id == eid).first()
    if not e:
        raise HTTPException(404)
    fname = f"{e.typ}_{e.objekt_id}_{(e.geloescht_am or '')[:10]}.json"
    return Response(content=e.daten_json, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/{eid}/restore")
def papierkorb_restore(eid: int, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db), _=Depends(get_admin_user)):
    e = db.query(GeloeschtesObjekt).filter(GeloeschtesObjekt.id == eid).first()
    if not e:
        raise HTTPException(404)
    from papierkorb import restore as _restore
    try:
        fehler, sync_event_id = _restore(db, e)
    except Exception as ex:
        db.rollback()
        print(f"[PAPIERKORB-RESTORE FEHLER] {e.typ} {e.objekt_id}: {ex}")
        return RedirectResponse("/admin/papierkorb?error=restore", status_code=303)
    if fehler:
        db.rollback()
        return RedirectResponse(f"/admin/papierkorb?error=restore_msg&msg={fehler}", status_code=303)
    db.delete(e); db.commit()
    if sync_event_id:
        import calendar_service
        background_tasks.add_task(calendar_service.sync_event_async, sync_event_id)
    return RedirectResponse("/admin/papierkorb?ok=restored", status_code=303)


@router.post("/{eid}/entfernen")
def papierkorb_entfernen(eid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    e = db.query(GeloeschtesObjekt).filter(GeloeschtesObjekt.id == eid).first()
    if e:
        db.delete(e); db.commit()
    return RedirectResponse("/admin/papierkorb?ok=entfernt", status_code=303)
