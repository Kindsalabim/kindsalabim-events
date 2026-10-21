"""Akquise in Reitern (Aykut 20.10.2026): Wer diesen Monat anzuschreiben ist, steht
oben für sich; Angeschriebene und Abgeschlossene stehen nicht mehr dazwischen."""
from types import SimpleNamespace

from models import Kunde
from routes.crm import _akquise_ansicht


def _k(status="lead", monat=None, firma="Firma"):
    return SimpleNamespace(pipeline_status=status, ansprachemonat=monat, firma=firma)


def test_einteilung_im_oktober():
    assert _akquise_ansicht(_k(monat=10), 10)[0] == "jetzt"
    assert _akquise_ansicht(_k(monat=None), 10)[0] == "jetzt"
    assert _akquise_ansicht(_k(monat=9), 10)[0] == "jetzt"      # verpasst
    assert _akquise_ansicht(_k(monat=8), 10)[0] == "jetzt"      # verpasst
    assert _akquise_ansicht(_k(monat=7), 10)[0] == "spaeter"    # nächstes Jahr
    assert _akquise_ansicht(_k(monat=11), 10)[0] == "spaeter"
    assert _akquise_ansicht(_k("kontakt", 10), 10)[0] == "angeschrieben"
    assert _akquise_ansicht(_k("angebot", 10), 10)[0] == "angeschrieben"
    assert _akquise_ansicht(_k("gebucht"), 10)[0] == "abgeschlossen"
    assert _akquise_ansicht(_k("verloren"), 10)[0] == "abgeschlossen"


def test_jahreswechsel_rechnet_im_kreis():
    assert _akquise_ansicht(_k(monat=12), 1)[0] == "jetzt"      # Dezember im Januar verpasst
    assert _akquise_ansicht(_k(monat=2), 1)[0] == "spaeter"


def test_reihenfolge_jetzt_und_spaeter():
    jetzt = [_k(monat=None, firma="C"), _k(monat=10, firma="B"), _k(monat=9, firma="A9"),
             _k(monat=8, firma="A8")]
    sortiert = sorted(jetzt, key=lambda k: _akquise_ansicht(k, 10)[1])
    assert [k.firma for k in sortiert] == ["A8", "A9", "B", "C"]
    spaeter = [_k(monat=3, firma="M"), _k(monat=11, firma="N"), _k(monat=12, firma="D")]
    sortiert = sorted(spaeter, key=lambda k: _akquise_ansicht(k, 10)[1])
    assert [k.firma for k in sortiert] == ["N", "D", "M"]


def _anlegen(db, firma, status, monat):
    db.add(Kunde(firma=firma, herkunft="akquise", pipeline_status=status,
                 ansprachemonat=monat, email=f"info@{firma.lower().replace(' ', '')}.de"))


def test_seite_zeigt_standardmaessig_nur_die_faelligen(admin, db):
    from datetime import datetime
    m = datetime.now().month
    naechster = m % 12 + 1
    _anlegen(db, "Reitertest Faellig", "lead", m)
    _anlegen(db, "Reitertest Spaeter", "lead", naechster)
    _anlegen(db, "Reitertest Angeschrieben", "kontakt", m)
    db.commit()
    h = admin.get("/admin/crm/akquise").text
    assert "Reitertest Faellig" in h
    assert "Reitertest Spaeter" not in h and "Reitertest Angeschrieben" not in h
    assert "Jetzt dran (" in h and "Angeschrieben (" in h
    h = admin.get("/admin/crm/akquise?ansicht=angeschrieben").text
    assert "Reitertest Angeschrieben" in h and "Reitertest Faellig" not in h
    h = admin.get("/admin/crm/akquise?ansicht=spaeter").text
    assert "Reitertest Spaeter" in h


def test_unbekannte_ansicht_faellt_auf_jetzt(admin):
    assert admin.get("/admin/crm/akquise?ansicht=quatsch").status_code == 200
