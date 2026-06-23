"""Benachrichtigungen (Glocke / Aktivitäts-Feed) + App-Einstellungen (E-Mail-Schalter)."""
from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Benachrichtigung, Admin
from auth import get_admin_user
from config import get_config
from notifications import NOTIF_TYPEN, mail_enabled, set_mail_enabled

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

TYP_ICON = {"dl_zusage": "✅", "dl_absage": "❌", "dl_urlaub": "🌴",
            "checkliste": "📋", "bericht": "📝"}


def tpl_context(request: Request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


@router.get("/benachrichtigungen", response_class=HTMLResponse)
def benachrichtigungen(request: Request, db: Session = Depends(get_db), user=Depends(get_admin_user)):
    email = user.get("sub") or user.get("email")
    ad = db.query(Admin).filter(Admin.email == email).first()
    cutoff = ad.notifications_gesehen_bis if ad else None  # vor dem Markieren merken (für „neu")
    eintraege = db.query(Benachrichtigung).order_by(Benachrichtigung.id.desc()).limit(200).all()
    # Als gesehen markieren -> Badge dieses Admins auf 0
    if ad:
        ad.notifications_gesehen_bis = datetime.now().isoformat(timespec="seconds")
        db.commit()
    return templates.TemplateResponse("admin/benachrichtigungen.html",
        tpl_context(request, eintraege=eintraege, cutoff=cutoff, typ_icon=TYP_ICON,
                    active="benachrichtigungen"))


@router.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    schalter = [{"typ": t[0], "label": t[1], "on": mail_enabled(db, t[0])} for t in NOTIF_TYPEN]
    return templates.TemplateResponse("admin/einstellungen.html",
        tpl_context(request, schalter=schalter, active="einstellungen",
                    gespeichert=request.query_params.get("ok")))


@router.post("/einstellungen")
async def einstellungen_speichern(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    form = await request.form()
    for t in NOTIF_TYPEN:
        set_mail_enabled(db, t[0], form.get(f"mail_{t[0]}") == "1")
    db.commit()
    return RedirectResponse("/admin/einstellungen?ok=1", status_code=303)
