import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, date, time, timedelta

from database import get_db
from models import Verfuegbarkeitsanfrage, Event, Dienstleister, KundeWiedervorlage, Admin
from config import get_config

router = APIRouter(prefix="/cron")


def _check_secret(secret: str = "") -> bool:
    cfg = get_config()
    return secret == cfg.get("cron_secret", "")


def _run_einsatz_erinnerungen(db: Session) -> dict:
    """Erinnert bestätigte Dienstleister 2 Tage vor ihrem Einsatz. Idempotent über
    das Flag einsatz_erinnerung_gesendet."""
    in_2_tagen = date.today() + timedelta(days=2)
    zusagen = db.query(Verfuegbarkeitsanfrage).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).filter(
        Verfuegbarkeitsanfrage.status == "Ja",
        Verfuegbarkeitsanfrage.einsatz_erinnerung_gesendet == False,
        Event.datum == in_2_tagen,
    ).all()

    from email_service import send_einsatz_erinnerung
    count = 0
    for a in zusagen:
        try:
            send_einsatz_erinnerung(a.dienstleister, a.event)
            a.einsatz_erinnerung_gesendet = True
            count += 1
        except Exception as e:
            print(f"Einsatz-Erinnerung fehlgeschlagen für {a.dienstleister.email}: {e}")
    db.commit()
    return {"einsatz_erinnerungen_gesendet": count, "datum": in_2_tagen.strftime("%d.%m.%Y")}


def _run_teamleiter_infos(db: Session) -> int:
    """Info-Mail an Kunden ~1 Woche vor dem Event mit dem Teamleiter als Ansprechpartner.
    Nur wenn Teamleiter gesetzt, Kunden-E-Mail vorhanden und noch nicht gesendet."""
    in_7_tagen = date.today() + timedelta(days=7)
    events = db.query(Event).filter(
        Event.datum == in_7_tagen,
        Event.teamleiter_id != None,            # noqa: E711
        Event.kunde_email != None,              # noqa: E711
        Event.kunde_email != "",
        Event.teamleiter_mail_gesendet == False,
    ).all()

    from email_service import send_teamleiter_info
    count = 0
    for ev in events:
        try:
            send_teamleiter_info(ev)
            ev.teamleiter_mail_gesendet = True
            count += 1
        except Exception as e:
            print(f"Teamleiter-Info-Mail fehlgeschlagen für Event {ev.id}: {e}")
    db.commit()
    return count


_APP_BASE = "https://kindsalabim-events.onrender.com"


def _run_bericht_erinnerungen(db: Session) -> int:
    """Erinnert den Teamleiter, den Eventbericht auszufüllen – erstmals ab 2h nach Event-Ende,
    danach alle 3 Tage, bis der Bericht eingereicht ist. Idempotent über bericht_erinnerung_am.
    Hinweis: Der Versandzeitpunkt hängt vom Cron-Takt ab (täglich) – die 2h/3-Tage sind die
    Mindest-Wartezeiten, gesendet wird beim nächsten Cron-Lauf danach."""
    from email_service import send_bericht_erinnerung
    from auth import create_magic_token
    now = datetime.now()
    heute = now.date()
    kandidaten = db.query(Event).filter(
        Event.datum <= heute,
        Event.teamleiter_id != None,            # noqa: E711
        Event.bericht_eingereicht_am == None,   # noqa: E711
        Event.status.notin_(["Abgesagt", "Abgeschlossen"]),
    ).all()
    count = 0
    for ev in kandidaten:
        if ev.zaubershow_event:   # reines Zaubershow-Event: kein Eventbericht nötig
            continue
        tl = ev.teamleiter
        if not tl or not tl.email or "@" not in tl.email:
            continue
        # Event-Ende = Datum + Endzeit; Erinnerung erst 2h danach
        try:
            h, m = (ev.endzeit or "23:59").split(":")
            ende = datetime.combine(ev.datum, time(int(h), int(m)))
        except Exception:
            ende = datetime.combine(ev.datum, time(23, 59))
        if now < ende + timedelta(hours=2):
            continue
        # Wiederholung: frühestens 3 Tage nach der letzten Erinnerung
        if ev.bericht_erinnerung_am:
            try:
                if now < datetime.fromisoformat(ev.bericht_erinnerung_am) + timedelta(days=3):
                    continue
            except ValueError:
                pass
        try:
            token = create_magic_token(tl, db)
            magic_url = f"{_APP_BASE}/portal/auth/{token}?next=/portal/bericht/{ev.id}"
            send_bericht_erinnerung(tl, ev, magic_url)
            ev.bericht_erinnerung_am = now.isoformat(timespec="seconds")
            count += 1
        except Exception as e:
            print(f"Bericht-Erinnerung fehlgeschlagen für Event {ev.id}: {e}")
    db.commit()
    return count


