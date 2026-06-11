"""Google-Kalender-Sync (App → Kalender).

Beim Anlegen/Bearbeiten eines Events wird automatisch ein Eintrag in Aykuts
gewohntem Format erzeugt/aktualisiert; beim Löschen entfernt.

Zugang über einen Google-Service-Account: Das JSON kommt als ENV-Secret
`GOOGLE_CALENDAR_CREDENTIALS`, die Ziel-Kalender stehen in config.defaults.yaml.
Ohne Credentials sind alle Funktionen ein No-op (lokal / bis Setup steht).

Format (mit Aykut abgestimmt):
  Titel:  (div.) Stadt, Anlass, Ansprechpartner
  Farbe:  Kindsalabim blau=bestätigt / grau=offen · Knallfrosch dunkelgrün/hellgrün
"""
import json
import re

from config import get_config

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_BASE_URL = "https://kindsalabim-events.onrender.com"

# Google colorId: 7=Peacock(blau) 8=Graphite(grau) 2=Sage(hellgrün) 10=Basil(dunkelgrün)
_OFFENE_STATUS = {"Entwurf", "Dienstleister angefragt"}

_svc = None  # gecachter Client (einmal bauen, danach wiederverwenden)


def _service():
    """Baut den Calendar-API-Client (gecacht) – oder None, wenn nicht konfiguriert.
    Mit 15-s-Timeout, damit Netzwerk-Hänger nicht ewig blockieren."""
    global _svc
    if _svc is not None:
        return _svc
    cfg = get_config()
    raw = cfg.get("google_calendar_credentials")
    if not raw:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        info = json.loads(raw) if isinstance(raw, str) else raw
        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
            authed = AuthorizedHttp(creds, http=httplib2.Http(timeout=15))
            _svc = build("calendar", "v3", http=authed, cache_discovery=False, static_discovery=True)
        except Exception:
            _svc = build("calendar", "v3", credentials=creds, cache_discovery=False, static_discovery=True)
        return _svc
    except Exception as e:
        print(f"Kalender-Service nicht verfügbar: {e}")
        return None


def _calendar_id(ev):
    cfg = get_config()
    key = "calendar_id_knallfrosch" if ev.marke == "Knallfrosch" else "calendar_id_kindsalabim"
    return cfg.get(key)


def _stadt(ort: str) -> str:
    """Stadt aus dem Veranstaltungsort ziehen (nach 5-stelliger PLZ; sonst letztes Segment)."""
    if not ort:
        return ""
    m = re.search(r"\b\d{5}\s+([^,]+)", ort)
    if m:
        return m.group(1).strip()
    return ort.split(",")[-1].strip()


def _title(ev) -> str:
    stadt = _stadt(ev.veranstaltungsort)
    kontakt = (ev.kunde_kontakt or "").strip() or (ev.kunde_firma or "").strip()
    rest = ", ".join(p for p in [stadt, ev.anlass, kontakt] if p)
    return f"(div.) {rest}".strip() if rest else "(div.)"


def _color_id(ev) -> str:
    bestaetigt = ev.status not in _OFFENE_STATUS
    if ev.marke == "Knallfrosch":
        return "10" if bestaetigt else "2"
    return "7" if bestaetigt else "8"


def _description(ev) -> str:
    lines = []
    kunde = " / ".join(p for p in [ev.kunde_firma, ev.kunde_kontakt] if p)
    if kunde:
        lines.append(f"Kunde: {kunde}")
    if ev.kunde_telefon:
        lines.append(f"Tel: {ev.kunde_telefon}")
    if ev.produkte:
        lines.append(f"Produkte: {ev.produkte}")
    team = []
    if ev.anzahl_teamer:
        team.append(f"{ev.anzahl_teamer} Teamer")
    if ev.anzahl_kuenstler:
        team.append(f"{ev.anzahl_kuenstler} Künstler")
    if team:
        lines.append("Team: " + ", ".join(team))
    if ev.hinweise:
        lines.append(f"Hinweise: {ev.hinweise}")
    lines.append("")
    lines.append(f"Auftragsbestätigung: {_BASE_URL}/admin/events/{ev.id}/auftragsbestaetigung/view")
    lines.append(f"In der App: {_BASE_URL}/admin/events/{ev.id}")
    return "\n".join(lines)


def _dt(datum, zeit):
    """{datum}T{HH:MM}:00 in Europe/Berlin (Google rechnet den Offset/DST selbst)."""
    return {"dateTime": f"{datum.isoformat()}T{zeit}:00", "timeZone": "Europe/Berlin"}


def _event_body(ev) -> dict:
    return {
        "summary": _title(ev),
        "location": ev.veranstaltungsort or "",
        "description": _description(ev),
        "colorId": _color_id(ev),
        "start": _dt(ev.datum, ev.startzeit),
        "end": _dt(ev.datum, ev.endzeit),
    }


def sync_event(ev):
    """Erstellt oder aktualisiert den Kalendereintrag. No-op ohne Credentials.
    Setzt ev.kalender_event_id – der Aufrufer muss anschließend committen."""
    svc = _service()
    if not svc:
        return
    cid = _calendar_id(ev)
    if not cid:
        return
    if not (ev.datum and ev.startzeit and ev.endzeit):
        return
    body = _event_body(ev)
    try:
        if ev.kalender_event_id:
            svc.events().update(calendarId=cid, eventId=ev.kalender_event_id, body=body).execute()
        else:
            created = svc.events().insert(calendarId=cid, body=body).execute()
            ev.kalender_event_id = created.get("id")
    except Exception as e:
        print(f"Kalender-Sync fehlgeschlagen (Event {ev.id}): {e}")


def delete_event(ev):
    """Entfernt den Kalendereintrag. No-op ohne Credentials / ohne ID."""
    delete_event_async(ev.kalender_event_id, ev.marke)


def delete_event_async(cal_event_id, marke):
    """Löscht per Kalender-Event-ID + Marke (für Hintergrund-Aufrufe ohne ORM-Objekt)."""
    svc = _service()
    if not svc or not cal_event_id:
        return
    cfg = get_config()
    key = "calendar_id_knallfrosch" if marke == "Knallfrosch" else "calendar_id_kindsalabim"
    cid = cfg.get(key)
    try:
        svc.events().delete(calendarId=cid, eventId=cal_event_id).execute()
    except Exception as e:
        print(f"Kalender-Löschen fehlgeschlagen: {e}")


def sync_event_async(event_id):
    """Hintergrund-Sync: eigene DB-Session, lädt Event, synct, committet kalender_event_id."""
    from database import SessionLocal
    from models import Event
    db = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.id == event_id).first()
        if ev:
            sync_event(ev)
            db.commit()
    except Exception as e:
        print(f"Kalender-Hintergrund-Sync fehlgeschlagen ({event_id}): {e}")
    finally:
        db.close()
