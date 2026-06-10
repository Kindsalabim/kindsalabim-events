from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import io, csv

from database import get_db
from models import Ticket, TicketKategorie, Sprint, TicketSubtask, TicketKommentar, Admin
from auth import get_admin_user
from config import get_config
from choices import de_date

router = APIRouter(prefix="/admin/tickets")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date

STATUS = ["todo", "doing", "done"]
STATUS_LABEL = {"todo": "Zu erledigen", "doing": "In Bearbeitung", "done": "Erledigt"}
WICHTIGKEIT = ["niedrig", "mittel", "hoch", "kritisch"]


def tpl(request, **kw):
    return {"request": request, "cfg": get_config(),
            "STATUS": STATUS, "STATUS_LABEL": STATUS_LABEL, "WICHTIGKEIT": WICHTIGKEIT, **kw}


def _date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s and s.strip() else None
    except ValueError:
        return None


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ── Board ────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def board(request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    aktiv = db.query(Sprint).filter(Sprint.status == "aktiv").first()
    spalten = {s: [] for s in STATUS}
    if aktiv:
        tks = db.query(Ticket).filter(Ticket.sprint_id == aktiv.id).order_by(
            Ticket.reihenfolge, Ticket.id).all()
        for t in tks:
            spalten.get(t.status, spalten["todo"]).append(t)
    backlog = db.query(Ticket).filter(Ticket.sprint_id == None).order_by(
        Ticket.reihenfolge, Ticket.id).all()
    sprints = db.query(Sprint).order_by(Sprint.id.desc()).all()
    kategorien = db.query(TicketKategorie).order_by(TicketKategorie.name).all()
    admins = db.query(Admin).order_by(Admin.email).all()
    return templates.TemplateResponse("admin/tickets_board.html",
        tpl(request, aktiv=aktiv, spalten=spalten, backlog=backlog,
            sprints=sprints, kategorien=kategorien, admins=admins))


# ── Ticket CRUD ──────────────────────────────────────────────────────────────

@router.post("/new")
def ticket_create(
    request: Request, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), beschreibung: str = Form(""),
    kategorie_id: str = Form(""), wichtigkeit: str = Form("mittel"),
    aufwand: str = Form(""), admin_id: str = Form(""),
    faellig: str = Form(""), sprint_id: str = Form(""),
):
    t = Ticket(
        titel=titel.strip(), beschreibung=beschreibung,
        kategorie_id=int(kategorie_id) if kategorie_id.isdigit() else None,
        wichtigkeit=wichtigkeit if wichtigkeit in WICHTIGKEIT else "mittel",
        aufwand=aufwand if aufwand in ("S", "M", "L", "XL") else None,
        admin_id=int(admin_id) if admin_id.isdigit() else None,
        faellig=_date(faellig),
        sprint_id=int(sprint_id) if sprint_id.isdigit() else None,
        status="todo", reihenfolge=0, erstellt_am=_now(), aktualisiert_am=_now(),
    )
    db.add(t); db.commit()
    return RedirectResponse("/admin/tickets", status_code=303)


