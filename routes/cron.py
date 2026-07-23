import csv
import io
import secrets
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from database import get_db
from models import (Verfuegbarkeitsanfrage, Event, Dienstleister, KundeWiedervorlage,
                    Admin, Rechnung, Kunde)
from config import get_config

router = APIRouter(prefix="/cron")

# Render-Server laufen in UTC; alle Datums-/Zeitfenster hier beziehen sich aber auf
# deutsche Ortszeit. Ohne diese Umrechnung verschieben sich Stichtage und Stunden-
# fenster (z. B. „2 h nach Event-Ende") um 1–2 Stunden bzw. über Mitternacht um
# einen Tag. (Review M6)
_BERLIN = ZoneInfo("Europe/Berlin")


def _jetzt() -> datetime:
    """Aktuelle Zeit in deutscher Ortszeit als naives datetime (passend zu den
    ebenfalls naiven „HH:MM"-Event-Zeiten)."""
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _heute() -> date:
    return _jetzt().date()


def _check_secret(request: Request, secret: str = "") -> bool:
    """Cron-Auth: bevorzugt per Header X-Cron-Secret (landet nicht in Server-Logs),
    der Query-Parameter ?secret= bleibt als Fallback für bestehende Aufrufer
    (cron-job.org). Zeitkonstanter Vergleich gegen Timing-Angriffe."""
    cfg = get_config()
    erwartet = cfg.get("cron_secret", "") or ""
    geliefert = request.headers.get("x-cron-secret") or secret or ""
    return bool(erwartet) and secrets.compare_digest(geliefert, erwartet)


def _run_einsatz_erinnerungen(db: Session) -> dict:
    """Erinnert bestätigte Dienstleister 2 Tage vor ihrem Einsatz. Idempotent über
    das Flag einsatz_erinnerung_gesendet."""
    heute = _heute()
    bis = heute + timedelta(days=2)
    # Fenster [heute, heute+2] statt exaktem Stichtag: ein ausgefallener Cron-Tag holt
    # die Erinnerung nach, das Flag verhindert Doppelversand. (Review K1)
    zusagen = db.query(Verfuegbarkeitsanfrage).join(
        Event, Verfuegbarkeitsanfrage.event_id == Event.id).filter(
        Verfuegbarkeitsanfrage.status == "Ja",
        Verfuegbarkeitsanfrage.einsatz_erinnerung_gesendet == False,
        Event.datum >= heute,
        Event.datum <= bis,
    ).all()

    from email_service import send_einsatz_erinnerung
    count = 0
    for a in zusagen:
        try:
            send_einsatz_erinnerung(a.dienstleister, a.event)
            a.einsatz_erinnerung_gesendet = True
            db.commit()   # pro Mail committen: ein Absturz mittendrin = kein Doppelversand
            count += 1
        except Exception as e:
            db.rollback()
            print(f"Einsatz-Erinnerung fehlgeschlagen für {a.dienstleister.email}: {e}")
    return {"einsatz_erinnerungen_gesendet": count, "datum": bis.strftime("%d.%m.%Y")}


