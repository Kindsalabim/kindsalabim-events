"""Checklisten-Sektion: dezenter „erneut senden"-Link in den beiden „bereits gesendet"-Zuständen
(gesendet/wartet + Kunde hat ausgefüllt). Nur bei vorhandener Kunden-Mail und nicht gesperrt."""
from datetime import date, timedelta

from factories import make_event

BALD = date.today() + timedelta(days=20)


def test_resend_link_im_wartezustand(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com", checklist_token="tok-warte")
    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "erneut senden" in r.text


def test_resend_link_nach_kundeneingang(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com",
                     checklist_token="tok-fertig", cl_eingereicht_am="30.06.2026")
    r = admin.get(f"/admin/events/{eid}")
    assert "erneut senden" in r.text


def test_kein_resend_ohne_kundenmail(admin):
    eid = make_event(datum=BALD, kunde_email=None, checklist_token="tok-noemail")
    r = admin.get(f"/admin/events/{eid}")
    assert "Link ansehen" in r.text          # Wartezustand wird angezeigt
    assert "erneut senden" not in r.text      # aber kein Resend ohne Mail


def test_kein_resend_bei_gesperrtem_event(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com",
                     checklist_token="tok-zu", status="Abgeschlossen")
    r = admin.get(f"/admin/events/{eid}")
    assert "erneut senden" not in r.text
