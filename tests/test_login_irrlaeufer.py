"""Dienstleister, die auf der Admin-Login-Seite landen (Irrläufer):
Wegweiser zum Portal + „Passwort vergessen" schickt ihnen automatisch den
Portal-Magic-Link statt stiller Funkstille. Kein Passwort-Feld mehr im
Dienstleister-Formular (Portal ist reiner Magic-Link-Login)."""
from factories import make_dienstleister, reload
from models import Dienstleister


def test_admin_login_zeigt_portal_wegweiser(client):
    h = client.get("/admin/login").text
    assert "/portal/login" in h
    assert "kein Passwort" in h


def test_forgot_schickt_dienstleisterin_den_portal_link(client, mails):
    did = make_dienstleister(vorname="Irrgard", nachname="Läufer",
                             email="irrgard@example.com")
    r = client.post("/admin/forgot", data={"email": "irrgard@example.com"},
                    follow_redirects=False)
    assert r.status_code == 303                      # gleiche Antwort wie immer
    assert reload(Dienstleister, did).magic_token    # Login-Token wurde erzeugt
    assert len(mails) == 1
    to, subject, html = mails[0]
    assert to == "irrgard@example.com"
    assert "Anmelde-Link" in subject                 # Portal-Magic-Link, kein Reset
    assert "/portal/auth/" in html


def test_forgot_unbekannte_adresse_schickt_nichts(client, mails):
    r = client.post("/admin/forgot", data={"email": "niemand@example.com"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert mails == []


def test_portal_login_ignoriert_gross_kleinschreibung_und_leerzeichen(client, mails):
    # Profil: "Melissa.Breivogel@…" – getippt: klein + Leerzeichen (Handy-Autofill)
    did = make_dienstleister(vorname="Melissa", nachname="Breivogel",
                             email="Melissa.Breivogel@web.example")
    r = client.post("/portal/login", data={"email": "  melissa.breivogel@web.example "},
                    follow_redirects=False)
    assert r.status_code == 303
    assert reload(Dienstleister, did).magic_token          # Link wurde erzeugt
    assert len(mails) == 1
    assert mails[0][0] == "Melissa.Breivogel@web.example"  # geht an die hinterlegte Adresse


def test_forgot_findet_dienstleister_trotz_anderer_schreibweise(client, mails):
    make_dienstleister(vorname="Gross", nachname="Klein", email="Gross.Klein@web.example")
    client.post("/admin/forgot", data={"email": "gross.klein@web.example"},
                follow_redirects=False)
    assert len(mails) == 1 and "Anmelde-Link" in mails[0][1]


def test_dienstleister_formular_ohne_passwortfeld(admin):
    h = admin.get("/admin/dienstleister/new").text
    assert "portal_passwort" not in h
    assert "ohne Passwort" in h                      # Erklärtext statt Feld
