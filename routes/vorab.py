"""Vorab-Check: unverbindliche Anfrage an Dienstleister, BEVOR der Kunde ein Angebot bekommt.

Aykuts Ausgangslage (26.09.2026): Bei knappen Sparten (Ballon), kurzfristigen Terminen
oder gefragten Wochenenden fragt er erst per WhatsApp „hältst du mir den Tag frei?" und
schickt dem Kunden danach ein Angebot. Meldet sich der Kunde nie, bleibt der Dienstleister
auf einem freigehaltenen Tag sitzen – niemand sagt ihm Bescheid.

Hier passiert dasselbe über die App: unverbindliche Anfrage per Mail (Antwort per Klick,
ohne Login), Übersicht über die Zusagen und ein Klick zur Reservierung bzw. zur Absage
mit Entwarnung an alle. Bewusst NICHT die normale Verfuegbarkeitsanfrage – die hängt an
einem Event und bringt Fristenlauf, Bestellung und Honorar mit.
"""
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_admin_user
from choices import SPARTE_ICON, benoetigte_sparten, de_date, kuenstler_passt
from config import get_config
from database import get_db
from distance import rank_contractors
from models import Dienstleister, Reservierung, Vorabanfrage, Vorabcheck

router = APIRouter()
templates = Jinja2Templates(directory="templates")
# Eigene Jinja-Umgebung: Filter/Globals, die admin_base.html und die Seite brauchen.
# (notif_unread, ist_buero_user und css_version setzt main.py für alle Router.)
templates.env.filters["de_date"] = de_date
templates.env.globals["sparte_icon"] = SPARTE_ICON

FREIHALTEN_TAGE = 7     # so lange soll der Dienstleister uns den Termin freihalten


