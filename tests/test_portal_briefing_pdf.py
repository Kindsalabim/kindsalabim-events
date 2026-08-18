"""Briefing-PDF für Dienstleister: Portal-Download (mit Zugriffsschutz),
Dashboard-Button und PDF-Hinweis in der Briefing-Mail."""
from datetime import date

import email_service
from factories import (make_event, make_dienstleister, make_anfrage,
                       briefing_event_ns, briefing_dl_ns)
from conftest import login_portal


# ── Portal-Download-Route ────────────────────────────────────────────────────────

def test_zugesagter_teamer_bekommt_pdf_nach_versand(client):
    did = make_dienstleister()
    eid = make_event(briefing_gesendet_am="2026-08-16T10:00:00")
    make_anfrage(eid, did, status="Ja")
    login_portal(client, did)
    r = client.get(f"/portal/events/{eid}/briefing.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_pdf_erst_nach_briefing_versand(client):
    # Zusage ja, aber Briefing noch nicht verschickt → freundlicher Hinweis statt
    # unvollständiger PDF (sorgte mehrfach für Rückfragen).
    did = make_dienstleister()
    eid = make_event()   # Status "Gebucht", kein Versand-Zeitstempel
    make_anfrage(eid, did, status="Ja")
    login_portal(client, did)
    r = client.get(f"/portal/events/{eid}/briefing.pdf", follow_redirects=False)
    assert r.status_code == 303
    assert "briefing_offen=1" in r.headers["location"]
    h = client.get("/portal?briefing_offen=1").text
    assert "noch nicht fertig" in h


def test_pdf_auch_bei_altbestand_mit_status(client):
    # Events, deren Briefing vor Einführung des Zeitstempels rausging → Status-Fallback
    did = make_dienstleister()
    eid = make_event(status="Briefing gesendet")
    make_anfrage(eid, did, status="Ja")
    login_portal(client, did)
    assert client.get(f"/portal/events/{eid}/briefing.pdf").status_code == 200


def test_briefing_senden_setzt_zeitstempel(admin):
    from models import Event
    from factories import reload
    did = make_dienstleister()
    eid = make_event()
    make_anfrage(eid, did, status="Ja")
    admin.post(f"/admin/events/{eid}/briefing", follow_redirects=False)
    assert reload(Event, eid).briefing_gesendet_am


def test_teamleiter_ohne_anfrage_bekommt_pdf(client):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did,      # Teamleiter, aber keine Ja-Anfrage
                     briefing_gesendet_am="2026-08-16T10:00:00")
    login_portal(client, did)
    r = client.get(f"/portal/events/{eid}/briefing.pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_fremder_teamer_wird_abgewiesen(client):
    did = make_dienstleister()               # nicht auf dem Event
    eid = make_event()
    login_portal(client, did)
    r = client.get(f"/portal/events/{eid}/briefing.pdf")
    assert r.status_code == 403


def test_ohne_login_kein_pdf(client):
    eid = make_event()
    r = client.get(f"/portal/events/{eid}/briefing.pdf", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/portal/login"


# ── Dashboard-Button ─────────────────────────────────────────────────────────────

def test_dashboard_zeigt_pdf_button_nur_nach_versand(client):
    did = make_dienstleister()
    eid = make_event(datum=date(2027, 8, 1),   # klar in der Zukunft → „Meine Einsätze"
                     briefing_gesendet_am="2026-08-16T10:00:00")
    make_anfrage(eid, did, status="Ja")
    login_portal(client, did)
    h = client.get("/portal").text
    assert f"/portal/events/{eid}/briefing.pdf" in h
    assert "Briefing als PDF speichern" in h


def test_dashboard_zeigt_hinweis_statt_button_vor_versand(client):
    did = make_dienstleister()
    eid = make_event(datum=date(2027, 9, 1))   # kein Briefing-Versand
    make_anfrage(eid, did, status="Ja")
    login_portal(client, did)
    h = client.get("/portal").text
    assert f"/portal/events/{eid}/briefing.pdf" not in h
    assert "bekommst du rechtzeitig vor dem Event" in h


# ── PDF-Hinweis in der Briefing-Mail ─────────────────────────────────────────────

def test_mail_pdf_hinweis_nur_wenn_angehaengt(mails):
    ev = briefing_event_ns()
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x", pdf_hinweis=True)
    assert "PDF an dieser Mail" in mails[-1][2]
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x")
    assert "PDF an dieser Mail" not in mails[-1][2]
