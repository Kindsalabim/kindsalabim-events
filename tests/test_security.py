"""Security-Härtung (Roadmap 2.2–2.4):
- 2.2 Same-Origin-Check auf POSTs (CSRF-Schutz, Middleware in main.py)
- 2.3 Cron-Secret per X-Cron-Secret-Header (Query bleibt Fallback), zeitkonstanter Vergleich
- 2.4 Checklisten-Token: Ablauf 30 Tage nach Event + Sperre gegen Mehrfach-Überschreibung
"""
from datetime import date, timedelta

import routes.cron as cron_routes
from factories import make_event, reload
from models import Event

CRON_CFG = {"cron_secret": "test-geheim", "admin_email": "a@b.de"}


# ── 2.2 CSRF / Same-Origin-Middleware ────────────────────────────────────────────

def test_post_mit_fremdem_origin_blockiert(client):
    r = client.post("/admin/login", data={"email": "x@y.de", "password": "falsch"},
                    headers={"Origin": "https://boese-seite.example"})
    assert r.status_code == 403


def test_post_mit_fremdem_referer_blockiert(client):
    r = client.post("/admin/login", data={"email": "x@y.de", "password": "falsch"},
                    headers={"Referer": "https://boese-seite.example/angriff.html"})
    assert r.status_code == 403


def test_post_mit_eigenem_origin_erlaubt(client):
    r = client.post("/admin/login", data={"email": "x@y.de", "password": "falsch"},
                    headers={"Origin": "http://testserver"})
    assert r.status_code == 200          # Login-Seite mit Fehlermeldung, kein 403
    assert "Zugangsdaten" in r.text


def test_post_ohne_origin_erlaubt(client):
    # Nicht-Browser-Clients (Cron-Runner, Skripte) senden weder Origin noch Referer.
    r = client.post("/admin/login", data={"email": "x@y.de", "password": "falsch"})
    assert r.status_code == 200


def test_get_nicht_betroffen(client):
    # Der Schutz gilt nur für POSTs – GETs mit fremdem Origin bleiben normal erreichbar.
    r = client.get("/admin/login", headers={"Origin": "https://boese-seite.example"})
    assert r.status_code == 200


# ── 2.3 Cron-Secret per Header ───────────────────────────────────────────────────

def test_cron_secret_per_header(client, monkeypatch, mails):
    monkeypatch.setattr(cron_routes, "get_config", lambda: CRON_CFG)
    r = client.get("/cron/einsatz-erinnerung", headers={"X-Cron-Secret": "test-geheim"})
    assert r.status_code == 200


def test_cron_secret_query_fallback(client, monkeypatch, mails):
    # Bestehende Aufrufer (cron-job.org) nutzen weiterhin ?secret= – muss funktionieren.
    monkeypatch.setattr(cron_routes, "get_config", lambda: CRON_CFG)
    r = client.get("/cron/einsatz-erinnerung?secret=test-geheim")
    assert r.status_code == 200


def test_cron_falsches_oder_fehlendes_secret(client, monkeypatch):
    monkeypatch.setattr(cron_routes, "get_config", lambda: CRON_CFG)
    assert client.get("/cron/einsatz-erinnerung",
                      headers={"X-Cron-Secret": "falsch"}).status_code == 401
    assert client.get("/cron/einsatz-erinnerung?secret=falsch").status_code == 401
    assert client.get("/cron/einsatz-erinnerung").status_code == 401


def test_cron_leeres_secret_sperrt(client, monkeypatch):
    # Fehlkonfiguration (leeres cron_secret) darf den Endpunkt nicht öffnen.
    monkeypatch.setattr(cron_routes, "get_config", lambda: {"cron_secret": ""})
    assert client.get("/cron/einsatz-erinnerung?secret=").status_code == 401


# ── 2.4 Checklisten-Token ────────────────────────────────────────────────────────

def _checklist_daten(name):
    return {"ansprechpartner_name": name, "verpflegung": "Ja", "teamkleidung": "Ja"}


def test_checkliste_zweite_einreichung_ueberschreibt_nicht(client):
    eid = make_event(checklist_token="tok-sec-lock", kunde_email="k@example.com")
    r1 = client.post("/checklist/tok-sec-lock", data=_checklist_daten("Erste Angabe"))
    assert r1.status_code == 200
    r2 = client.post("/checklist/tok-sec-lock", data=_checklist_daten("Überschreiber"))
    assert r2.status_code == 200                     # freundliche Danke-Seite …
    assert "Vielen Dank" in r2.text
    ev = reload(Event, eid)
    assert ev.cl_ansprechpartner_name == "Erste Angabe"   # … aber Daten unverändert


def test_checkliste_link_abgelaufen(client):
    alt = date.today() - timedelta(days=45)
    eid = make_event(datum=alt, checklist_token="tok-sec-alt")
    assert client.get("/checklist/tok-sec-alt").status_code == 410
    r = client.post("/checklist/tok-sec-alt", data=_checklist_daten("Zu spät"))
    assert r.status_code == 410
    assert not reload(Event, eid).cl_eingereicht_am


def test_checkliste_kurz_nach_event_noch_gueltig(client):
    # Innerhalb der 30-Tage-Frist bleibt der Link nutzbar (Nachzügler-Kunden).
    kurz = date.today() - timedelta(days=5)
    make_event(datum=kurz, checklist_token="tok-sec-frisch")
    assert client.get("/checklist/tok-sec-frisch").status_code == 200
