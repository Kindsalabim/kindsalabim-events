"""Review-Fixes Gruppe 2 (Zuverlässigkeit Cron/Mail):
- K1: Erinnerungs-Fenster statt exaktem Stichtag (ausgefallener Cron-Tag = kein Verlust)
- K2: Material-Bestell-Erinnerung mit eigenem Flag (kein Doppelversand / kein Totalausfall)
- M6: deutsche Ortszeit statt UTC (_jetzt/_heute)
- M7: Bericht-Erinnerung committet pro Event + ein Magic-Token je Teamleiter/Lauf
- H2: DEMO_MODE-Riegel – Demo-Routen inert gegen PostgreSQL (Prod)
"""
from datetime import date, timedelta

import routes.cron as cron
import ingest_bakerross
from database import SessionLocal
from models import Event, Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister, make_anfrage, reload

HEUTE = date.today()
CRON_CFG = {"cron_secret": "g2-secret", "admin_email": "a@b.de"}


def _sess_run(fn):
    s = SessionLocal()
    try:
        return fn(s)
    finally:
        s.close()


# ── M6: Zeitzone-Helfer ───────────────────────────────────────────────────────────

def test_heute_ist_deutsche_ortszeit():
    # _heute() darf nicht mehr als einen Tag von der UTC-Kalenderdatei abweichen,
    # liefert aber deutsche Ortszeit (relevant um Mitternacht auf dem UTC-Render-Server).
    assert abs((cron._heute() - HEUTE).days) <= 1
    assert cron._jetzt().tzinfo is None   # naiv, passend zu den "HH:MM"-Event-Zeiten


# ── K1: Einsatz-Erinnerung als Fenster ────────────────────────────────────────────

def test_einsatz_fenster_holt_verpassten_tag_nach():
    # Event ist nur noch 1 Tag entfernt (2-Tage-Stichtag verpasst) → muss trotzdem raus.
    # Datensatz-spezifisch geprüft (die geteilte Test-DB kann weitere Events im Fenster haben).
    eid = make_event(datum=HEUTE + timedelta(days=1))
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    _sess_run(cron._run_einsatz_erinnerungen)
    assert reload(Verfuegbarkeitsanfrage, aid).einsatz_erinnerung_gesendet is True


def test_einsatz_nicht_zu_frueh():
    eid = make_event(datum=HEUTE + timedelta(days=5))
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    _sess_run(cron._run_einsatz_erinnerungen)
    assert reload(Verfuegbarkeitsanfrage, aid).einsatz_erinnerung_gesendet is False


# ── K1: Material-Abhol-Erinnerung als Fenster ─────────────────────────────────────

def test_material_abhol_fenster_und_flag():
    did = make_dienstleister()
    eid = make_event(datum=HEUTE + timedelta(days=1), material_mitnahme=True, logistiker_id=did)
    _sess_run(cron._run_material_abhol_erinnerungen)
    assert reload(Event, eid).material_abhol_erinnerung_gesendet is True   # erinnert
    # Zweiter Lauf lässt das gesetzte Flag unangetastet (kein Doppelversand)
    _sess_run(cron._run_material_abhol_erinnerungen)
    assert reload(Event, eid).material_abhol_erinnerung_gesendet is True


def test_material_abhol_nicht_zu_frueh():
    did = make_dienstleister()
    eid = make_event(datum=HEUTE + timedelta(days=10), material_mitnahme=True, logistiker_id=did)
    _sess_run(cron._run_material_abhol_erinnerungen)
    assert reload(Event, eid).material_abhol_erinnerung_gesendet is False


# ── M7: Bericht-Erinnerung – ein Token je Teamleiter, pro Event committen ──────────

def test_bericht_erinnerung_ein_token_fuer_mehrere_events(mails):
    did = make_dienstleister()
    e1 = make_event(datum=HEUTE - timedelta(days=1), endzeit="10:00", teamleiter_id=did)
    e2 = make_event(datum=HEUTE - timedelta(days=1), endzeit="10:00", teamleiter_id=did)
    n = _sess_run(cron._run_bericht_erinnerungen)
    assert n == 2                                   # beide Events erinnert
    assert reload(Event, e1).bericht_erinnerung_am
    assert reload(Event, e2).bericht_erinnerung_am
    assert reload(__import__("models").Dienstleister, did).magic_token   # ein gültiger Token


# ── K1/K2: Frist- und Material-Bestell-Erinnerung über den Endpunkt ───────────────

def test_endpunkt_frist_fenster_und_material_flag(client, monkeypatch, mails):
    monkeypatch.setattr(cron, "get_config", lambda: CRON_CFG)
    monkeypatch.setattr(ingest_bakerross, "ingest_catalog", lambda db: "test-skip")

    # Frist gestern abgelaufen, aber noch nicht erinnert → Fenster (<= morgen) muss greifen
    did = make_dienstleister()
    eid = make_event(datum=HEUTE + timedelta(days=10))
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=HEUTE - timedelta(days=1))
    # Material-Bestellung: Event in 10 Tagen, Transport nötig, noch nicht bestellt
    mid = make_event(datum=HEUTE + timedelta(days=10), material_mitnahme=True, material_bestellt=False)

    r = client.get("/cron/erinnerung", headers={"X-Cron-Secret": "g2-secret"})
    assert r.status_code == 200
    assert reload(Verfuegbarkeitsanfrage, aid).erinnerung_gesendet is True
    assert reload(Event, mid).material_erinnerung_gesendet is True

    # Zweiter Lauf: keine Doppel-Mails (beide Flags gesetzt)
    daten = client.get("/cron/erinnerung", headers={"X-Cron-Secret": "g2-secret"}).json()
    assert daten["erinnerungen_gesendet"] == 0
    assert daten["material_erinnerungen"] == 0


# ── H2: DEMO_MODE-Riegel gegen PostgreSQL ─────────────────────────────────────────

def test_demo_inert_gegen_postgres(monkeypatch):
    import main
    monkeypatch.setattr(main, "get_config", lambda: {"demo_mode": True})
    assert main._demo_on() is True                     # SQLite-Test-DB → Demo erlaubt
    monkeypatch.setattr(main.engine.dialect, "name", "postgresql")
    assert main._demo_on() is False                    # Prod (Postgres) → inert
