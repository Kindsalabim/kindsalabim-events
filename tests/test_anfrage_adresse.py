"""Adresse in der Verfügbarkeitsanfrage: Teamer sehen die volle Adresse,
Künstler nur PLZ/Ort (Kundenschutz). Entscheidung Aykut 22.07.2026."""
from datetime import date
from types import SimpleNamespace

import email_service
from choices import anfrage_ort

ADRESSE = "Musterstraße 12, 45127 Essen"


def _ev(**over):
    base = dict(marke="Kindsalabim", anlass="Sommerfest", datum=date(2026, 8, 1),
                startzeit="14:00", endzeit="18:00", veranstaltungsort=ADRESSE,
                produkte="Spieleland", transporter_angeboten=False, material_info="")
    base.update(over)
    return SimpleNamespace(**base)


def _dl():
    return SimpleNamespace(vorname="Max", nachname="Muster", email="dl@example.com")


def _gesendet(fn, *args, **kw):
    captured = {}
    orig = email_service._deliver
    email_service._deliver = lambda to, subject, html, anhaenge=None: captured.setdefault("html", html)
    try:
        fn(*args, **kw)
    finally:
        email_service._deliver = orig
    return captured.get("html", "")


def test_anfrage_ort_nach_rolle():
    assert anfrage_ort(ADRESSE, "Teamer") == ADRESSE
    assert anfrage_ort(ADRESSE, "Künstler") == "45127 Essen"
    assert anfrage_ort(ADRESSE, None) == "45127 Essen"   # ohne Rolle konservativ maskieren
    assert anfrage_ort("", "Teamer") == ""


def test_anfrage_mail_teamer_sieht_volle_adresse():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(), 1, "http://t", rolle="Teamer")
    assert "Musterstraße 12" in html


def test_anfrage_mail_kuenstler_sieht_nur_plz_ort():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(), 1, "http://t", rolle="Künstler")
    assert "Musterstraße 12" not in html and "45127 Essen" in html


def test_serie_mail_folgt_der_rolle():
    tage = [_ev(), _ev(datum=date(2026, 8, 2))]
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t", rolle="Teamer")
    assert "Musterstraße 12" in html
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t")
    assert "Musterstraße 12" not in html   # Default bleibt maskiert
