"""Roadmap 3.3 – Abgelaufene Verfügbarkeitsanfragen automatisch markieren + Büro benachrichtigen.

Deckt ab: Markierung nur für kommende/aktive Events, Idempotenz, Glocken-Meldung je Event,
Soft-Frist (Portal zeigt sie weiter, verspätete Antwort + Frist-Verlängerung reaktivieren)."""
from datetime import date, timedelta

from models import Verfuegbarkeitsanfrage, Benachrichtigung
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login
from database import SessionLocal

GESTERN = date.today() - timedelta(days=1)
BALD = date.today() + timedelta(days=14)


def _run():
    s = SessionLocal()
    try:
        from routes.cron import _run_abgelaufene_anfragen
        return _run_abgelaufene_anfragen(s)
    finally:
        s.close()


def _notif_count():
    s = SessionLocal()
    try:
        return s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "anfrage_abgelaufen").count()
    finally:
        s.close()


def test_abgelaufene_anfrage_wird_markiert_und_meldet():
    eid = make_event(datum=BALD)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=GESTERN)
    vorher = _notif_count()
    n = _run()
    assert n == 1
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Abgelaufen"
    assert _notif_count() == vorher + 1


def test_frist_in_zukunft_bleibt_ausstehend():
    eid = make_event(datum=BALD)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend",
                       frist_datum=date.today() + timedelta(days=2))
    _run()
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ausstehend"


def test_vergangenes_event_wird_nicht_angefasst():
    eid = make_event(datum=GESTERN)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=GESTERN)
    _run()
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ausstehend"


def test_abgesagtes_event_wird_nicht_angefasst():
    eid = make_event(datum=BALD, status="Abgesagt")
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=GESTERN)
    _run()
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ausstehend"


def test_beantwortete_anfrage_bleibt_unveraendert():
    eid = make_event(datum=BALD)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja", frist_datum=GESTERN)
    _run()
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"


def test_eine_meldung_je_event_und_idempotent():
    eid = make_event(datum=BALD)
    d1, d2 = make_dienstleister(), make_dienstleister()
    make_anfrage(eid, d1, status="Ausstehend", frist_datum=GESTERN)
    make_anfrage(eid, d2, status="Ausstehend", frist_datum=GESTERN)
    vorher = _notif_count()
    n1 = _run()
    assert n1 == 2                       # beide Anfragen markiert
    assert _notif_count() == vorher + 1  # aber nur EINE Sammel-Meldung
    n2 = _run()                          # zweiter Lauf findet nichts mehr
    assert n2 == 0
    assert _notif_count() == vorher + 1


def test_portal_zeigt_abgelaufene_und_verspaetete_zusage_geht(client):
    eid = make_event(datum=BALD)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=GESTERN)
    _run()
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Abgelaufen"
    portal_login(client, did)
    r = client.get("/portal")
    assert r.status_code == 200 and "Frist abgelaufen" in r.text
    # verspätete Zusage ist weiterhin möglich
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"


def test_frist_verlaengern_reaktiviert_abgelaufene_anfrage(client):
    eid = make_event(datum=BALD)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=GESTERN)
    _run()
    portal_login(client, did)
    client.post(f"/portal/verlaengern/{aid}", follow_redirects=False)
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.status == "Ausstehend"
    assert a.frist_datum > date.today()
    assert a.frist_verlaengert is True
