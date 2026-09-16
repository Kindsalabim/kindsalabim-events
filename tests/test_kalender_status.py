"""Kalender-Verbindung: Diagnose, Nachtragen, Glocke bei stillem Ausfall.

Hintergrund (13.09.2026): Die Google-Kalender-Verbindung war ausgefallen. Weder
das Umwandeln einer Reservierung noch neue Reservierungen landeten im Kalender –
gemerkt hat es niemand, weil alle Fehlerpfade nur in die Render-Logs schrieben.
Für Aykut ist der Kalender die Arbeitsfläche: Ein Termin, den nur die App kennt,
existiert im Alltag nicht.
"""
from datetime import date, timedelta

import calendar_service
from database import SessionLocal
from models import Benachrichtigung, Event, Reservierung
from factories import make_event


# ── Diagnose ─────────────────────────────────────────────────────────────────

def test_diagnose_meldet_fehlende_zugangsdaten(monkeypatch):
    monkeypatch.setattr(calendar_service, "get_config", lambda: {})
    d = calendar_service.diagnose()
    assert d["ok"] is False
    assert "Zugangsdaten" in d["meldung"]


def test_diagnose_meldet_fehlende_kalender_id(monkeypatch):
    monkeypatch.setattr(calendar_service, "get_config",
                        lambda: {"google_calendar_credentials": "{}",
                                 "calendar_id_kindsalabim": "a@b.de"})
    monkeypatch.setattr(calendar_service, "_service", lambda: object())
    d = calendar_service.diagnose()
    knallfrosch = [k for k in d["kalender"] if k["marke"] == "Knallfrosch"][0]
    assert knallfrosch["ok"] is False and "Kalender-ID" in knallfrosch["detail"]


def test_status_seite_erreichbar(admin):
    r = admin.get("/admin/kalender-status")
    assert r.status_code == 200
    assert "Kalender-Verbindung" in r.text


# ── Glocke bei stillem Ausfall ───────────────────────────────────────────────

def _kalender_glocken_leeren(db):
    """Die Test-DB ist über die ganze Sitzung geteilt – die Tagessperre der Glocke
    würde sonst je nach Testreihenfolge greifen oder nicht."""
    db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "kalender_fehler").delete(synchronize_session=False)
    db.commit()


def _kalender_glocken(db):
    db.expire_all()
    return db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "kalender_fehler").count()


def test_glocke_wenn_eintrag_nicht_geschrieben_wird(db, monkeypatch):
    """Ohne Kalender-Verbindung bleibt kalender_event_id leer – das muss melden."""
    _kalender_glocken_leeren(db)
    monkeypatch.setattr(calendar_service, "_service", lambda: None)
    calendar_service.sync_event_async(make_event(datum=date.today() + timedelta(days=5)))
    assert _kalender_glocken(db) == 1


def test_glocke_nur_einmal_pro_tag(db, monkeypatch):
    """Bei einem Totalausfall sonst eine Meldungsflut."""
    _kalender_glocken_leeren(db)
    monkeypatch.setattr(calendar_service, "_service", lambda: None)
    calendar_service.sync_event_async(make_event(datum=date.today() + timedelta(days=6)))
    calendar_service.sync_event_async(make_event(datum=date.today() + timedelta(days=7)))
    assert _kalender_glocken(db) == 1


# ── Nachtragen ───────────────────────────────────────────────────────────────

def test_nachtragen_erfasst_nur_was_fehlt(db, monkeypatch):
    """Bestehende Einträge bleiben unberührt, Abgesagtes wird übersprungen."""
    offen = make_event(datum=date.today() + timedelta(days=9))
    schon_da = make_event(datum=date.today() + timedelta(days=10),
                          kalender_event_id="bereits-vorhanden")
    abgesagt = make_event(datum=date.today() + timedelta(days=11), status="Abgesagt")

    gesynct = []

    def _sync_ok(ev):
        gesynct.append(ev.id)
        ev.kalender_event_id = f"neu-{ev.id}"
        return None                                  # None = Erfolg

    monkeypatch.setattr(calendar_service, "sync_event", _sync_ok)
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: False)

    s = SessionLocal()
    try:
        bericht = calendar_service.fehlende_nachtragen(s)
    finally:
        s.close()
    assert offen in gesynct
    assert schon_da not in gesynct          # hat schon einen Eintrag
    assert abgesagt not in gesynct          # abgesagte Events gehören nicht in den Kalender
    assert bericht["events"] >= 1


