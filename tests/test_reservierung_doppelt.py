"""Reservierung ↔ Event doppelt (Funke-Fall 16.09.2026): Buchung als neues Event
angelegt statt die Reservierung umzuwandeln → Reservierung lief ab und stand pink
neben dem echten Event im Kalender. Kalender-Aufrufe sind gemockt."""
from datetime import date, timedelta

import calendar_service
from database import SessionLocal
from factories import make_event, reload
from models import Benachrichtigung, Reservierung
from reservierung_abgleich import passt
from routes.cron import _run_reservierung_farben
from test_reservierung import _make_res

GESTERN = date.today() - timedelta(days=1)


def test_namensabgleich():
    assert passt("Funke Mediengruppe", "FUNKE Medien NRW")
    assert passt("Kita Hohenzollernstraße", "Städt. Kita Hohenzollernstrasse")
    assert not passt("Kita Hohenzollernstraße", "Kita Blumenweg")
    assert not passt("Familie Otto", "Familie Schmidt")
    assert not passt("", "Funke")


def test_event_seite_zeigt_passende_reservierung(admin):
    tag = date.today() + timedelta(days=40)
    eid = make_event(datum=tag, kunde_firma="FUNKE Medien NRW")
    rid = _make_res(datum=tag, kunde_firma="Funke Mediengruppe")
    _make_res(datum=tag, kunde_firma="Kita Blumenweg")          # anderer Kunde
    _make_res(datum=tag + timedelta(days=1), kunde_firma="Funke Mediengruppe")  # anderer Tag
    html = admin.get(f"/admin/events/{eid}").text
    assert html.count("Offene Reservierung") == 1
    assert f"/admin/reservierungen/{rid}/freigeben" in html


def test_aufloesen_fuehrt_zurueck_zum_event(admin, monkeypatch):
    geloescht = []
    monkeypatch.setattr(calendar_service, "delete_event_async",
                        lambda *a, **kw: geloescht.append(a) or True)
    tag = date.today() + timedelta(days=41)
    eid = make_event(datum=tag, kunde_firma="Auflöse-Test AG")
    rid = _make_res(datum=tag, kunde_firma="Auflöse-Test")
    s = SessionLocal()
    try:
        s.get(Reservierung, rid).kalender_event_id = "block-1"
        s.commit()
    finally:
        s.close()
    r = admin.post(f"/admin/reservierungen/{rid}/freigeben",
                   data={"zurueck": f"/admin/events/{eid}"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/events/{eid}"
    assert reload(Reservierung, rid) is None
    assert geloescht and geloescht[0][0] == "block-1"


def test_aufloesen_ignoriert_fremde_ruecksprungadresse(admin, monkeypatch):
    monkeypatch.setattr(calendar_service, "delete_event_async", lambda *a, **kw: True)
    rid = _make_res(kunde_firma="Umleitung GmbH")
    r = admin.post(f"/admin/reservierungen/{rid}/freigeben",
                   data={"zurueck": "https://boese.example"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/reservierungen"


def test_cron_faerbt_nicht_um_sondern_meldet_einmal(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(calendar_service, "sync_reservierung_async",
                        lambda i: aufrufe.append(i) or True)
    make_event(datum=GESTERN + timedelta(days=20), kunde_firma="Doppelmeldung Werke")
    rid = _make_res(datum=GESTERN + timedelta(days=20), frist=GESTERN,
                    kunde_firma="Doppelmeldung Werke GmbH")
    s = SessionLocal()
    try:
        s.get(Reservierung, rid).kalender_event_id = "block-2"
        s.commit()
        _run_reservierung_farben(s)
        _run_reservierung_farben(s)
        meldungen = s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "reservierung_doppelt",
            Benachrichtigung.titel.contains("Doppelmeldung Werke")).count()
    finally:
        s.close()
    assert rid not in aufrufe
    assert meldungen == 1
