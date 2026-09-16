"""Google-Kalender-Sync (App → Kalender).

Beim Anlegen/Bearbeiten eines Events wird automatisch ein Eintrag in Aykuts
gewohntem Format erzeugt/aktualisiert; beim Löschen entfernt.

Zugang über einen Google-Service-Account: Das JSON kommt als ENV-Secret
`GOOGLE_CALENDAR_CREDENTIALS`, die Ziel-Kalender stehen in config.defaults.yaml.
Ohne Credentials sind alle Funktionen ein No-op (lokal / bis Setup steht).

Format (mit Aykut abgestimmt):
  Titel:  (KÜRZEL) Stadt, Anlass, Ansprechpartner
  Farbe:  Kindsalabim blau=bestätigt / grau=offen · Knallfrosch dunkelgrün/hellgrün

Kürzel aus den gebuchten Aktionen (siehe _event_art):
  (Z)        nur Zaubershow
  (ZB)       Zaubershow + Ballonmodellage
  (B)        nur Ballonmodellage
  (Kischmi.) nur Kinderschminken
  (div.)     alles andere (mehrere/verschiedene Dienstleistungen ohne klares Einzel-Kürzel)
"""
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import get_config

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_BASE_URL = "https://kindsalabim-events.onrender.com"

# Google colorId: 7=Peacock(blau) 8=Graphite(anthrazit) 4=Flamingo 10=Basil(dunkelgrün)
# Events sind immer gebucht → blau/grün. Abgesagt → flamingo.
# Reservierungen: anthrazit, nach Fristablauf flamingo (Umfärbung via Cron).

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


def diagnose() -> dict:
    """Prüft die Kalender-Verbindung – rein lesend, ändert nichts.

    Hintergrund: Fällt der Kalender aus, merkt man es sonst erst daran, dass
    Termine nicht auftauchen (Vorfall 13.09.2026). Zwei Pfade scheitern dabei
    völlig lautlos: fehlende Zugangsdaten und fehlende Kalender-ID.

    Rückgabe: {"ok": bool, "meldung": str, "kalender": [{marke, ok, detail}]}
    """
    cfg = get_config()
    if not cfg.get("google_calendar_credentials"):
        return {"ok": False, "kalender": [],
                "meldung": "Es sind keine Google-Zugangsdaten hinterlegt "
                           "(Umgebungsvariable GOOGLE_CALENDAR_CREDENTIALS). "
                           "Ohne sie schreibt die App gar nichts in den Kalender."}
    svc = _service()
    if not svc:
        return {"ok": False, "kalender": [],
                "meldung": "Die Zugangsdaten sind hinterlegt, der Client lässt sich "
                           "damit aber nicht aufbauen – vermutlich sind sie "
                           "unvollständig oder kein gültiges Dienstkonto-JSON."}
    ergebnis, alle_ok = [], True
    for marke, key in (("Kindsalabim", "calendar_id_kindsalabim"),
                       ("Knallfrosch", "calendar_id_knallfrosch")):
        cid = cfg.get(key)
        if not cid:
            ergebnis.append({"marke": marke, "ok": False,
                             "detail": f"Keine Kalender-ID hinterlegt ({key})"})
            alle_ok = False
            continue
        try:
            kal = svc.calendars().get(calendarId=cid).execute()
            name = kal.get("summary", cid)
            # Lesen allein beweist nichts: Mit reiner Lese-Freigabe klappt der Abruf,
            # jedes Anlegen scheitert aber (Vorfall 16.09.2026). Die Rolle steht in
            # der Kalenderliste des Dienstkontos – ebenfalls rein lesend abrufbar.
            try:
                rolle = svc.calendarList().get(calendarId=cid).execute().get("accessRole")
            except Exception:
                rolle = None
            if rolle in ("reader", "freeBusyReader"):
                ergebnis.append({"marke": marke, "ok": False,
                                 "detail": f"„{name}“ ist nur LESBAR freigegeben – die App "
                                           f"kann keine Termine eintragen. Freigabe auf "
                                           f"„Änderungen an Terminen vornehmen“ ändern."})
                alle_ok = False
            elif rolle in ("writer", "owner"):
                ergebnis.append({"marke": marke, "ok": True,
                                 "detail": f"verbunden mit „{name}“, Schreibrecht vorhanden"})
            else:
                ergebnis.append({"marke": marke, "ok": True,
                                 "detail": f"„{name}“ erreichbar – ob die App schreiben darf, "
                                           f"zeigt sich erst beim Nachtragen"})
        except Exception as e:
            text = str(e)
            if "404" in text or "notFound" in text:
                hinweis = ("Kalender nicht gefunden oder nicht freigegeben – das "
                           "Dienstkonto braucht Schreibrechte auf diesen Kalender.")
            elif "403" in text:
                hinweis = ("Zugriff verweigert – Freigabe für das Dienstkonto prüfen "
                           "(Schreibrechte nötig).")
            else:
                hinweis = text.splitlines()[0][:200]
            ergebnis.append({"marke": marke, "ok": False, "detail": hinweis})
            alle_ok = False
    return {"ok": alle_ok, "kalender": ergebnis,
            "meldung": "Kalender erreichbar." if alle_ok
                       else "Mindestens ein Kalender ist nicht erreichbar oder nicht beschreibbar."}


