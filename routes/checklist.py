from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from database import get_db
from models import Event
from config import get_config
from choices import ZEITEN, de_date

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.globals["zeiten"] = ZEITEN


@router.get("/checklist/{token}", response_class=HTMLResponse)
def checklist_show(token: str, request: Request, db: Session = Depends(get_db)):
    ev = db.query(Event).filter(Event.checklist_token == token).first()
    if not ev:
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Link ungültig oder abgelaufen.</p>", status_code=404)

    already_submitted = bool(ev.cl_eingereicht_am)
    return templates.TemplateResponse("checklist.html", {
        "request": request,
        "ev": ev,
        "already_submitted": already_submitted,
        "cfg": get_config(),
    })


@router.post("/checklist/{token}", response_class=HTMLResponse)
def checklist_submit(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    ansprechpartner_name:  str = Form(""),
    ansprechpartner_mobil: str = Form(""),
    firma_name:            str = Form(""),
    strasse:               str = Form(""),
    plz_ort:               str = Form(""),
    aufbau_von:            str = Form(""),
    aufbau_bis:            str = Form(""),
    abbau_von:             str = Form(""),
    abbau_bis:             str = Form(""),
    aufbauort:             list = Form([]),
    verpflegung:           str = Form("Nein"),
    teamkleidung:          str = Form("Nein"),
    parkplatz:             str = Form(""),
):
    ev = db.query(Event).filter(Event.checklist_token == token).first()
    if not ev:
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Link ungültig.</p>", status_code=404)

    ev.cl_ansprechpartner_name  = ansprechpartner_name
    ev.cl_ansprechpartner_mobil = ansprechpartner_mobil
    ev.cl_firma_name            = firma_name
    ev.cl_strasse               = strasse
    ev.cl_plz_ort               = plz_ort
    ev.cl_aufbau_von            = aufbau_von
    ev.cl_aufbau_bis            = aufbau_bis
    ev.cl_abbau_von             = abbau_von
    ev.cl_abbau_bis             = abbau_bis
    ev.cl_aufbauort             = ", ".join(aufbauort)
    ev.cl_verpflegung           = verpflegung
    ev.cl_teamkleidung          = teamkleidung
    ev.cl_parkplatz             = parkplatz
    ev.cl_eingereicht_am        = datetime.now().strftime("%d.%m.%Y %H:%M")
    db.commit()
    # Status automatisch aktualisieren
    from routes.admin import auto_status
    ev.status = auto_status(ev, db)
    db.commit()

    # Admin-Benachrichtigung
    from email_service import send_checklist_notification
    cfg = get_config()
    base_url = str(request.base_url).rstrip("/")
    send_checklist_notification(ev, cfg["admin_email"], base_url)

    return templates.TemplateResponse("checklist.html", {
        "request": request,
        "ev": ev,
        "already_submitted": True,
        "cfg": get_config(),
    })
