from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db
from models import Dienstleister, Verfuegbarkeitsanfrage, Event
from auth import get_portal_user, verify_password, create_token
from config import get_config

router = APIRouter(prefix="/portal")
templates = Jinja2Templates(directory="templates")

def tpl_context(request: Request, **kwargs):
    return {"request": request, "cfg": get_config(), **kwargs}


@router.get("/login", response_class=HTMLResponse)
def portal_login(request: Request):
    return templates.TemplateResponse("portal/login.html", tpl_context(request))

@router.post("/login")
def portal_login_post(request: Request, db: Session = Depends(get_db),
                      email: str = Form(...), password: str = Form(...)):
    d = db.query(Dienstleister).filter(Dienstleister.email == email).first()
    if not d or not d.password_hash or not verify_password(password, d.password_hash):
        return templates.TemplateResponse("portal/login.html",
            tpl_context(request, error="Ungültige Zugangsdaten"))
    token = create_token({"sub": str(d.id), "role": "dienstleister"})
    resp = RedirectResponse("/portal", status_code=303)
    resp.set_cookie("portal_token", token, httponly=True, max_age=60*60*24)
    return resp

@router.get("/logout")
def portal_logout():
    resp = RedirectResponse("/portal/login", status_code=303)
    resp.delete_cookie("portal_token")
    return resp

@router.get("", response_class=HTMLResponse)
def portal_dashboard(request: Request, db: Session = Depends(get_db),
                     user=Depends(get_portal_user)):
    did = int(user["sub"])
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()

    today = datetime.today()

    def parse_date(a):
        try:
            return datetime.strptime(a.event.datum, "%d.%m.%Y")
        except:
            return datetime.max

    anfragen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ausstehend"
    ).all()
    anfragen = sorted(anfragen, key=parse_date)

    confirmed = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.dienstleister_id == did,
        Verfuegbarkeitsanfrage.status == "Ja"
    ).all()

    upcoming = sorted([a for a in confirmed if parse_date(a) >= today], key=parse_date)
    past = sorted([a for a in confirmed if parse_date(a) < today], key=parse_date, reverse=True)

    return templates.TemplateResponse("portal/dashboard.html",
        tpl_context(request, dienstleister=d, anfragen=anfragen,
                    upcoming=upcoming, past=past))

@router.post("/antwort/{anfrage_id}")
def portal_antwort(anfrage_id: int, antwort: str = Form(...),
                   db: Session = Depends(get_db), user=Depends(get_portal_user)):
    did = int(user["sub"])
    a = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.id == anfrage_id,
        Verfuegbarkeitsanfrage.dienstleister_id == did
    ).first()
    if a and antwort in ("Ja", "Nein"):
        a.status = antwort
        db.commit()
    return RedirectResponse("/portal", status_code=303)
