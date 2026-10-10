"""Anrede in Kundenmails nach Vornamen (Aykut 10.10.2026).

Anlass: Eine Kundin bekam „Hallo Sandra Schero,“. Regel: Ist am Vornamen eindeutig
erkennbar, ob Frau oder Herr, wird so angesprochen, unabhängig von der Sprache. Bei
Namen, die für beide Geschlechter vorkommen, bleibt der volle Name.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from anrede import geschlecht, kunden_anrede


@pytest.mark.parametrize("name, erwartet", [
    ("Sandra Schero", "Hallo Frau Schero,"),
    ("Emine Aslan", "Hallo Frau Aslan,"),          # Aykuts Beispiel
    ("Jake Blade", "Hallo Herr Blade,"),           # Aykuts Beispiel
    ("Jürgen Klopp", "Hallo Herr Klopp,"),
    ("Juergen Klopp", "Hallo Herr Klopp,"),
    ("Ayşe Yılmaz", "Hallo Frau Yılmaz,"),          # türkische Sonderzeichen
    ("Anna-Lena Müller", "Hallo Frau Müller,"),     # Doppelname: erster Teil zählt
    ("Anna Maria Meier", "Hallo Frau Meier,"),      # zweiter Vorname fällt weg
    ("Dr. Anna Meier", "Hallo Frau Dr. Meier,"),
    ("Jan van der Berg", "Hallo Herr van der Berg,"),
    ("Frau Schmidt", "Hallo Frau Schmidt,"),        # steht schon da
])
def test_eindeutige_vornamen(name, erwartet):
    assert kunden_anrede(name) == erwartet


@pytest.mark.parametrize("name", [
    "Kim Weber", "Andrea Rossi", "Sascha Klein", "Jean Dupont", "Deniz Kaya",
    "Xaver Unbekannt",                      # nicht gelistet: nie raten
])
def test_unklar_bleibt_der_volle_name(name):
    assert kunden_anrede(name) == f"Hallo {name},"


def test_mehrere_personen_oder_nur_ein_wort():
    assert kunden_anrede("Anna und Peter Meier") == "Hallo Anna und Peter Meier,"
    assert kunden_anrede("Schmidt") == "Hallo Schmidt,"
    assert kunden_anrede("") == "Guten Tag,"
    assert kunden_anrede(None) == "Guten Tag,"


def test_listen_widersprechen_sich_nicht():
    import anrede
    assert not (anrede._WEIBLICH & anrede._MAENNLICH)
    assert not (anrede._WEIBLICH & anrede._UNEINDEUTIG)
    assert not (anrede._MAENNLICH & anrede._UNEINDEUTIG)
    assert geschlecht("kim") == "" and geschlecht("andrea") == ""


def _event(kontakt):
    return SimpleNamespace(
        marke="Kindsalabim", kunde_kontakt=kontakt, kunde_email="kunde@example.test",
        datum=date(2026, 10, 10), anlass="Sommerfest", startzeit="14:00", endzeit="18:00",
        checklist_token="tok", teamleiter=SimpleNamespace(
            vorname="Sabrina", nachname="Braun", telefon="0159 000"))


def test_teamleiter_mail_spricht_mit_frau_an(mails):
    from email_service import send_teamleiter_info
    send_teamleiter_info(_event("Sandra Schero"))
    html = mails[-1][2]
    assert "Hallo Frau Schero," in html
    assert "Hallo Sandra Schero" not in html


def test_checklisten_mail_spricht_persoenlich_an(mails):
    from email_service import send_checklist_email
    send_checklist_email(_event("Jake Blade"), "https://example.test")
    assert "Hallo Herr Blade," in mails[-1][2]
    send_checklist_email(_event(""), "https://example.test")
    assert "Guten Tag," in mails[-1][2]
