"""Review-Fixes Gruppe 4 (Performance/Robustheit):
- H6: Briefing-Versand läuft im Hintergrund (Seite kehrt sofort zurück), Mail geht raus
- Dashboard-Aggregate (kein N+1) rendert weiter korrekt
- Eager-Loads: Portal-/Dienstleister-/CRM-Ansichten rendern ohne Fehler
- Indizes werden idempotent angelegt
"""
from datetime import date, timedelta

from sqlalchemy import text

from database import SessionLocal, engine
from models import Event, ExternerTeamer
from factories import make_event, make_dienstleister, make_anfrage, reload
from conftest import login_portal

HEUTE = date.today()


# ── H6: Briefing-Versand im Hintergrund ───────────────────────────────────────────

def test_briefing_versand_im_hintergrund(admin, mails):
    did = make_dienstleister(email="teamer@example.com")
    eid = make_event(datum=HEUTE + timedelta(days=5))
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    r = admin.post(f"/admin/events/{eid}/briefing",
                   headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303
    # Status sofort gesetzt (optimistisch), Mail über den BackgroundTask verschickt
    assert reload(Event, eid).status == "Briefing gesendet"
    assert any("teamer@example.com" in to for to, *_ in mails)


# ── Dashboard-Aggregate (kein N+1) ────────────────────────────────────────────────

def test_dashboard_rendert_mit_aggregaten(admin):
    did = make_dienstleister()
    eid = make_event(datum=HEUTE + timedelta(days=7), anzahl_teamer=2, kunde_firma="Aggregat GmbH")
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    s = SessionLocal()
    try:
        s.add(ExternerTeamer(event_id=eid, name="Extern Eins", telefon="0151")); s.commit()
    finally:
        s.close()
    r = admin.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Aggregat GmbH" in r.text


# ── Eager-Loads rendern fehlerfrei ────────────────────────────────────────────────

def test_portal_dashboard_rendert(client):
    did = make_dienstleister()
    eid = make_event(datum=HEUTE + timedelta(days=6))
    make_anfrage(eid, did, status="Ausstehend", frist_datum=HEUTE + timedelta(days=2))
    login_portal(client, did)
    assert client.get("/portal").status_code == 200


def test_dienstleister_detail_rendert(admin):
    did = make_dienstleister()
    eid = make_event()
    make_anfrage(eid, did, status="Ja")
    assert admin.get(f"/admin/dienstleister/{did}").status_code == 200


# ── Indizes idempotent angelegt ───────────────────────────────────────────────────

def test_indizes_vorhanden():
    with engine.connect() as conn:
        namen = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index'")).all()}
    for erwartet in ("ix_events_datum", "ix_anfrage_dl_status", "ux_anfrage_event_dl"):
        assert erwartet in namen