def _run_teamleiter_infos(db: Session) -> int:
    """Info-Mail an Kunden ~1 Woche vor dem Event mit dem Teamleiter als Ansprechpartner.
    Nur wenn Teamleiter gesetzt, Kunden-E-Mail vorhanden und noch nicht gesendet."""
    heute = _heute()
    bis = heute + timedelta(days=7)
    # Fenster [heute, heute+7] statt exaktem Stichtag – ein ausgefallener Cron-Tag
    # holt die Info nach; das Flag verhindert Doppelversand. (Review K1)
    events = db.query(Event).filter(
        Event.datum >= heute,
        Event.datum <= bis,
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
            db.commit()
            count += 1
        except Exception as e:
            db.rollback()
            print(f"Teamleiter-Info-Mail fehlgeschlagen für Event {ev.id}: {e}")
    return count


_APP_BASE = "https://kindsalabim-events.onrender.com"


def _run_bericht_erinnerungen(db: Session) -> int:
    """Erinnert den Teamleiter, den Eventbericht auszufüllen – erstmals ab 2h nach Event-Ende,
    danach alle 3 Tage, bis der Bericht eingereicht ist. Idempotent über bericht_erinnerung_am.
    Hinweis: Der Versandzeitpunkt hängt vom Cron-Takt ab (täglich) – die 2h/3-Tage sind die
    Mindest-Wartezeiten, gesendet wird beim nächsten Cron-Lauf danach."""
    from email_service import send_bericht_erinnerung
    from auth import create_magic_token
    now = _jetzt()
    heute = now.date()
    kandidaten = db.query(Event).filter(
        Event.datum <= heute,
        Event.teamleiter_id != None,            # noqa: E711
        Event.bericht_eingereicht_am == None,   # noqa: E711
        Event.status.notin_(["Abgesagt", "Abgeschlossen"]),
    ).all()
    count = 0
    token_cache: dict[int, str] = {}   # ein Magic-Token je Teamleiter pro Lauf wiederverwenden
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
            # Hat der Teamleiter mehrere offene Berichte, würde ein zweiter create_magic_token
            # den ersten Link entwerten → pro Teamleiter nur EINEN Token je Lauf erzeugen.
            if tl.id not in token_cache:
                token_cache[tl.id] = create_magic_token(tl, db)
            magic_url = f"{_APP_BASE}/portal/auth/{token_cache[tl.id]}?next=/portal/bericht/{ev.id}"
            send_bericht_erinnerung(tl, ev, magic_url)
            ev.bericht_erinnerung_am = now.isoformat(timespec="seconds")
            db.commit()   # pro Event committen: schließt das Doppelversand-Fenster
                          # zwischen 2h-Ping und Tages-Cron (Review M7)
            count += 1
        except Exception as e:
            db.rollback()
            token_cache.pop(tl.id, None)   # Token wurde evtl. nicht persistiert
            print(f"Bericht-Erinnerung fehlgeschlagen für Event {ev.id}: {e}")
    return count


def _run_material_abhol_erinnerungen(db: Session) -> int:
    """3 Tage vor dem Event: erinnert den zugeteilten Logistiker, das Material abzuholen/mitzunehmen.
    Nur wenn Materialmitnahme nötig + Logistiker gesetzt + Logistiker hat E-Mail + noch nicht erinnert."""
    heute = _heute()
    bis = heute + timedelta(days=3)
    # Fenster [heute, heute+3] statt exaktem Stichtag; Flag verhindert Doppelversand. (Review K1)
    events = db.query(Event).filter(
        Event.datum >= heute,
        Event.datum <= bis,
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
            db.commit()
            count += 1
        except Exception as e:
            db.rollback()
            print(f"Material-Abhol-Erinnerung fehlgeschlagen für Event {ev.id}: {e}")
    return count


def _run_abgelaufene_anfragen(db: Session) -> int:
    """Markiert offene Verfügbarkeitsanfragen, deren Frist abgelaufen ist, als „Abgelaufen"
    und benachrichtigt das Büro (Glocke, eine Meldung je Event) zum Nachbesetzen.

    Nur für kommende, nicht abgesagte/abgeschlossene Events – vergangene Events brauchen keine
    Nachbesetzung mehr. Die Soft-Frist bleibt: der Dienstleister sieht die Anfrage im Portal
    weiter und kann verspätet antworten (das setzt den Status dann auf Ja/Nein). Idempotent –
    einmal als „Abgelaufen" markierte Anfragen werden nicht erneut gefunden."""
    today = _heute()
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


def _run_ueberfaellige_rechnungen(db: Session) -> int:
    """Meldet unbezahlte Rechnungen, deren Zahlungsziel (14 Werktage nach Rechnungs-
    datum) abgelaufen ist – Glocke + Admin-Mail via notify(), einmal je Rechnung
    (Flag ueberfaellig_erinnert). Wird die Rechnung nie bezahlt, bleibt sie in der
    Buchhaltung rot markiert (Badge), es kommt aber keine tägliche Wiederholung."""
    from choices import rechnung_faellig_am, de_euro, ZAHLUNGSZIEL_WERKTAGE
    from notifications import notify
    heute = _heute()
    offene = db.query(Rechnung).filter(
        Rechnung.bezahlt == False,                    # noqa: E712
        Rechnung.ueberfaellig_erinnert == False,      # noqa: E712
        Rechnung.datum != None,                       # noqa: E711
    ).all()
    count = 0
    for r in offene:
        faellig = rechnung_faellig_am(r)
        if not faellig or heute <= faellig:
            continue
        try:
            notify(db, "rechnung_ueberfaellig",
                   f"Rechnung überfällig: {r.rgnr or 'ohne Nr.'} – {r.kunde or 'unbekannt'}",
                   f"Rechnung vom {r.datum.strftime('%d.%m.%Y')} über {de_euro(r.brutto)} € "
                   f"brutto war am {faellig.strftime('%d.%m.%Y')} fällig "
                   f"({ZAHLUNGSZIEL_WERKTAGE} Werktage) und ist noch nicht als bezahlt markiert.",
                   "/admin/buchhaltung")
            r.ueberfaellig_erinnert = True
            db.commit()   # pro Rechnung committen: kein Doppelversand bei Absturz
            count += 1
        except Exception as e:
            db.rollback()
            print(f"Überfällig-Meldung fehlgeschlagen für Rechnung {r.id}: {e}")
    return count


@router.get("/erinnerung")
def send_erinnerungen(request: Request, secret: str = "", db: Session = Depends(get_db)):
    """Wird täglich von Render Cron aufgerufen. Sendet Erinnerungen 24h vor Fristablauf."""
    if not _check_secret(request, secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    today = _heute()
    morgen = today + timedelta(days=1)

    # Frist-Erinnerung 24h vorher; „<= morgen" statt „== morgen", damit ein ausgefallener
    # Cron-Tag nicht bedeutet, dass die Erinnerung nie rausgeht. Flag verhindert Doppel-
    # versand; abgelaufene Anfragen wechseln später den Status und fallen aus dem Filter. (K1)
    offene = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.status == "Ausstehend",
        Verfuegbarkeitsanfrage.frist_datum != None,   # noqa: E711
        Verfuegbarkeitsanfrage.frist_datum <= morgen,
        Verfuegbarkeitsanfrage.erinnerung_gesendet == False
    ).all()

    from email_service import send_erinnerung
    count = 0
    for a in offene:
        try:
            send_erinnerung(a.dienstleister, a.event)
            a.erinnerung_gesendet = True
            db.commit()
            count += 1
        except Exception as e:
            db.rollback()
            print(f"Erinnerung fehlgeschlagen für {a.dienstleister.email}: {e}")

    # Material-Bestell-Erinnerung: bis 3 Wochen vor Event, wenn Materialtransport nötig und
    # noch nicht bestellt. Fenster + eigenes Flag (material_erinnerung_gesendet) statt exaktem
    # Stichtag ohne Flag – sonst Doppelversand bei Doppel-Aufruf bzw. Totalausfall bei Cron-
    # Lücke. (Review K2)
    in_3_wochen = today + timedelta(weeks=3)
    material_events = db.query(Event).filter(
        Event.datum >= today,
        Event.datum <= in_3_wochen,
        Event.material_mitnahme == True,
        Event.material_bestellt == False,
        Event.material_erinnerung_gesendet == False,
        Event.status.notin_(["Abgesagt", "Abgeschlossen"]),
    ).all()
    material_count = 0
    from email_service import send_material_erinnerung
    cfg = get_config()
    for ev in material_events:
        try:
            send_material_erinnerung(ev, cfg["admin_email"])
            ev.material_erinnerung_gesendet = True
            db.commit()
            material_count += 1
        except Exception as e:
            db.rollback()
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

    # Unbezahlte Rechnungen nach Zahlungsziel (14 Werktage) melden
    rechnungen_ueberfaellig = _run_ueberfaellige_rechnungen(db)

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
                         "rechnungen_ueberfaellig": rechnungen_ueberfaellig,
                         "bakerross_katalog": katalog,
                         "datum": morgen.strftime("%d.%m.%Y")})