def fehlende_eintraege(db, tage_zurueck: int = 30):
    """(events, reservierungen) ohne Kalendereintrag – kommende Termine plus die
    letzten `tage_zurueck` Tage. Abgesagte Events gehören nicht in den Kalender."""
    from datetime import date, timedelta
    from models import Event, Reservierung
    grenze = date.today() - timedelta(days=tage_zurueck)
    events = db.query(Event).filter(
        Event.kalender_event_id == None,                 # noqa: E711
        Event.datum >= grenze,
        Event.status != "Abgesagt").order_by(Event.datum).all()
    reservierungen = db.query(Reservierung).filter(
        Reservierung.kalender_event_id == None,          # noqa: E711
        Reservierung.datum >= grenze).order_by(Reservierung.datum).all()
    return events, reservierungen


def fehlende_nachtragen(db, tage_zurueck: int = 30) -> dict:
    """Trägt Kalendereinträge nach, die fehlen (kein `kalender_event_id`).

    Gedacht für die Zeit nach einem Kalender-Ausfall: Was die App währenddessen
    angelegt hat, steht nur in der Datenbank – für den Alltag zählt aber der
    Kalender. Bestehende Einträge bleiben unberührt.

    Jeder Fehlschlag landet MIT GRUND im Bericht. Vorher kam bei einem
    Schreibverbot „0 nachgetragen, 0 Fehler" heraus (Vorfall 16.09.2026).
    """
    bericht = {"versucht": 0, "events": 0, "reservierungen": 0, "geloescht": 0, "fehler": []}
    offene_events, offene_res = fehlende_eintraege(db, tage_zurueck)

    for ev in offene_events:
        bericht["versucht"] += 1
        titel = f"{ev.kunde_firma or ev.anlass or 'Event'} ({ev.datum.strftime('%d.%m.%Y')})"
        try:
            grund = sync_event(ev)
        except Exception as e:
            grund = fehler_erklaeren(e)
        if ev.kalender_event_id and not grund:
            bericht["events"] += 1
        else:
            bericht["fehler"].append({"titel": titel,
                                      "grund": grund or "Kein Eintrag entstanden."})
    db.commit()

    for r in offene_res:
        bericht["versucht"] += 1
        titel = (f"Reservierung {r.kunde_firma or r.anlass or ''} "
                 f"({r.datum.strftime('%d.%m.%Y')})").replace("  ", " ")
        try:
            ok = sync_reservierung_async(r.id)
        except Exception as e:
            ok = False
            bericht["fehler"].append({"titel": titel, "grund": fehler_erklaeren(e)})
            continue
        if ok:
            bericht["reservierungen"] += 1
        else:
            bericht["fehler"].append({"titel": titel, "grund": "Konnte nicht eingetragen "
                                      "werden – Grund siehe Kalender-Prüfung oben."})

    # Vorgemerkte Löschungen nachholen (Blöcke gelöschter Reservierungen/Events)
    rest, vorgemerkt = [], offene_loeschungen(db)
    for eintrag in vorgemerkt:
        bericht["versucht"] += 1
        erledigt, grund = _kalender_loeschen(eintrag.get("id"), eintrag.get("marke"))
        if erledigt:
            bericht["geloescht"] += 1
        else:
            eintrag["grund"] = grund
            rest.append(eintrag)
            bericht["fehler"].append({"titel": f"Block „{eintrag.get('titel')}“ entfernen",
                                      "grund": grund or "Löschen fehlgeschlagen."})
    if vorgemerkt:
        _loeschungen_speichern(db, rest)
    return bericht


