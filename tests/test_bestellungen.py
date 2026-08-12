"""Bestellungen am Event: Beträge sammeln, Summe anzeigen, und die Summe als
Materialkosten-Vorschlag im Neue-Rechnung-Formular der Buchhaltung anbieten."""
from datetime import date, timedelta

from database import SessionLocal
from factories import make_event
from models import EventBestellung


def test_bestellung_anlegen_summe_und_loeschen(admin):
    eid = make_event(datum=date.today() + timedelta(days=14))
    r = admin.post(f"/admin/events/{eid}/bestellungen",
                   data={"bezeichnung": "Baker Ross Sets", "betrag": "123,45"},
                   follow_redirects=False)
    assert r.status_code == 303
    admin.post(f"/admin/events/{eid}/bestellungen",
               data={"bezeichnung": "Deko", "betrag": "26,55"}, follow_redirects=False)
    h = admin.get(f"/admin/events/{eid}").text
    assert "Baker Ross Sets" in h and "Materialkosten gesamt" in h
    assert "150,00" in h                                   # 123,45 + 26,55

    s = SessionLocal()
    try:
        b = s.query(EventBestellung).filter_by(event_id=eid).order_by(EventBestellung.id).first()
        assert b.betrag == 123.45
        bid = b.id
    finally:
        s.close()
    admin.post(f"/admin/events/{eid}/bestellungen/{bid}/delete", follow_redirects=False)
    s = SessionLocal()
    try:
        assert s.query(EventBestellung).filter_by(event_id=eid).count() == 1
    finally:
        s.close()


def test_leere_bezeichnung_wird_ignoriert(admin):
    eid = make_event(datum=date.today() + timedelta(days=14))
    admin.post(f"/admin/events/{eid}/bestellungen",
               data={"bezeichnung": "   ", "betrag": "50"}, follow_redirects=False)
    s = SessionLocal()
    try:
        assert s.query(EventBestellung).filter_by(event_id=eid).count() == 0
    finally:
        s.close()


def test_buchhaltung_bietet_event_vorschlag(admin):
    eid = make_event(datum=date.today() - timedelta(days=3), kunde_firma="Materialkunde GmbH")
    admin.post(f"/admin/events/{eid}/bestellungen",
               data={"bezeichnung": "Bastelmaterial", "betrag": "99,90"}, follow_redirects=False)
    h = admin.get("/admin/buchhaltung").text
    assert "Aus Event übernehmen" in h
    assert "Materialkunde GmbH" in h
    assert 'data-material="99,90"' in h