@router.get("/einsatz-erinnerung")
def send_einsatz_erinnerungen(request: Request, secret: str = "", db: Session = Depends(get_db)):
    """Manuell/separat auslösbar. Erinnert bestätigte Dienstleister 2 Tage vor ihrem
    Einsatz. (Läuft regulär im täglichen /cron/erinnerung mit.)"""
    if not _check_secret(request, secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_run_einsatz_erinnerungen(db))


@router.get("/bericht-erinnerung")
def send_bericht_erinnerungen(request: Request, secret: str = "", db: Session = Depends(get_db)):
    """Schlanker, zeitkritischer Endpunkt – NUR die Bericht-Erinnerung an den Teamleiter.
    Gedacht für einen häufigen Ping (z. B. stündlich via cron-job.org), damit die
    Erinnerung noch am selben Abend rausgeht. Idempotent (2h-Sperre + 3-Tage-Takt),
    läuft zusätzlich im täglichen /cron/erinnerung als Fallback."""
    if not _check_secret(request, secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"bericht_erinnerungen": _run_bericht_erinnerungen(db)})


# Spalten, die NIE ins Backup-CSV dürfen: aktive Login-Geheimnisse. Ein Magic-Token
# ist 36 h ein gültiger Portal-Login, checklist_token öffnet die Kunden-Checkliste –
# beides würde in einer weiterleitbaren E-Mail landen. (Roadmap-Review H1)
_CSV_GEHEIM = {"magic_token", "magic_token_expires", "checklist_token",
               "password_hash", "reset_token", "reset_token_expires"}