def dienstkonto_adresse() -> str:
    """E-Mail des Dienstkontos – die muss im Google-Kalender freigegeben sein."""
    raw = get_config().get("google_calendar_credentials")
    if not raw:
        return ""
    try:
        info = json.loads(raw) if isinstance(raw, str) else raw
        return info.get("client_email", "")
    except Exception:
        return ""


def _stadt(ort: str) -> str:
    """Stadt aus dem Veranstaltungsort ziehen (nach 5-stelliger PLZ; sonst letztes Segment)."""
    if not ort:
        return ""
    m = re.search(r"\b\d{5}\s+([^,]+)", ort)
    if m:
        return m.group(1).strip()
    return ort.split(",")[-1].strip()


def _kurz_von(aktiv) -> str:
    """Einzel-Kürzel für eine Aktionsliste (ohne Workshop-Logik)."""
    zauber  = any("zaubershow" in p for p in aktiv)
    ballon  = any("ballonmod" in p for p in aktiv)
    schmink = any("schmink" in p for p in aktiv)
    # Aktivität ohne eigenes Einzel-Kürzel (Bastel, Hüpfburg, …)
    andere  = any(not ("zaubershow" in p or "ballonmod" in p or "schmink" in p) for p in aktiv)
    if not andere:
        if zauber and ballon and not schmink:   return "ZB"
        if zauber and not ballon and not schmink: return "Z"
        if ballon and not zauber and not schmink: return "B"
        if schmink and not zauber and not ballon: return "Kischmi."
    return "div."


def _event_art(ev) -> str:
    """Leitet das Kalender-Kürzel aus den gebuchten Aktionen (`ev.produkte` +
    `produkte_freitext`) ab.
    WORKSHOP dominiert in Großbuchstaben, damit es Aykut Tage vorher ins Auge
    springt (er muss dann selbst anwesend sein; ein „(div.)" würde fälschlich
    nach „diverse Aktionen ohne mich" aussehen). Kombinationen zeigen beides:
    (WORKSHOP+Z) / (WORKSHOP+B) / (WORKSHOP+ZB) / (WORKSHOP+Kischmi.);
    Workshop + gemischte Sonstiges bleibt schlicht (WORKSHOP).
    Ohne Workshop: (Z) · (ZB) · (B) · (Kischmi.) · (div.) wie bisher."""
    roh = ", ".join(filter(None, [getattr(ev, "produkte", None) or "",
                                  getattr(ev, "produkte_freitext", None) or ""]))
    produkte = [p.strip().lower() for p in roh.split(",") if p.strip()]
    aktiv = [p for p in produkte if p != "kein material"]   # Marker, keine Aktivität
    workshops = [p for p in aktiv if "workshop" in p]
    rest = [p for p in aktiv if "workshop" not in p]
    if workshops:
        if not rest:
            return "WORKSHOP"
        rk = _kurz_von(rest)
        return "WORKSHOP" if rk == "div." else f"WORKSHOP+{rk}"
    return _kurz_von(aktiv)


def _title(ev) -> str:
    stadt = _stadt(ev.veranstaltungsort)
    kontakt = (ev.kunde_kontakt or "").strip() or (ev.kunde_firma or "").strip()
    rest = ", ".join(p for p in [stadt, ev.anlass, kontakt] if p)
    art = _event_art(ev)
    title = f"({art}) {rest}".strip() if rest else f"({art})"
    if ev.status == "Abgesagt":
        return f"ABGESAGT – {title}"
    return title


