"""Kundenschutz aus Agenturverträgen (Aykut 27.10.2026): Eine Sperre kann ein Ablaufdatum
haben. Bis einschließlich zu diesem Tag wird die Firma nicht angeschrieben, danach wieder.
30 Tage vorher meldet sich die Glocke einmal."""
from datetime import timedelta

import vertrieb
from models import Benachrichtigung, VertriebSperre
from routes import cron


def _sperre(db, ebene, wert):
    return db.query(VertriebSperre).filter(VertriebSperre.ebene == ebene,
                                           VertriebSperre.wert == vertrieb.normalisieren(wert)
                                           if ebene != "domain" else VertriebSperre.wert == wert).first()


def test_befristete_sperre_gilt_bis_einschliesslich_und_dann_nicht_mehr(db, monkeypatch):
    heute = vertrieb.heute()
    vertrieb.sperren(db, "unternehmen", "Schutzkunde Eins GmbH", "kundenschutz",
                     gilt_bis=heute + timedelta(days=3))
    assert vertrieb.darf_kontaktieren(db, firma="Schutzkunde Eins")[0] is False
    monkeypatch.setattr(vertrieb, "heute", lambda: heute + timedelta(days=3))
    assert vertrieb.darf_kontaktieren(db, firma="Schutzkunde Eins")[0] is False   # letzter Tag
    monkeypatch.setattr(vertrieb, "heute", lambda: heute + timedelta(days=4))
    assert vertrieb.darf_kontaktieren(db, firma="Schutzkunde Eins")[0] is True    # danach frei


def test_unbefristete_sperre_wird_nicht_befristet(db):
    vertrieb.sperren(db, "domain", "dauerhaft-gesperrt.example", "widerspruch")
    vertrieb.sperren(db, "domain", "dauerhaft-gesperrt.example", "kundenschutz",
                     gilt_bis=vertrieb.heute() - timedelta(days=1))
    s = _sperre(db, "domain", "dauerhaft-gesperrt.example")
    assert s.gilt_bis is None and s.grund == "widerspruch"
    assert vertrieb.darf_kontaktieren(db, email="x@dauerhaft-gesperrt.example")[0] is False


def test_verlaengern_ueberschreibt_datum_und_setzt_glocke_zurueck(db):
    heute = vertrieb.heute()
    s = vertrieb.sperren(db, "unternehmen", "Verlaengert AG", "kundenschutz",
                         gilt_bis=heute - timedelta(days=10))
    s.ablauf_erinnert_am = heute - timedelta(days=40)
    db.commit()
    assert vertrieb.darf_kontaktieren(db, firma="Verlaengert AG")[0] is True     # abgelaufen
    vertrieb.sperren(db, "unternehmen", "Verlaengert AG", "kundenschutz", "neuer Vertrag",
                     gilt_bis=heute + timedelta(days=700))
    db.refresh(s)
    assert s.gilt_bis == heute + timedelta(days=700)
    assert s.ablauf_erinnert_am is None and s.notiz == "neuer Vertrag"
    assert vertrieb.darf_kontaktieren(db, firma="Verlaengert AG")[0] is False


def test_formular_speichert_datum_und_notiz_und_zeigt_es(admin, db):
    bis = vertrieb.heute() + timedelta(days=730)
    r = admin.post("/admin/crm/akquise/sperre",
                   data={"ebene": "unternehmen", "wert": "Formular Schutzkunde GmbH",
                         "grund": "kundenschutz", "gilt_bis": bis.isoformat(),
                         "notiz": "Agentur Muster, Vertrag vom 27.10.2026"},
                   follow_redirects=False)
    assert r.status_code == 303
    s = _sperre(db, "unternehmen", "Formular Schutzkunde GmbH")
    assert s.gilt_bis == bis and s.notiz == "Agentur Muster, Vertrag vom 27.10.2026"
    html = admin.get("/admin/crm/akquise").text
    assert f"gilt bis {bis.strftime('%d.%m.%Y')}" in html
    assert 'name="gilt_bis"' in html and "Kundenschutz (Vertrag mit Agentur)" in html


def test_formular_ohne_datum_bleibt_unbefristet(admin, db):
    admin.post("/admin/crm/akquise/sperre",
               data={"ebene": "unternehmen", "wert": "Ohne Datum KG", "grund": "eigene",
                     "gilt_bis": ""}, follow_redirects=False)
    assert _sperre(db, "unternehmen", "Ohne Datum KG").gilt_bis is None


def test_glocke_30_tage_vorher_nur_einmal(db):
    heute = cron._heute()
    bald = vertrieb.sperren(db, "unternehmen", "Glocke Bald GmbH", "kundenschutz",
                            gilt_bis=heute + timedelta(days=20))
    spaeter = vertrieb.sperren(db, "unternehmen", "Glocke Spaeter GmbH", "kundenschutz",
                               gilt_bis=heute + timedelta(days=200))
    assert cron._run_kundenschutz_ablauf(db) >= 1
    db.refresh(bald)
    db.refresh(spaeter)
    assert bald.ablauf_erinnert_am == heute
    assert spaeter.ablauf_erinnert_am is None                   # noch nicht im Fenster
    meldung = (db.query(Benachrichtigung).filter(Benachrichtigung.typ == "kundenschutz_endet")
               .order_by(Benachrichtigung.id.desc()).first())
    assert "Glocke Bald GmbH" in (meldung.titel + meldung.text)
    vorher = db.query(Benachrichtigung).filter(Benachrichtigung.typ == "kundenschutz_endet").count()
    cron._run_kundenschutz_ablauf(db)                            # zweiter Lauf am selben Tag
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "kundenschutz_endet").count() == vorher