def test_nachtragen_zaehlt_reservierungen(db, monkeypatch):
    s = SessionLocal()
    try:
        r = Reservierung(datum=date.today() + timedelta(days=12), startzeit="11:00",
                         endzeit="11:45", art="Div.", anlass="Vorlesetag",
                         kunde_firma="Stadt Herten", marke="Kindsalabim")
        s.add(r); s.commit()
        monkeypatch.setattr(calendar_service, "sync_event", lambda ev: None)
        monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
        bericht = calendar_service.fehlende_nachtragen(s)
        assert bericht["reservierungen"] >= 1
    finally:
        s.close()


# ── Vorfall 16.09.2026: Lesen klappt, Schreiben nicht ────────────────────────

GOOGLE_403 = ('<HttpError 403 when requesting https://www.googleapis.com/calendar/v3/'
              'calendars/x/events returned "You need to have writer access to this '
              'calendar.". Details: "[{\'domain\': \'calendar\', \'reason\': '
              '\'requiredAccessLevel\'}]">')


def test_schreibverbot_wird_verstaendlich_erklaert():
    grund = calendar_service.fehler_erklaeren(Exception(GOOGLE_403))
    assert "nur LESEN" in grund and "Änderungen an Terminen vornehmen" in grund


def test_nachtragen_meldet_schreibfehler_mit_grund(db, monkeypatch):
    """Vorher: „0 nachgetragen, 0 Fehler" – weil sync_event den Fehler schluckte."""
    make_event(datum=date.today() + timedelta(days=13), kunde_firma="FUNKE Medien NRW")

    class _Kaputt:
        def events(self):
            return self

        def insert(self, **kw):
            return self

        def execute(self):
            raise Exception(GOOGLE_403)

    monkeypatch.setattr(calendar_service, "_service", lambda: _Kaputt())
    monkeypatch.setattr(calendar_service, "get_config",
                        lambda: {"calendar_id_kindsalabim": "k@x.de",
                                 "calendar_id_knallfrosch": "f@x.de"})
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
    s = SessionLocal()
    try:
        bericht = calendar_service.fehlende_nachtragen(s)
    finally:
        s.close()
    funke = [f for f in bericht["fehler"] if "FUNKE" in f["titel"]]
    assert funke, "Schreibfehler wurde nicht gemeldet"
    assert "nur LESEN" in funke[0]["grund"]


def test_diagnose_erkennt_reine_lesefreigabe(monkeypatch):
    """calendars().get() klappt auch mit Leserecht – die Rolle muss geprüft werden."""
    class _NurLesen:
        def __init__(self):
            self._antwort = {}

        def calendars(self):
            self._antwort = {"summary": "Kindsalabim"}
            return self

        def calendarList(self):
            self._antwort = {"accessRole": "reader"}
            return self

        def get(self, **kw):
            return self

        def execute(self):
            return self._antwort

    monkeypatch.setattr(calendar_service, "get_config",
                        lambda: {"google_calendar_credentials": "{}",
                                 "calendar_id_kindsalabim": "k@x.de",
                                 "calendar_id_knallfrosch": "f@x.de"})
    monkeypatch.setattr(calendar_service, "_service", lambda: _NurLesen())
    d = calendar_service.diagnose()
    assert d["ok"] is False
    assert all("nur LESBAR" in k["detail"] for k in d["kalender"])


def test_statusseite_listet_fehlende_mit_namen(admin, db):
    make_event(datum=date.today() + timedelta(days=14), kunde_firma="Sichtbar im Status GmbH")
    html = admin.get("/admin/kalender-status").text
    assert "Sichtbar im Status GmbH" in html


def test_nachtragen_zeigt_grund_auf_der_seite(admin, db, monkeypatch):
    make_event(datum=date.today() + timedelta(days=15), kunde_firma="Grund-Anzeige AG")
    monkeypatch.setattr(calendar_service, "sync_event",
                        lambda ev: calendar_service.fehler_erklaeren(Exception(GOOGLE_403)))
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
    html = admin.post("/admin/kalender-status/nachtragen").text
    assert "konnten nicht in den Kalender geschrieben werden" in html
    assert "nur LESEN" in html
    assert "Grund-Anzeige AG" in html
