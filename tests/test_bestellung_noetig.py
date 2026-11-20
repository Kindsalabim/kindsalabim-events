"""Bestellbedarf (Aykut 21.11.2026): „Bestellung nötig“ gilt bei Material-Mitnahme ODER
einer gebuchten Material-Aktion; ein Hand-Schalter kann es in beide Richtungen übersteuern.
Gilt für Workflow-Leiste, „Planung fertig“ und die 3-Wochen-Bestell-Erinnerung."""
from datetime import date, timedelta

import routes.cron as cron
import ingest_bakerross
from database import SessionLocal
from models import Event
from routes.admin import auto_status, _workflow_steps
from factories import make_event, make_dienstleister, make_anfrage, reload

HEUTE = date.today()


def _ev(**kw):
    return Event(anlass="X", produkte=kw.pop("produkte", "Kinderschminken"), **kw)


def test_material_aktion_macht_bestellung_noetig():
    ev = _ev(produkte="Kinderschminken, Bastelaktion")
    assert ev.bestellung_noetig is True
    assert ev.bestellung_grund_auto == "Bastelaktion gebucht"


def test_alle_vereinbarten_aktionen():
    for p in ("Bastelaktion", "Buttonmaschine", "Prickeln", "Knusperhäuschen",
              "Lebkuchenherzen", "Fotoaktion"):
        assert _ev(produkte=p).bestellung_noetig is True, p


def test_bewusst_ausgenommene_aktionen():
    for p in ("Bunter Bastelspaß", "Bastelspaß Weihnachten", "Glitzertattoos", "Kinderschminken"):
        assert _ev(produkte=p).bestellung_noetig is False, p


def test_material_mitnahme_macht_bestellung_noetig():
    ev = _ev(material_mitnahme=True)
    assert ev.bestellung_noetig is True
    assert ev.bestellung_grund_auto == "Material-Mitnahme angehakt"


def test_hand_schalter_in_beide_richtungen():
    assert _ev(bestellung_manuell="ja").bestellung_noetig is True
    assert _ev(produkte="Bastelaktion", bestellung_manuell="nein").bestellung_noetig is False


def test_workflow_zeigt_bestellung_offen_bei_bastelaktion():
    ev = _ev(produkte="Bastelaktion", anzahl_teamer=0, anzahl_kuenstler=0)
    schritt = [s for s in _workflow_steps(ev, [], externe_n=0) if s["key"] == "bestellungen"][0]
    assert schritt["state"] == "todo" and schritt["target"] == "bestellungen"


def test_planung_fertig_wartet_auf_bestellung_bei_bastelaktion():
    eid = make_event(produkte="Bastelaktion", checkliste_uebersprungen=True, anzahl_teamer=1)
    make_anfrage(eid, make_dienstleister(), status="Ja", rolle="Teamer")
    s = SessionLocal()
    ev = s.get(Event, eid)
    assert auto_status(ev, s) != "Planung fertig"
    ev.material_bestellt = True
    s.commit()
    assert auto_status(ev, s) == "Planung fertig"
    s.close()


def test_schalter_route_setzt_und_setzt_zurueck(admin):
    eid = make_event(produkte="Bastelaktion")
    r = admin.post(f"/admin/events/{eid}/bestellung-manuell", data={"wert": "nein"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#bestellungen")
    assert reload(Event, eid).bestellung_manuell == "nein"
    admin.post(f"/admin/events/{eid}/bestellung-manuell", data={"wert": ""})
    assert reload(Event, eid).bestellung_manuell is None
    admin.post(f"/admin/events/{eid}/bestellung-manuell", data={"wert": "quatsch"})
    assert reload(Event, eid).bestellung_manuell is None


def test_detailseite_zeigt_grund_und_knopf(admin):
    eid = make_event(produkte="Buttonmaschine")
    html = admin.get(f"/admin/events/{eid}").text
    assert "Bestellung nötig" in html and "Buttonmaschine gebucht" in html
    assert "Als bestellt markieren" in html
    assert "Für dieses Event keine Bestellung nötig" in html


def test_erinnerung_auch_ohne_mitnahme_bei_material_aktion(client, monkeypatch, mails):
    monkeypatch.setattr(cron, "get_config", lambda: {"cron_secret": "bn-secret", "admin_email": "a@b.de"})
    monkeypatch.setattr(ingest_bakerross, "ingest_catalog", lambda db: "test-skip")
    mit = make_event(datum=HEUTE + timedelta(days=10), produkte="Lebkuchenherzen")
    ohne = make_event(datum=HEUTE + timedelta(days=10), produkte="Lebkuchenherzen",
                      bestellung_manuell="nein")
    r = client.get("/cron/erinnerung", headers={"X-Cron-Secret": "bn-secret"})
    assert r.status_code == 200
    assert reload(Event, mit).material_erinnerung_gesendet is True
    assert reload(Event, ohne).material_erinnerung_gesendet is False