def _color_id(ev) -> str:
    if ev.status == "Abgesagt":
        return "4"  # Flamingo
    return "10" if ev.marke == "Knallfrosch" else "7"  # Basil / Peacock – Events sind immer fest


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
    Setzt ev.kalender_event_id – der Aufrufer muss anschließend committen.

    Rückgabe: None bei Erfolg, sonst ein verständlicher Grund. Die bisherigen
    Aufrufer ignorieren das; das Nachtragen braucht es aber – vorher verschwand
    ein Schreibfehler hier wortlos im Log, und „0 nachgetragen" sah aus wie
    „nichts zu tun" (Vorfall 16.09.2026)."""
    svc = _service()
    if not svc:
        return "Keine Verbindung zum Google-Kalender (Zugangsdaten fehlen oder sind ungültig)."
    cid = _calendar_id(ev)
    if not cid:
        return f"Keine Kalender-ID für die Marke {ev.marke or '?'} hinterlegt."
    if not (ev.datum and ev.startzeit and ev.endzeit):
        return "Datum oder Uhrzeit fehlt am Event."
    body = _event_body(ev)
    try:
        if ev.kalender_event_id:
            svc.events().update(calendarId=cid, eventId=ev.kalender_event_id, body=body).execute()
        else:
            created = svc.events().insert(calendarId=cid, body=body).execute()
            ev.kalender_event_id = created.get("id")
        return None
    except Exception as e:
        print(f"Kalender-Sync fehlgeschlagen (Event {ev.id}): {e}")
        return fehler_erklaeren(e)


def fehler_erklaeren(e) -> str:
    """Google-API-Fehler in einen Satz übersetzen, mit dem man etwas anfangen kann."""
    text = str(e)
    if "403" in text and ("writer" in text or "requiredAccessLevel" in text
                          or "forbidden" in text.lower()):
        return ("Das Dienstkonto darf diesen Kalender nur LESEN, nicht beschreiben. "
                "In Google Kalender die Freigabe auf „Änderungen an Terminen vornehmen“ "
                "ändern.")
    if "403" in text:
        return "Zugriff verweigert (403) – Freigabe des Kalenders für das Dienstkonto prüfen."
    if "404" in text or "notFound" in text:
        return ("Kalender nicht gefunden (404) – ist er für das Dienstkonto freigegeben "
                "und stimmt die Kalender-ID?")
    return text.splitlines()[0][:220] if text else "Unbekannter Fehler"


def delete_event(ev):
    """Entfernt den Kalendereintrag. No-op ohne Credentials / ohne ID."""
    delete_event_async(ev.kalender_event_id, ev.marke)


_LOESCH_KEY = "kalender_loeschen_offen"


def _kalender_loeschen(cal_event_id, marke):
    """Einen Kalendereintrag löschen. Rückgabe (erledigt, grund).
    „Schon weg" (404/410) zählt als erledigt – das Ziel ist ja erreicht."""
    svc = _service()
    if not svc:
        return False, "Keine Verbindung zum Google-Kalender."
    cfg = get_config()
    key = "calendar_id_knallfrosch" if marke == "Knallfrosch" else "calendar_id_kindsalabim"
    cid = cfg.get(key)
    if not cid:
        return False, f"Keine Kalender-ID für die Marke {marke or '?'} hinterlegt."
    try:
        svc.events().delete(calendarId=cid, eventId=cal_event_id).execute()
        return True, None
    except Exception as e:
        text = str(e)
        if "404" in text or "410" in text or "notFound" in text or "deleted" in text:
            return True, None
        print(f"Kalender-Löschen fehlgeschlagen: {e}")
        return False, fehler_erklaeren(e)