def tpl_context(request: Request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def offene_checks(db: Session) -> list:
    """Vorab-Checks, die noch auf eine Entscheidung warten (für die Reservierungsseite)."""
    return (db.query(Vorabcheck).filter(Vorabcheck.status == "offen")
            .order_by(Vorabcheck.datum).all())


def zusagen(check) -> list:
    return [a for a in check.anfragen if a.status == "Ja"]


# ── Anlegen & Übersicht ──────────────────────────────────────────────────────

@router.post("/admin/vorabcheck/new")
def vorabcheck_new(datum: str = Form(...), startzeit: str = Form(""), endzeit: str = Form(""),
                   veranstaltungsort: str = Form(""), aktion: str = Form(""),
                   kunde_firma: str = Form(""), budget: str = Form(""),
                   marke: str = Form("Kindsalabim"), notiz: str = Form(""),
                   db: Session = Depends(get_db), _=Depends(get_admin_user)):
    try:
        datum_d = date.fromisoformat(datum)
    except ValueError:
        return RedirectResponse("/admin/reservierungen?fehler=vorab_datum", status_code=303)
    try:
        budget_f = float(budget.replace(",", ".")) if budget.strip() else None
    except ValueError:
        budget_f = None
    check = Vorabcheck(
        datum=datum_d, startzeit=startzeit.strip() or None, endzeit=endzeit.strip() or None,
        veranstaltungsort=veranstaltungsort.strip() or None, aktion=aktion.strip() or None,
        kunde_firma=kunde_firma.strip() or None, budget=budget_f,
        marke=marke, notiz=notiz.strip() or None,
        frist=date.today() + timedelta(days=FREIHALTEN_TAGE),
        erstellt_am=_jetzt())
    db.add(check); db.commit(); db.refresh(check)
    return RedirectResponse(f"/admin/vorabcheck/{check.id}", status_code=303)


@router.get("/admin/vorabcheck/{check_id}", response_class=HTMLResponse)
def vorabcheck_detail(check_id: int, request: Request, db: Session = Depends(get_db),
                      _=Depends(get_admin_user)):
    check = db.query(Vorabcheck).filter(Vorabcheck.id == check_id).first()
    if not check:
        raise HTTPException(404)
    schon_gefragt = {a.dienstleister_id for a in check.anfragen}
    aktive = db.query(Dienstleister).filter(Dienstleister.aktiv == True).all()  # noqa: E712
    benoetigt = benoetigte_sparten(check.aktion or "")
    vorschlag = {}
    for rolle in ("Künstler", "Teamer"):
        rollen = ("Künstler", "Beides") if rolle == "Künstler" else ("Teamer", "Beides")
        kandidaten = [d for d in aktive if d.rolle in rollen
                      and d.id not in schon_gefragt
                      and (rolle != "Künstler" or kuenstler_passt(d, benoetigt))]
        vorschlag[rolle] = rank_contractors(kandidaten, check.veranstaltungsort or "")
    return templates.TemplateResponse("admin/vorabcheck.html",
        tpl_context(request, check=check, vorschlag=vorschlag, zusagen=zusagen(check)))


# ── Unverbindlich anfragen ───────────────────────────────────────────────────

@router.post("/admin/vorabcheck/{check_id}/anfragen")
def vorabcheck_anfragen(check_id: int, request: Request, background_tasks: BackgroundTasks,
                        dienstleister_ids: list = Form([]), rolle: str = Form("Künstler"),
                        db: Session = Depends(get_db), _=Depends(get_admin_user)):
    check = db.query(Vorabcheck).filter(Vorabcheck.id == check_id).first()
    if not check:
        raise HTTPException(404)
    basis = str(request.base_url).rstrip("/")
    neue = []
    for did in dienstleister_ids:
        try:
            did = int(did)
        except (TypeError, ValueError):
            continue
        if any(a.dienstleister_id == did for a in check.anfragen):
            continue            # Doppelklick / schon gefragt
        a = Vorabanfrage(vorabcheck_id=check.id, dienstleister_id=did, rolle=rolle,
                         token=secrets.token_urlsafe(24), erstellt_am=_jetzt())
        db.add(a); neue.append(a)
    db.commit()
    for a in neue:
        background_tasks.add_task(_anfrage_mail, a.id, basis)
    return RedirectResponse(f"/admin/vorabcheck/{check_id}", status_code=303)


def _anfrage_mail(anfrage_id: int, basis: str):
    """Mailversand im Hintergrund – ein Fehler darf die Anfrage nicht verhindern."""
    from database import SessionLocal
    from email_service import send_vorabanfrage
    db = SessionLocal()
    try:
        a = db.query(Vorabanfrage).filter(Vorabanfrage.id == anfrage_id).first()
        if not a or not a.dienstleister or not (a.dienstleister.email or "").strip():
            return
        send_vorabanfrage(a.dienstleister, a.check,
                          f"{basis}/vorab/{a.token}/ja", f"{basis}/vorab/{a.token}/nein",
                          budget=a.check.budget if a.rolle == "Künstler" else None)
    except Exception as e:
        print(f"[VORAB] Anfrage-Mail {anfrage_id} fehlgeschlagen: {e}")
    finally:
        db.close()


# ── Antwort des Dienstleisters (Klick in der Mail, ohne Login) ───────────────

@router.get("/vorab/{token}/{antwort}", response_class=HTMLResponse)
def vorab_antwort(token: str, antwort: str, request: Request, db: Session = Depends(get_db)):
    if antwort not in ("ja", "nein"):
        raise HTTPException(404)
    a = db.query(Vorabanfrage).filter(Vorabanfrage.token == token).first()
    if not a:
        raise HTTPException(404)
    schon = a.status in ("Ja", "Nein")
    if not schon:
        a.status = "Ja" if antwort == "ja" else "Nein"
        a.beantwortet_am = _jetzt()
        db.commit()
    return templates.TemplateResponse("vorab_antwort.html",
        tpl_context(request, anfrage=a, check=a.check, schon=schon))


# ── Ausgang 1: Angebot raus → Reservierung ──────────────────────────────────

@router.post("/admin/vorabcheck/{check_id}/reservierung")
def vorabcheck_zu_reservierung(check_id: int, background_tasks: BackgroundTasks,
                               frist: str = Form(""), db: Session = Depends(get_db),
                               _=Depends(get_admin_user)):
    check = db.query(Vorabcheck).filter(Vorabcheck.id == check_id).first()
    if not check:
        raise HTTPException(404)
    try:
        frist_d = date.fromisoformat(frist) if frist.strip() else check.frist
    except ValueError:
        frist_d = check.frist
    r = Reservierung(datum=check.datum, startzeit=check.startzeit, endzeit=check.endzeit,
                     veranstaltungsort=check.veranstaltungsort,
                     kunde_firma=check.kunde_firma or (check.aktion or "Anfrage"),
                     anlass=check.aktion, marke=check.marke, frist=frist_d,
                     notiz=check.notiz, erstellt_am=_jetzt())
    db.add(r); db.commit(); db.refresh(r)
    check.reservierung_id = r.id
    check.status = "uebernommen"
    db.commit()
    import calendar_service
    background_tasks.add_task(calendar_service.sync_reservierung_async, r.id)
    return RedirectResponse("/admin/reservierungen?ok=aus_vorabcheck", status_code=303)


# ── Ausgang 2: Kunde bekommt eine Absage ────────────────────────────────────

@router.post("/admin/vorabcheck/{check_id}/absagen")
def vorabcheck_absagen(check_id: int, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db), _=Depends(get_admin_user)):
    """Wir sagen dem Kunden ab – alle, die den Tag freihalten, bekommen Entwarnung."""
    check = db.query(Vorabcheck).filter(Vorabcheck.id == check_id).first()
    if not check:
        raise HTTPException(404)
    check.status = "abgesagt"
    ids = [a.id for a in zusagen(check) if not a.info_gesendet_am]
    db.commit()
    for aid in ids:
        background_tasks.add_task(entwarnung_senden, aid, False)
    return RedirectResponse("/admin/reservierungen?ok=vorab_abgesagt", status_code=303)


