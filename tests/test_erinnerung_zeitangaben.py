"""Erinnerungs-Mails: Die Restzeit wird echt berechnet, statt fest im Text zu stehen.

Hintergrund (Aykut, 16.07.): Eine Mail für ein Event am 17.07. behauptete „In 3 Wochen"
bzw. „In 2 Tagen" – der Versand läuft über ein Zeitfenster, der Text war fest verdrahtet.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import email_service
from choices import zeit_bis_text


# ── Helfer ───────────────────────────────────────────────────────────────────────

def test_zeit_bis_text_stufen():
    h = date(2026, 7, 16)
    assert zeit_bis_text(date(2026, 7, 16), h) == "heute"
    assert zeit_bis_text(date(2026, 7, 17), h) == "morgen"
    assert zeit_bis_text(date(2026, 7, 18), h) == "in 2 Tagen"
    assert zeit_bis_text(date(2026, 7, 21), h) == "in 5 Tagen"
    assert zeit_bis_text(date(2026, 7, 30), h) == "in 2 Wochen"
    assert zeit_bis_text(date(2026, 8, 6), h) == "in 3 Wochen"
    assert zeit_bis_text(None, h) == ""


def _ev(tage_hin, **over):
    base = dict(marke="Kindsalabim", anlass="Sommerfest", kunde_firma="DüBS",
                datum=date.today() + timedelta(days=tage_hin),
                startzeit="15:00", endzeit="19:00",
                veranstaltungsort="Karl-Geusen-Str. 206, 40231 Düsseldorf",
                produkte="Bastelaktion", material_info="2 Kisten")
    base.update(over)
    return SimpleNamespace(**base)


# ── Einsatz-Erinnerung (Punkt 3) ─────────────────────────────────────────────────

def test_einsatz_erinnerung_morgen_statt_2_tage(mails):
    dl = SimpleNamespace(vorname="Aykut", email="a@x.de")
    email_service.send_einsatz_erinnerung(dl, _ev(1))
    to, subject, html = mails[-1]
    assert "morgen</strong> hast du folgenden Einsatz" in html
    assert "2 Tagen" not in html and "2 Tagen" not in subject
    assert subject.startswith("📅 Morgen:")


def test_einsatz_erinnerung_heute(mails):
    dl = SimpleNamespace(vorname="Aykut", email="a@x.de")
    email_service.send_einsatz_erinnerung(dl, _ev(0))
    assert "heute</strong> hast du folgenden Einsatz" in mails[-1][2]


def test_einsatz_erinnerung_zwei_tage_bleibt_korrekt(mails):
    dl = SimpleNamespace(vorname="Aykut", email="a@x.de")
    email_service.send_einsatz_erinnerung(dl, _ev(2))
    assert "in 2 Tagen</strong> hast du folgenden Einsatz" in mails[-1][2]


def test_betreff_behaelt_deutsche_grossschreibung(mails):
    # str.capitalize() würde „in 2 Tagen" zu „In 2 tagen" machen
    dl = SimpleNamespace(vorname="Aykut", email="a@x.de")
    email_service.send_einsatz_erinnerung(dl, _ev(2))
    assert mails[-1][1].startswith("📅 In 2 Tagen:")


# ── Material-Erinnerung (Punkt 2) ────────────────────────────────────────────────

def test_material_erinnerung_morgen_statt_3_wochen(mails):
    email_service.send_material_erinnerung(_ev(1), "admin@x.de")
    html = mails[-1][2]
    assert "Morgen</strong> findet folgendes Event statt" in html
    assert "In <strong>3 Wochen</strong>" not in html


def test_material_erinnerung_drei_wochen_bleibt_korrekt(mails):
    email_service.send_material_erinnerung(_ev(21), "admin@x.de")
    assert "In 3 Wochen</strong> findet folgendes Event statt" in mails[-1][2]


def test_material_erinnerung_ohne_lieferantennamen(mails):
    # Der Lieferant gehört nicht in die Mail
    email_service.send_material_erinnerung(_ev(10), "admin@x.de")
    assert "Bakerross" not in mails[-1][2]


# ── Material-Abholung (Logistiker) ───────────────────────────────────────────────

def test_material_abhol_erinnerung_echte_restzeit(mails):
    log = SimpleNamespace(vorname="Max", email="m@x.de")
    email_service.send_material_abhol_erinnerung(_ev(1), log)
    html = mails[-1][2]
    assert "morgen</strong> ist dein Einsatz" in html
    assert "3 Tagen" not in html