def _model_to_csv(rows, model) -> bytes:
    """Exportiert alle Zeilen eines Modells als CSV (; getrennt, UTF-8 mit BOM für Excel).
    Login-Geheimnisse (_CSV_GEHEIM) werden ausgelassen."""
    cols = [c.name for c in model.__table__.columns if c.name not in _CSV_GEHEIM]
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([getattr(r, c) for c in cols])
    return buf.getvalue().encode("utf-8-sig")


@router.post("/backup")
def send_backup(request: Request, secret: str = "", db: Session = Depends(get_db)):
    """Wird wöchentlich (montags) von Render Cron aufgerufen. Schickt einen CSV-Export
    der wichtigsten Tabellen (Events, Dienstleister, Rechnungen, Kunden) als E-Mail-
    Anhang an den Admin – menschenlesbares Off-Platform-Notfall-Backup."""
    if not _check_secret(request, secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    datum = _heute().strftime("%Y-%m-%d")
    # (Beschriftung, Dateiname-Präfix, Modell) – so lässt sich die Liste leicht erweitern.
    export = [
        ("Events",        "events",        Event),
        ("Dienstleister", "dienstleister", Dienstleister),
        ("Rechnungen",    "rechnungen",    Rechnung),
        ("Kunden",        "kunden",        Kunde),
    ]
    attachments, counts = [], {}
    for label, praefix, modell in export:
        zeilen = db.query(modell).all()
        attachments.append((f"{praefix}_{datum}.csv", _model_to_csv(zeilen, modell)))
        counts[label] = len(zeilen)

    from email_service import send_backup
    try:
        send_backup(attachments, counts)
    except Exception as e:
        print(f"Backup-E-Mail fehlgeschlagen: {e}")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    return JSONResponse({"status": "ok", **counts})
