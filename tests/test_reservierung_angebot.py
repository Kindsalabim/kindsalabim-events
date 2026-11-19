"""Angebot mit Mr.-Magic-Programm verschickt → Reservierung (Aykut 19.11.2026).

Wenn ein Geschäftskunde eine Zaubershow anfragt und das Angebot rausgeht, muss der
Termin im Kalender reserviert sein, sonst droht eine Doppelbuchung (Fall Sevenich).
Reine Div.-Angebote (Kinderschminken, Tattoos, Basteln) meldet der Assistent gar
nicht erst – dafür findet sich immer Personal.

Vertrag: C:\\Users\\aykut\\Claude\\Austausch\\Schnittstellen\\SCHNITTSTELLEN.md, 2.2/2.3.
"""
from datetime import date, timedelta

from factories import make_event
from models import Reservierung, Verbindungslog

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}
TAG = date.today() + timedelta(days=90)
FRIST = TAG - timedelta(days=5)


def _mit_secret(monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})


def _angebot(admin, **daten):
    daten.setdefault("datum", TAG.isoformat())
    daten.setdefault("startzeit", "14:00")
    daten.setdefault("endzeit", "15:00")
    daten.setdefault("frist", FRIST.isoformat())
    daten.setdefault("ag_nummer", "AG1246")
    return admin.post("/admin/crm/api/reservierung/angebot", headers=GEHEIM, json=daten)


def test_reservierung_wird_angelegt(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    r = _angebot(admin, firma="Sevenich GmbH", empfaenger="info@sevenich.example",
                kontakt="Herr Sevenich", telefon="0201 123", ort="Markt 1, 45127 Essen",
                anlass="Firmenfeier", art="Z")
    assert r.status_code == 200
    j = r.json()
    assert j["ergebnis"] == "angelegt" and j["frist"] == FRIST.isoformat()
    db.expire_all()
    res = db.query(Reservierung).filter(Reservierung.id == j["reservierung_id"]).one()
    assert res.datum == TAG and res.kunde_firma == "Sevenich GmbH"
    assert res.kunde_email == "info@sevenich.example" and res.art == "Z"
    assert res.frist == FRIST and res.marke == "Kindsalabim"
    assert res.notiz == "Angebot AG1246"


def test_art_ohne_angabe_wird_z(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    r = _angebot(admin, firma="Ohne Art GmbH", empfaenger="info@ohne-art.example")
    db.expire_all()
    res = db.query(Reservierung).filter(Reservierung.id == r.json()["reservierung_id"]).one()
    assert res.art == "Z"


def test_zweiter_versand_meldet_schon_reserviert(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    _angebot(admin, firma="Doppelt GmbH", empfaenger="info@doppelt.example")
    r = _angebot(admin, firma="Doppelt GmbH", empfaenger="info@doppelt.example")
    assert r.json() == {"ergebnis": "schon_reserviert"}
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.kunde_firma == "Doppelt GmbH").count() == 1


def test_firmen_domain_reicht_als_treffer(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    _angebot(admin, firma="Domain Treffer GmbH", empfaenger="info@domain-treffer.example")
    r = _angebot(admin, firma="Anders geschrieben", empfaenger="m.mueller@domain-treffer.example")
    assert r.json() == {"ergebnis": "schon_reserviert"}


def test_schon_gebuchtes_event_meldet_schon_gebucht(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    make_event(datum=TAG, kunde_firma="Schon Gebucht GmbH", kunde_email="info@schon-gebucht.example")
    r = _angebot(admin, firma="Schon Gebucht GmbH", empfaenger="info@schon-gebucht.example")
    assert r.json() == {"ergebnis": "schon_gebucht"}
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.kunde_firma == "Schon Gebucht GmbH").count() == 0


def test_fehlerfaelle(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    assert admin.post("/admin/crm/api/reservierung/angebot",
                      json={"datum": TAG.isoformat()}).status_code == 401
    assert _angebot(admin, datum="nächsten Samstag").status_code == 422
    assert _angebot(admin, startzeit="").status_code == 422
    assert _angebot(admin, endzeit="irgendwann").status_code == 422
    assert _angebot(admin, frist="").status_code == 422
    vergangen = date.today() - timedelta(days=1)
    r = _angebot(admin, datum=vergangen.isoformat())
    assert r.status_code == 422 and "Vergangenheit" in r.json()["detail"]


def test_monitor_schluessel_kollidiert_nicht_mit_vertrieb_angebot(admin, db, monkeypatch):
    """/reservierung/angebot und /vertrieb/angebot enden beide auf "angebot" – je
    eigene Ampel im Verbindungs-Monitor (1.5)."""
    _mit_secret(monkeypatch)
    from models import Kunde
    k = Kunde(firma="Monitor Test GmbH", email="info@monitor-test.example", herkunft="akquise",
             pipeline_status="lead")
    db.add(k); db.commit()
    admin.post("/admin/crm/api/vertrieb/angebot", headers=GEHEIM,
              json={"kunde_id": str(k.id), "betreff": "x", "empfaenger": k.email})
    _angebot(admin, firma="Monitor Test GmbH", empfaenger="info@monitor-reservierung.example")
    db.expire_all()
    assert db.query(Verbindungslog).filter(
        Verbindungslog.schnittstelle == "assistent.angebot").count() >= 1
    assert db.query(Verbindungslog).filter(
        Verbindungslog.schnittstelle == "assistent.reservierung").count() >= 1