def entwarnung_senden(anfrage_id: int, gebucht: bool):
    """„Termin wieder frei" bzw. „Kunde hat gebucht" an jemanden, der freigehalten hat."""
    from database import SessionLocal
    from email_service import send_vorab_entwarnung
    db = SessionLocal()
    try:
        a = db.query(Vorabanfrage).filter(Vorabanfrage.id == anfrage_id).first()
        if not a or a.info_gesendet_am or not a.dienstleister:
            return
        if (a.dienstleister.email or "").strip():
            send_vorab_entwarnung(a.dienstleister, a.check, gebucht=gebucht)
        a.info_gesendet_am = _jetzt()
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[VORAB] Entwarnung {anfrage_id} fehlgeschlagen: {e}")
    finally:
        db.close()


def reservierung_abschliessen(db: Session, reservierung_id: int, gebucht: bool,
                              event_id: int = None) -> list:
    """Die Reservierung endet (gebucht oder freigegeben) – den Vorab-Check nachziehen.

    Gibt die Anfrage-IDs zurück, die noch eine Rückmeldung brauchen; der Aufrufer
    verschickt sie im Hintergrund. Löst außerdem die Verknüpfung zur Reservierung,
    die gleich gelöscht wird."""
    check = (db.query(Vorabcheck)
             .filter(Vorabcheck.reservierung_id == reservierung_id).first())
    if not check:
        return []
    offen = [a.id for a in zusagen(check) if not a.info_gesendet_am]
    check.reservierung_id = None
    if gebucht:
        check.event_id = event_id
    check.status = "uebernommen" if gebucht else "abgesagt"
    db.commit()
    return offen


# ── Erinnerung: jemand wartet auf Bescheid ──────────────────────────────────

def offene_rueckmeldungen_melden(db: Session) -> int:
    """Glocke, solange jemand den Tag für uns freihält und die Frist abgelaufen ist.
    Genau die Lücke, die vorher im Kopf hängen blieb (Vorfall-Schilderung 26.09.2026)."""
    from notifications import notify
    heute = date.today()
    count = 0
    checks = db.query(Vorabcheck).filter(
        Vorabcheck.status == "offen",
        Vorabcheck.frist != None,              # noqa: E711
        Vorabcheck.frist < heute).all()
    for check in checks:
        wartende = [a for a in zusagen(check) if not a.info_gesendet_am]
        if not wartende or check.erinnert_am == heute:
            continue
        namen = ", ".join(a.dienstleister.vorname for a in wartende if a.dienstleister)
        notify(db, "vorab_wartet",
               f"{namen} wartet auf Bescheid: {de_date(check.datum)}",
               f"Für {check.aktion or 'die Anfrage'} am {de_date(check.datum)} "
               f"{'halten' if len(wartende) > 1 else 'hält'} {namen} den Termin frei. "
               f"Die Frist ist abgelaufen – bitte Bescheid geben, ob es etwas wird.",
               f"/admin/vorabcheck/{check.id}", marke=check.marke)
        check.erinnert_am = heute
        db.commit()
        count += 1
    return count
