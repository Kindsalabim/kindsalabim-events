"""Logistiker-Warnung im Event-Detail: ein manuell zugewiesener Logistiker
(ev.logistiker_id) zählt genauso wie ein per Anfrage zugesagter – die Warnung
darf dann nicht mehr erscheinen (Bug 27.07.2026)."""
from datetime import date, timedelta

from factories import make_event, make_dienstleister, make_anfrage

BALD = date.today() + timedelta(days=20)


def test_warnung_wenn_material_aber_kein_logistiker(admin):
    eid = make_event(datum=BALD, material_mitnahme=True)
    r = admin.get(f"/admin/events/{eid}")
    assert "Logistiker fehlt" in r.text


def test_keine_warnung_bei_manuell_zugewiesenem_logistiker(admin):
    # Künstlerin ohne Logistiker-Flag, nach Absprache manuell eingetragen
    did = make_dienstleister(rolle="Künstler")
    eid = make_event(datum=BALD, material_mitnahme=True, logistiker_id=did)
    r = admin.get(f"/admin/events/{eid}")
    assert "Logistiker fehlt" not in r.text


def test_keine_warnung_bei_zugesagtem_logistiker(admin):
    did = make_dienstleister(logistiker=True)
    eid = make_event(datum=BALD, material_mitnahme=True)
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    r = admin.get(f"/admin/events/{eid}")
    assert "Logistiker fehlt" not in r.text


def test_keine_warnung_ohne_material(admin):
    eid = make_event(datum=BALD, material_mitnahme=False)
    r = admin.get(f"/admin/events/{eid}")
    assert "Logistiker fehlt" not in r.text
