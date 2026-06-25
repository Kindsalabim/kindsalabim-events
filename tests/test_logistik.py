"""Logistiker-Workflow: Anfrage-Flag, Portal-Transportantwort, Zuweisung, auto_status, Material-bereit."""
from datetime import date, timedelta

from models import Event, Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login
from routes.admin import auto_status
from database import SessionLocal


def test_anfrage_als_logistiker_flag(admin):
    eid = make_event(material_mitnahme=True)
    did = make_dienstleister()
    r = admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "logistiker_ids": [str(did)],
        "rolle": "Teamer", "direkt": "1"}, follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    a = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=eid, dienstleister_id=did).first()
    assert a.als_logistiker is True
    s.close()


def test_portal_antwort_eigenes_auto_setzt_logistiker(client):
    eid = make_event(material_mitnahme=True, transporter_angeboten=True)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", als_logistiker=True)
    portal_login(client, did)
    r = client.post(f"/portal/antwort/{aid}", data={"antwort": "ja_auto"}, follow_redirects=False)
    assert r.status_code == 303
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.status == "Ja" and a.logistik_transport == "eigenes_auto"
    assert reload(Event, eid).logistiker_id == did


def test_portal_antwort_ohne_material_setzt_keinen_logistiker(client):
    eid = make_event(material_mitnahme=True)
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ausstehend", als_logistiker=True)
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "ja_ohne"}, follow_redirects=False)
    assert reload(Verfuegbarkeitsanfrage, aid).logistik_transport == "ohne"
    assert reload(Event, eid).logistiker_id is None


def test_auto_status_logistiker_erfuellt_check():
    eid = make_event(material_mitnahme=True, material_bestellt=True, checkliste_uebersprungen=True,
                     anzahl_teamer=1)
    did = make_dienstleister()
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    s = SessionLocal()
    ev = s.get(Event, eid)
    assert auto_status(ev, s) != "Planung fertig"   # ohne Logistiker
    ev.logistiker_id = did
    s.commit()
    assert auto_status(ev, s) == "Planung fertig"    # mit Logistiker
    s.close()


def test_material_bereit_ohne_logistiker_fehler(admin):
    eid = make_event(material_mitnahme=True)
    r = admin.post(f"/admin/events/{eid}/material-bereit", follow_redirects=False)
    assert "error=kein_logistiker" in r.headers["location"]
    assert reload(Event, eid).material_bereit is False


def test_material_bereit_setzt_flag(admin):
    did = make_dienstleister(email="log@example.com")
    eid = make_event(material_mitnahme=True, logistiker_id=did)
    r = admin.post(f"/admin/events/{eid}/material-bereit", follow_redirects=False)
    assert r.status_code == 303
    ev = reload(Event, eid)
    assert ev.material_bereit is True and ev.material_bereit_gesendet is True


def test_cron_material_abhol_erinnerung():
    from routes.cron import _run_material_abhol_erinnerungen
    did = make_dienstleister(email="fahrer@example.com")
    eid = make_event(datum=date.today() + timedelta(days=3), material_mitnahme=True,
                     logistiker_id=did, status="Planung fertig")
    s = SessionLocal()
    n = _run_material_abhol_erinnerungen(s)
    s.close()
    assert n >= 1
    assert reload(Event, eid).material_abhol_erinnerung_gesendet is True