def _run_material_abhol_erinnerungen(db: Session) -> int:
    """3 Tage vor dem Event: erinnert den zugeteilten Logistiker, das Material abzuholen/mitzunehmen.
    Nur wenn Materialmitnahme nötig + Logistiker gesetzt + Logistiker hat E-Mail + noch nicht erinnert."""
    in_3_tagen = date.today() + timedelta(days=3)
    events = db.query(Event).filter(
        Event.datum == in_3_tagen,
        Event.material_mitnahme == True,                     # noqa: E712
        Event.logistiker_id != None,                          # noqa: E711
        Event.material_abhol_erinnerung_gesendet == False,    # noqa: E712
        Event.status.notin_(["Abgesagt", "Abgeschlossen"]),
    ).all()
    from email_service import send_material_abhol_erinnerung
    count = 0
    for ev in events:
        log = ev.logistiker
        if not log or not log.email or "@" not in log.email:
            continue
        a = db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == ev.id,
            Verfuegbarkeitsanfrage.dienstleister_id == ev.logistiker_id).first()
        transport = a.logistik_transport if a else ""
        try:
            send_material_abhol_erinnerung(ev, log, transport)
            ev.material_abhol_erinnerung_gesendet = True
            count += 1
        except Exception as e:
            print(f"Material-Abhol-Erinnerung fehlgeschlagen für Event {ev.id}: {e}")
    db.commit()
    return count


def _run_abgelaufene_anfragen(db: Session) -> int:
    """Markiert offene Verfügbarkeitsanfragen, deren Frist abgelaufen ist, als „Abgelaufen"
    und benachrichtigt das Büro (Glocke, eine Meldung je Event) zum Nachbesetzen.

    Nur für kommende, nicht abgesagte/abgeschlossene Events – vergangene Events brauchen keine
    Nachbesetzung mehr. Die Soft-Frist bleibt: der Dienstleister sieht die Anfrage im Portal
    weiter und kann verspätet antworten (das setzt den Status dann auf Ja/Nein). Idempotent –
    einmal als „Abgelaufen" markierte Anfragen werden nicht erneut gefunden."""
    today = date.today()
    abgelaufen = db.query(Verfuegbarkeitsanfrage).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).filter(
        Verfuegbarkeitsanfrage.status == "Ausstehend",
        Verfuegbarkeitsanfrage.frist_datum != None,   # noqa: E711
        Verfuegbarkeitsanfrage.frist_datum < today,
        Event.datum >= today,
        Event.status.notin_(["Abgesagt", "Abgeschlossen"]),
    ).all()
    if not abgelaufen:
        return 0

    pro_event: dict[int, int] = {}
    for a in abgelaufen:
        a.status = "Abgelaufen"
        pro_event[a.event_id] = pro_event.get(a.event_id, 0) + 1

    from notifications import notify
    from routes.admin import vorschlag_ersatz, ersatz_label
    for eid, n in pro_event.items():
        ev = db.get(Event, eid)
        datum = ev.datum.strftime("%d.%m.%Y") if ev and ev.datum else ""
        anlass = (ev.anlass if ev else "") or "Event"
        wort = "Anfrage" if n == 1 else "Anfragen"
        v = vorschlag_ersatz(ev, db)
        vorschlag = f" Vorschlag zum Nachbesetzen: {ersatz_label(v)}." if v else ""
        notify(db, "anfrage_abgelaufen",
               f"{n} {wort} abgelaufen: {anlass}",
               f"{n} Verfügbarkeitsanfrage(n) für {anlass} am {datum} sind ohne Antwort "
               f"abgelaufen – bitte nachbesetzen.{vorschlag}",
               f"/admin/events/{eid}")
    db.commit()
    return len(abgelaufen)


