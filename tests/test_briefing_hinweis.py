# -*- coding: utf-8 -*-
"""Hinweis „Briefing fehlt" auf der Event-Karte im Dashboard.

Aykut hat zweimal vergessen, ein Briefing zu verschicken (09/2026). Monate
vorher ist ein offenes Briefing normal – deshalb erscheint der Hinweis erst in
der letzten Woche vor dem Event.
"""
from datetime import date, timedelta

from factories import make_event

HINWEIS = "Briefing fehlt"


def _event_in(tagen, **kw):
    return make_event(datum=date.today() + timedelta(days=tagen), **kw)


def test_hinweis_erscheint_eine_woche_vorher(admin):
    _event_in(3, kunde_firma="Briefing Bald GmbH")
    r = admin.get("/admin/dashboard")
    assert r.status_code == 200
    assert HINWEIS in r.text


def test_hinweis_genau_am_siebten_tag_noch_da(admin):
    _event_in(7, kunde_firma="Briefing Grenze GmbH")
    assert HINWEIS in admin.get("/admin/dashboard").text


def test_kein_hinweis_wenn_das_event_weit_weg_ist(admin, db):
    """Einzeln geprüft: sonst könnte ein anderes Event den Hinweis erzeugen."""
    from models import Event
    for ev in db.query(Event).all():          # Test-DB wird nicht zurückgesetzt
        ev.briefing_gesendet_am = "2026-01-01T10:00:00"
    db.commit()
    _event_in(30, kunde_firma="Briefing Fern GmbH")
    assert HINWEIS not in admin.get("/admin/dashboard").text


def test_kein_hinweis_wenn_das_briefing_raus_ist(admin, db):
    from models import Event
    for ev in db.query(Event).all():
        ev.briefing_gesendet_am = "2026-01-01T10:00:00"
    db.commit()
    _event_in(2, kunde_firma="Briefing Raus GmbH",
              briefing_gesendet_am="2026-09-01T10:00:00")
    assert HINWEIS not in admin.get("/admin/dashboard").text


def test_alter_stand_ohne_zeitstempel_zaehlt_als_verschickt(admin, db):
    """Events von vor der Einführung des Zeitstempels: Status entscheidet."""
    from models import Event
    for ev in db.query(Event).all():
        ev.briefing_gesendet_am = "2026-01-01T10:00:00"
    db.commit()
    _event_in(2, kunde_firma="Briefing Alt GmbH", status="Briefing gesendet")
    assert HINWEIS not in admin.get("/admin/dashboard").text