def delete_event_async(cal_event_id, marke, titel: str = "") -> bool:
    """Löscht per Kalender-Event-ID + Marke (für Hintergrund-Aufrufe ohne ORM-Objekt).

    Scheitert das Löschen, wird der Eintrag VORGEMERKT: Die Aufrufer (Reservierung
    umwandeln/freigeben, Event löschen) haben den Datensatz samt Kalender-ID dann
    schon entfernt – ohne Vormerkung bliebe der Block für immer im Kalender stehen,
    ohne dass die App noch davon weiß (Vorfall 13.–16.09.2026, pinke Blöcke Herten
    und Hohenzollernstraße). `fehlende_nachtragen` holt das Löschen nach."""
    if not cal_event_id:
        return True
    erledigt, grund = _kalender_loeschen(cal_event_id, marke)
    # Ohne konfigurierte Zugangsdaten ist der Kalender schlicht aus (lokal/Tests) –
    # dann gibt es nichts nachzuholen.
    if not erledigt and get_config().get("google_calendar_credentials"):
        _loeschung_vormerken(cal_event_id, marke, titel, grund)
    return erledigt


def _loeschung_vormerken(cal_event_id, marke, titel, grund):
    import json as _json
    from datetime import date as _date
    from database import SessionLocal
    from models import AppEinstellung
    db = SessionLocal()
    try:
        row = db.query(AppEinstellung).filter(AppEinstellung.key == _LOESCH_KEY).first()
        liste = _json.loads(row.value) if row and row.value else []
        if not any(e.get("id") == cal_event_id for e in liste):
            liste.append({"id": cal_event_id, "marke": marke, "titel": titel or "Kalendereintrag",
                          "grund": grund, "seit": _date.today().isoformat()})
        if not row:
            row = AppEinstellung(key=_LOESCH_KEY)
            db.add(row)
        row.value = _json.dumps(liste, ensure_ascii=False)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Kalender-Löschung konnte nicht vorgemerkt werden: {e}")
    finally:
        db.close()


def offene_loeschungen(db) -> list:
    """Kalender-Blöcke, deren Löschen noch aussteht."""
    import json as _json
    from models import AppEinstellung
    row = db.query(AppEinstellung).filter(AppEinstellung.key == _LOESCH_KEY).first()
    try:
        return _json.loads(row.value) if row and row.value else []
    except ValueError:
        return []


def _loeschungen_speichern(db, liste):
    import json as _json
    from models import AppEinstellung
    row = db.query(AppEinstellung).filter(AppEinstellung.key == _LOESCH_KEY).first()
    if not row:
        row = AppEinstellung(key=_LOESCH_KEY)
        db.add(row)
    row.value = _json.dumps(liste, ensure_ascii=False)
    db.commit()


def sync_event_async(event_id):
    """Hintergrund-Sync: eigene DB-Session, lädt Event, synct, committet kalender_event_id.

    Bleibt der Eintrag danach aus, wird das gemeldet – ein stiller Kalender-Ausfall
    fällt sonst erst auf, wenn ein Termin im Alltag fehlt (Vorfall 13.09.2026)."""
    from database import SessionLocal
    from models import Event
    db = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.id == event_id).first()
        if not ev:
            return
        sync_event(ev)
        db.commit()
        if not ev.kalender_event_id:
            _melde_kalender_ausfall(db, f"{ev.anlass or 'Event'} am "
                                        f"{ev.datum.strftime('%d.%m.%Y') if ev.datum else '?'}",
                                    f"/admin/events/{ev.id}", ev.marke)
    except Exception as e:
        print(f"Kalender-Hintergrund-Sync fehlgeschlagen ({event_id}): {e}")
    finally:
        db.close()


def _melde_kalender_ausfall(db, was: str, link: str, marke=None):
    """Eine Glocke, wenn ein Kalendereintrag nicht geschrieben werden konnte.
    Höchstens eine Meldung pro Tag – bei einem Totalausfall sonst eine Flut."""
    from datetime import datetime
    from models import Benachrichtigung
    from notifications import notify
    heute = datetime.now().strftime("%Y-%m-%d")
    schon_heute = db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "kalender_fehler",
        Benachrichtigung.erstellt_am >= heute).first()
    if schon_heute:
        return
    notify(db, "kalender_fehler", "⚠ Kalender-Eintrag fehlt",
           f'„{was}" konnte nicht in den Google-Kalender geschrieben werden. '
           f'Solange das so bleibt, fehlen dort alle neuen Termine. '
           f'Unter Einstellungen → „Kalender-Verbindung prüfen" steht der Grund; '
           f'dort lassen sich fehlende Einträge auch nachtragen.',
           "/admin/kalender-status", marke=marke)
    db.commit()