@router.get("/{tid}", response_class=HTMLResponse)
def ticket_detail(request: Request, tid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if not t: raise HTTPException(404)
    kategorien = db.query(TicketKategorie).order_by(TicketKategorie.name).all()
    admins = db.query(Admin).order_by(Admin.email).all()
    sprints = db.query(Sprint).order_by(Sprint.id.desc()).all()
    return templates.TemplateResponse("admin/ticket_detail.html",
        tpl(request, t=t, kategorien=kategorien, admins=admins, sprints=sprints))


@router.post("/{tid}/edit")
def ticket_update(
    request: Request, tid: int, db: Session = Depends(get_db), _=Depends(get_admin_user),
    titel: str = Form(...), beschreibung: str = Form(""),
    kategorie_id: str = Form(""), wichtigkeit: str = Form("mittel"),
    aufwand: str = Form(""), admin_id: str = Form(""),
    faellig: str = Form(""), sprint_id: str = Form(""), status: str = Form("todo"),
):
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if not t: raise HTTPException(404)
    t.titel = titel.strip(); t.beschreibung = beschreibung
    t.kategorie_id = int(kategorie_id) if kategorie_id.isdigit() else None
    t.wichtigkeit = wichtigkeit if wichtigkeit in WICHTIGKEIT else "mittel"
    t.aufwand = aufwand if aufwand in ("S", "M", "L", "XL") else None
    t.admin_id = int(admin_id) if admin_id.isdigit() else None
    t.faellig = _date(faellig)
    t.sprint_id = int(sprint_id) if sprint_id.isdigit() else None
    t.status = status if status in STATUS else "todo"
    t.aktualisiert_am = _now()
    db.commit()
    return RedirectResponse("/admin/tickets", status_code=303)


@router.post("/{tid}/delete")
def ticket_delete(tid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if t: db.delete(t); db.commit()
    return RedirectResponse("/admin/tickets", status_code=303)


@router.post("/{tid}/move")
def ticket_move(tid: int, status: str = Form(...), order: str = Form(""),
                db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Kanban-Drag: Status ändern + Reihenfolge der Zielspalte setzen."""
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if not t:
        return JSONResponse({"ok": False}, status_code=404)
    if status in STATUS:
        t.status = status
        t.aktualisiert_am = _now()
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    for i, oid in enumerate(ids):
        db.query(Ticket).filter(Ticket.id == oid).update({"reihenfolge": i})
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/{tid}/sprint")
def ticket_to_sprint(tid: int, sprint_id: str = Form(""),
                     db: Session = Depends(get_db), _=Depends(get_admin_user)):
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if not t: raise HTTPException(404)
    t.sprint_id = int(sprint_id) if sprint_id.isdigit() else None
    if t.sprint_id:
        t.status = "todo"
    t.aktualisiert_am = _now()
    db.commit()
    return RedirectResponse("/admin/tickets", status_code=303)


# ── Subtasks ─────────────────────────────────────────────────────────────────

@router.post("/{tid}/subtask/new")
def subtask_new(tid: int, text: str = Form(...), db: Session = Depends(get_db), _=Depends(get_admin_user)):
    n = db.query(TicketSubtask).filter(TicketSubtask.ticket_id == tid).count()
    db.add(TicketSubtask(ticket_id=tid, text=text.strip(), reihenfolge=n))
    db.commit()
    return RedirectResponse(f"/admin/tickets/{tid}", status_code=303)


@router.post("/subtask/{sid}/toggle")
def subtask_toggle(sid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    s = db.query(TicketSubtask).filter(TicketSubtask.id == sid).first()
    if s:
        s.erledigt = not s.erledigt; db.commit()
        return RedirectResponse(f"/admin/tickets/{s.ticket_id}", status_code=303)
    return RedirectResponse("/admin/tickets", status_code=303)


@router.post("/subtask/{sid}/delete")
def subtask_delete(sid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    s = db.query(TicketSubtask).filter(TicketSubtask.id == sid).first()
    tid = s.ticket_id if s else None
    if s: db.delete(s); db.commit()
    return RedirectResponse(f"/admin/tickets/{tid}" if tid else "/admin/tickets", status_code=303)


# ── Kommentare ───────────────────────────────────────────────────────────────

@router.post("/{tid}/kommentar")
def kommentar_new(tid: int, text: str = Form(...),
                  db: Session = Depends(get_db), user=Depends(get_admin_user)):
    if text.strip():
        db.add(TicketKommentar(ticket_id=tid, text=text.strip(),
                               autor=user.get("sub"), erstellt_am=_now()))
        db.commit()
    return RedirectResponse(f"/admin/tickets/{tid}", status_code=303)


# ── Sprints ──────────────────────────────────────────────────────────────────

@router.post("/sprints/new")
def sprint_new(name: str = Form(...), start: str = Form(""), ende: str = Form(""),
               db: Session = Depends(get_db), _=Depends(get_admin_user)):
    sd = _date(start) or date.today()
    ed = _date(ende) or (sd + timedelta(days=7))
    db.add(Sprint(name=name.strip(), start_datum=sd, end_datum=ed,
                  status="geplant", erstellt_am=_now()))
    db.commit()
    return RedirectResponse("/admin/tickets?tab=sprints", status_code=303)


@router.post("/sprints/{sid}/activate")
def sprint_activate(sid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    # nur ein aktiver Sprint
    db.query(Sprint).filter(Sprint.status == "aktiv").update({"status": "geplant"})
    s = db.query(Sprint).filter(Sprint.id == sid).first()
    if s: s.status = "aktiv"
    db.commit()
    return RedirectResponse("/admin/tickets", status_code=303)


@router.post("/sprints/{sid}/close")
def sprint_close(sid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    s = db.query(Sprint).filter(Sprint.id == sid).first()
    if s:
        s.status = "abgeschlossen"
        # nicht erledigte Tickets zurück in den Backlog
        db.query(Ticket).filter(Ticket.sprint_id == sid, Ticket.status != "done").update(
            {"sprint_id": None})
        db.commit()
    return RedirectResponse("/admin/tickets?tab=sprints", status_code=303)


@router.post("/sprints/{sid}/delete")
def sprint_delete(sid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    db.query(Ticket).filter(Ticket.sprint_id == sid).update({"sprint_id": None})
    s = db.query(Sprint).filter(Sprint.id == sid).first()
    if s: db.delete(s); db.commit()
    return RedirectResponse("/admin/tickets?tab=sprints", status_code=303)


# ── Jira-CSV-Import ──────────────────────────────────────────────────────────

_PRIO = {"highest": "kritisch", "high": "hoch", "medium": "mittel",
         "low": "niedrig", "lowest": "niedrig"}
_PALETTE = ["#1D4E89", "#e8743b", "#6b8e23", "#9333ea", "#0d9488", "#db2777",
            "#b45309", "#475569", "#dc2626", "#0891b2"]


def _aufwand_from_sp(sp):
    try:
        f = float(str(sp).replace(",", "."))
    except (ValueError, TypeError):
        return None
    if f <= 0: return None
    if f <= 2: return "S"
    if f <= 4: return "M"
    if f <= 8: return "L"
    return "XL"


def _status_from(row):
    sk = (row.get("Statuskategorie") or row.get("Status") or "").strip().lower()
    if "arbeit" in sk or "progress" in sk or "bearbeit" in sk:
        return "doing"
    if "fertig" in sk or "erledigt" == sk or "done" in sk or "abgeschlossen" in sk:
        return "done"
    return "todo"


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request, _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/tickets_import.html", tpl(request, ergebnis=None))


@router.post("/import", response_class=HTMLResponse)
async def import_post(request: Request, datei: UploadFile = File(...),
                      umfang: str = Form("business"),
                      db: Session = Depends(get_db), _=Depends(get_admin_user)):
    raw = await datei.read()
    text = None
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    if text is None:
        return templates.TemplateResponse("admin/tickets_import.html",
            tpl(request, ergebnis={"fehler": "Datei konnte nicht gelesen werden."}))

    reader = csv.DictReader(io.StringIO(text))

    # Kategorien-Cache (Name -> id), inkl. bestehender
    kat = {k.name: k.id for k in db.query(TicketKategorie).all()}
    farb_i = len(kat)
    # vorhandene extern_keys → Doppel-Import vermeiden
    vorhanden = {t.extern_key for t in db.query(Ticket.extern_key).all() if t.extern_key}

    importiert = uebersprungen = 0
    for row in reader:
        proj = (row.get("Projektschlüssel") or "").strip().upper()
        # Umfang-Filter
        if umfang == "kbd" and proj != "KBD":
            uebersprungen += 1; continue
        if umfang == "business" and proj == "MP":
            uebersprungen += 1; continue

        key = (row.get("Vorgangsschlüssel") or "").strip() or None
        if key and key in vorhanden:
            uebersprungen += 1; continue

        titel = (row.get("Zusammenfassung") or "").strip()
        if not titel:
            uebersprungen += 1; continue

        # Kategorie aus Epic (Parent summary)
        kat_id = None
        epic = (row.get("Parent summary") or "").strip()
        if epic:
            if epic not in kat:
                k = TicketKategorie(name=epic, farbe=_PALETTE[farb_i % len(_PALETTE)])
                db.add(k); db.flush()
                kat[epic] = k.id; farb_i += 1
            kat_id = kat[epic]

        prio = (row.get("Priorität") or "").strip().lower()
        faellig = None
        fd = (row.get("Fälligkeitsdatum") or "").strip()
        for fmt in ("%d/%b/%y %I:%M %p", "%d/%b/%y", "%Y-%m-%d"):
            try:
                faellig = datetime.strptime(fd, fmt).date(); break
            except (ValueError, TypeError):
                continue

        t = Ticket(
            titel=titel,
            beschreibung=(row.get("Beschreibung") or "").strip(),
            kategorie_id=kat_id,
            wichtigkeit=_PRIO.get(prio, "mittel"),
            aufwand=_aufwand_from_sp(row.get("Benutzerdefinierte Felder (Story point estimate)")),
            status=_status_from(row),
            sprint_id=None,
            faellig=faellig,
            extern_key=key,
            reihenfolge=0, erstellt_am=_now(), aktualisiert_am=_now(),
        )
        db.add(t)
        if key:
            vorhanden.add(key)
        importiert += 1

    db.commit()
    return templates.TemplateResponse("admin/tickets_import.html",
        tpl(request, ergebnis={"importiert": importiert, "uebersprungen": uebersprungen}))


# ── Kategorien ───────────────────────────────────────────────────────────────

@router.post("/kategorien/new")
def kategorie_new(name: str = Form(...), farbe: str = Form("#1D4E89"),
                  db: Session = Depends(get_db), _=Depends(get_admin_user)):
    if name.strip():
        db.add(TicketKategorie(name=name.strip(), farbe=farbe or "#1D4E89"))
        db.commit()
    return RedirectResponse("/admin/tickets?tab=kategorien", status_code=303)


@router.post("/kategorien/{kid}/delete")
def kategorie_delete(kid: int, db: Session = Depends(get_db), _=Depends(get_admin_user)):
    db.query(Ticket).filter(Ticket.kategorie_id == kid).update({"kategorie_id": None})
    k = db.query(TicketKategorie).filter(TicketKategorie.id == kid).first()
    if k: db.delete(k); db.commit()
    return RedirectResponse("/admin/tickets?tab=kategorien", status_code=303)
