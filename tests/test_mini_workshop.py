"""Programm-Art „Z+Mini-Workshop“ (45 Min. Zaubershow + 15 Min. Mini-Workshop).

Der E-Mail-Assistent kennt sie, die Events-App kannte sie nicht: Reservierungs-Links
und die AB-Meldung mit dieser Art wären ins Leere gelaufen. Aykut 11.10.2026: im
Event eine eigene Aktion „Mini-Workshop“.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from calendar_service import _event_art, _reservierung_body
from choices import benoetigte_sparten
from routes.admin import PRODUKTE_LIST, _ART_PRODUKTE, _reservierung_vorlage

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}


def _ev(produkte):
    return SimpleNamespace(produkte=produkte, produkte_freitext="")


def test_aktion_mini_workshop_gibt_es():
    assert "Mini-Workshop" in PRODUKTE_LIST
    assert benoetigte_sparten("Mini-Workshop") == {"Showact"}


def test_kalenderkuerzel_wie_bei_der_reservierung():
    assert _event_art(_ev("Zaubershow, Mini-Workshop")) == "Z+Mini-Workshop"
    assert _event_art(_ev("Mini-Workshop")) == "Mini-Workshop"
    assert _event_art(_ev("Zaubershow, Ballonmodellage, Mini-Workshop")) == "ZB+Mini-Workshop"
    assert _event_art(_ev("Hüpfburg, Mini-Workshop")) == "Mini-Workshop"
    # Ein voller Zauberworkshop am selben Tag dominiert
    assert _event_art(_ev("Zaubershow, Zauberworkshop, Mini-Workshop")) == "WORKSHOP+Z"
    # Unverändert ohne Mini-Workshop
    assert _event_art(_ev("Zaubershow, Zauberworkshop")) == "WORKSHOP+Z"


def test_reservierungs_link_nimmt_die_art_an():
    for roh in ("Z+Mini-Workshop", "Z+MINI-WORKSHOP", "z+mini workshop"):
        v = _reservierung_vorlage({"art": roh, "datum": "2026-12-01", "startzeit": "15:00"})
        assert v.art == "Z+Mini-Workshop", roh
        assert not any("Art bitte wählen" in h for h in v.hinweise)


def test_reservierung_im_kalender():
    r = SimpleNamespace(art="Z+Mini-Workshop", veranstaltungsort="Weg 1, 45127 Essen",
                        kunde_firma="Familie Test", kunde_kontakt="", anlass="Geburtstag",
                        frist=None, kunde_telefon="", kunde_email="", notiz="",
                        datum=date(2026, 12, 1), startzeit="15:00", endzeit="16:00")
    assert _reservierung_body(r)["summary"].startswith("(Z+Mini-Workshop) Essen")


def test_formulare_bieten_die_art_an(admin, db):
    from models import Reservierung
    assert 'value="Z+Mini-Workshop"' in admin.get("/admin/reservierungen").text
    r = Reservierung(datum=date.today() + timedelta(days=90), kunde_firma="Mini Edit",
                     art="Z+Mini-Workshop", frist=date.today() + timedelta(days=80),
                     erstellt_am="2026-10-11T10:00:00")
    db.add(r); db.commit()
    h = admin.get(f"/admin/reservierungen/{r.id}/edit").text
    assert 'value="Z+Mini-Workshop" selected' in h


def test_ab_meldung_fuellt_die_aktionen_vor(admin, monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})
    tag = date.today() + timedelta(days=95)
    r = admin.post("/admin/crm/api/buchung/ab", headers=GEHEIM, json={
        "datum": tag.isoformat(), "privat": True, "kontakt": "Jake Blade",
        "empfaenger": "jake.mini@gmail.com", "art": "Z+Mini-Workshop"})
    assert r.json()["ergebnis"] == "vorlage"
    assert _ART_PRODUKTE["Z+MINI-WORKSHOP"] == ["Zaubershow", "Mini-Workshop"]
    h = admin.get(f"/admin/events/new?vorlage=1&datum={tag.isoformat()}"
                  "&art=Z%2BMini-Workshop").text
    import re
    assert re.search(r'value="Mini-Workshop"[^>]*checked', h)
    assert re.search(r'value="Zaubershow"[^>]*checked', h)