# ── Reservierungen (anthrazitfarbener Ganztags-Block) ───────────────────────────

def _plus_eine_stunde(zeit: str) -> str:
    """'HH:MM' + 1 Stunde, gedeckelt bei 24:00 (für die Default-Endzeit)."""
    try:
        h, m = (int(x) for x in zeit.split(":"))
    except (ValueError, AttributeError):
        return "24:00"
    h = min(h + 1, 24)
    return f"{h:02d}:{m:02d}" if h < 24 else "24:00"


def _reservierung_body(r) -> dict:
    stadt = _stadt(r.veranstaltungsort or "")
    kontakt = (r.kunde_kontakt or "").strip() or (r.kunde_firma or "").strip()
    art = (r.art or "Div.").strip()
    rest = ", ".join(p for p in [stadt, r.anlass, kontakt] if p)
    summary = f"({art})" + (f" {rest}" if rest else "")
    if r.frist:
        summary += f", reserv. bis {r.frist.strftime('%d.%m.%Y')}"
    lines = []
    if r.kunde_firma:   lines.append(f"Kunde: {r.kunde_firma}")
    if r.kunde_telefon: lines.append(f"Tel: {r.kunde_telefon}")
    if r.kunde_email:   lines.append(f"Mail: {r.kunde_email}")
    if r.frist:         lines.append(f"Rückmeldung bis: {r.frist.strftime('%d.%m.%Y')}")
    if r.notiz:         lines.append(f"Notiz: {r.notiz}")
    lines.append("")
    lines.append("Unverbindliche Reservierung (Kindsalabim-App)")
    heute = datetime.now(ZoneInfo("Europe/Berlin")).date()
    abgelaufen = bool(r.frist and r.frist < heute)
    body = {
        "summary": summary,
        "location": r.veranstaltungsort or "",
        "description": "\n".join(lines),
        "colorId": "4" if abgelaufen else "8",  # Flamingo nach Fristablauf, sonst Anthrazit
    }
    # Zeitgebunden, sobald eine Startzeit gesetzt ist; sonst Ganztags-Fallback
    if r.startzeit:
        ende = r.endzeit if (r.endzeit and r.endzeit > r.startzeit) else _plus_eine_stunde(r.startzeit)
        body["start"] = _dt(r.datum, r.startzeit)
        body["end"] = _dt(r.datum, ende)
    else:
        body["start"] = {"date": r.datum.isoformat()}
        body["end"] = {"date": (r.datum + timedelta(days=1)).isoformat()}
    return body


def sync_reservierung_async(reservierung_id) -> bool:
    """Hintergrund-Sync für eine Reservierung – legt/aktualisiert den Kalender-Block
    (anthrazit; flamingo nach Fristablauf). Gibt True zurück, wenn der Kalender
    tatsächlich aktualisiert wurde (für die Cron-Umfärbung)."""
    from database import SessionLocal
    from models import Reservierung
    db = SessionLocal()
    try:
        r = db.query(Reservierung).filter(Reservierung.id == reservierung_id).first()
        if not r or not r.datum:
            return False
        svc = _service()
        cid = _calendar_id(r)
        if not svc or not cid:
            # Stiller Ausfall – genau das soll nicht mehr unbemerkt bleiben
            _melde_kalender_ausfall(
                db, f"Reservierung {r.kunde_firma or ''} am {r.datum.strftime('%d.%m.%Y')}",
                "/admin/reservierungen", r.marke)
            return False
        body = _reservierung_body(r)
        if r.kalender_event_id:
            svc.events().update(calendarId=cid, eventId=r.kalender_event_id, body=body).execute()
        else:
            created = svc.events().insert(calendarId=cid, body=body).execute()
            r.kalender_event_id = created.get("id")
        db.commit()
        return True
    except Exception as e:
        print(f"Reservierungs-Sync fehlgeschlagen ({reservierung_id}): {e}")
        return False
    finally:
        db.close()