@router.get("/erinnerung")
def send_erinnerungen(secret: str = "", db: Session = Depends(get_db)):
    """Wird täglich von Render Cron aufgerufen. Sendet Erinnerungen 24h vor Fristablauf."""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    today = date.today()
    morgen = today + timedelta(days=1)

    offene = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.status == "Ausstehend",
        Verfuegbarkeitsanfrage.frist_datum == morgen,
        Verfuegbarkeitsanfrage.erinnerung_gesendet == False
    ).all()

    from email_service import send_erinnerung
    count = 0
    for a in offene:
        try:
            send_erinnerung(a.dienstleister, a.event)
            a.erinnerung_gesendet = True
            count += 1
        except Exception as e:
            print(f"Erinnerung fehlgeschlagen für {a.dienstleister.email}: {e}")

    db.commit()

    # Material-Erinnerungen: 3 Wochen vor Event wenn Materialtransport nötig
    in_3_wochen = today + timedelta(weeks=3)
    material_events = db.query(Event).filter(
        Event.datum == in_3_wochen,
        Event.material_mitnahme == True,
        Event.material_bestellt == False
    ).all()
    material_count = 0
    from email_service import send_material_erinnerung
    cfg = get_config()
    for ev in material_events:
        try:
            send_material_erinnerung(ev, cfg["admin_email"])
            material_count += 1
        except Exception as e:
            print(f"Material-Erinnerung fehlgeschlagen: {e}")

    # CRM-Wiedervorlagen: tägliche Sammel-Erinnerung an alle aktiven Admins
    faellige_wv = db.query(KundeWiedervorlage).filter(
        KundeWiedervorlage.erledigt == False,
        KundeWiedervorlage.faellig != None,
        KundeWiedervorlage.faellig <= today,
    ).order_by(KundeWiedervorlage.faellig).all()
    wv_mails = 0
    if faellige_wv:
        from email_service import send_wiedervorlage_digest
        admins = db.query(Admin).filter(Admin.aktiv == True).all()
        for ad in admins:
            try:
                send_wiedervorlage_digest(ad.email, faellige_wv, today)
                wv_mails += 1
            except Exception as e:
                print(f"Wiedervorlage-Digest fehlgeschlagen für {ad.email}: {e}")

    # Einsatz-Erinnerung (2 Tage vorher) – läuft im selben täglichen Cron mit,
    # da der separate Render-Cron nie angelegt wurde.
    einsatz = _run_einsatz_erinnerungen(db)

    # Teamleiter-Info-Mail an Kunden (1 Woche vorher)
    teamleiter_mails = _run_teamleiter_infos(db)

    # Bericht-Erinnerung an Teamleiter (ab 2h nach Event-Ende, dann alle 3 Tage)
    bericht_erinnerungen = _run_bericht_erinnerungen(db)

    # Material-Abhol-Erinnerung an den Logistiker (3 Tage vorher)
    material_abhol = _run_material_abhol_erinnerungen(db)

    # Abgelaufene Anfragen markieren + Büro zum Nachbesetzen benachrichtigen
    abgelaufene_anfragen = _run_abgelaufene_anfragen(db)

    # Baker-Ross-Katalog wöchentlich (montags) aus der Sitemap auffrischen.
    katalog = "übersprungen"
    if today.weekday() == 0:
        try:
            from ingest_bakerross import ingest_catalog
            katalog = ingest_catalog(db)
        except Exception as e:
            katalog = f"fehlgeschlagen: {e}"

    return JSONResponse({"erinnerungen_gesendet": count, "material_erinnerungen": material_count,
                         "wiedervorlage_mails": wv_mails,
                         "einsatz_erinnerungen": einsatz["einsatz_erinnerungen_gesendet"],
                         "teamleiter_mails": teamleiter_mails,
                         "bericht_erinnerungen": bericht_erinnerungen,
                         "material_abhol_erinnerungen": material_abhol,
                         "abgelaufene_anfragen": abgelaufene_anfragen,
                         "bakerross_katalog": katalog,
                         "datum": morgen.strftime("%d.%m.%Y")})


@router.get("/einsatz-erinnerung")
def send_einsatz_erinnerungen(secret: str = "", db: Session = Depends(get_db)):
    """Manuell/separat auslösbar. Erinnert bestätigte Dienstleister 2 Tage vor ihrem
    Einsatz. (Läuft regulär im täglichen /cron/erinnerung mit.)"""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_run_einsatz_erinnerungen(db))


@router.get("/bericht-erinnerung")
def send_bericht_erinnerungen(secret: str = "", db: Session = Depends(get_db)):
    """Schlanker, zeitkritischer Endpunkt – NUR die Bericht-Erinnerung an den Teamleiter.
    Gedacht für einen häufigen Ping (z. B. stündlich via cron-job.org), damit die
    Erinnerung noch am selben Abend rausgeht. Idempotent (2h-Sperre + 3-Tage-Takt),
    läuft zusätzlich im täglichen /cron/erinnerung als Fallback."""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"bericht_erinnerungen": _run_bericht_erinnerungen(db)})


def _model_to_csv(rows, model) -> bytes:
    """Exportiert alle Zeilen eines Modells als CSV (alle Spalten, ; getrennt, UTF-8 mit BOM für Excel)."""
    cols = [c.name for c in model.__table__.columns]
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([getattr(r, c) for c in cols])
    return buf.getvalue().encode("utf-8-sig")


@router.post("/backup")
def send_backup(secret: str = "", db: Session = Depends(get_db)):
    """Wird wöchentlich (montags) von Render Cron aufgerufen. Schickt einen CSV-Export
    aller Events + Dienstleister als E-Mail-Anhang an den Admin."""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    events = db.query(Event).all()
    dienstleister = db.query(Dienstleister).all()

    datum = datetime.today().strftime("%Y-%m-%d")
    attachments = [
        (f"events_{datum}.csv", _model_to_csv(events, Event)),
        (f"dienstleister_{datum}.csv", _model_to_csv(dienstleister, Dienstleister)),
    ]

    from email_service import send_backup
    try:
        send_backup(attachments, len(events), len(dienstleister))
    except Exception as e:
        print(f"Backup-E-Mail fehlgeschlagen: {e}")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    return JSONResponse({"status": "ok", "events": len(events), "dienstleister": len(dienstleister)})
