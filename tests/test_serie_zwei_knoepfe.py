"""Serien-Anfrage: zwei Knöpfe statt Häkchen (Aykut 24.11.2026) – vorher wurden
versehentlich alle Termine angefragt, weil das Häkchen oben vorgewählt war."""
from datetime import date

from database import SessionLocal
from models import Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister


def test_zwei_knoepfe_mit_daten_kein_haekchen(admin):
    t1 = make_event(datum=date(2026, 12, 12), serien_id="serie-knopf")
    make_event(datum=date(2026, 12, 13), serien_id="serie-knopf")
    html = admin.get(f"/admin/events/{t1}").text
    assert "Nur für diesen Termin anfragen (Sa 12.12.)" in html
    assert "Für alle 2 Termine anfragen (Sa 12.12. + So 13.12.)" in html
    assert "der Serie anfragen" not in html


def test_ohne_serie_ein_knopf(admin):
    eid = make_event()
    html = admin.get(f"/admin/events/{eid}").text
    assert 'data-normal="Anfragen senden"' in html
    assert "Nur für diesen Termin" not in html


def test_viele_termine_zeigen_zeitraum(admin):
    ids = [make_event(datum=date(2026, 12, d), serien_id="serie-lang") for d in (10, 11, 12, 13)]
    html = admin.get(f"/admin/events/{ids[0]}").text
    assert "Für alle 4 Termine anfragen (10.12.–13.12.)" in html


def test_nur_dieser_termin_fragt_nur_einen_tag_an(admin):
    t1 = make_event(datum=date(2026, 12, 12), serien_id="serie-einzel")
    t2 = make_event(datum=date(2026, 12, 13), serien_id="serie-einzel")
    did = make_dienstleister()
    admin.post(f"/admin/events/{t1}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Teamer", "direkt": "1"})
    s = SessionLocal()
    assert s.query(Verfuegbarkeitsanfrage).filter_by(event_id=t1, dienstleister_id=did).count() == 1
    assert s.query(Verfuegbarkeitsanfrage).filter_by(event_id=t2, dienstleister_id=did).count() == 0
    s.close()
