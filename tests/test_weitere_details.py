"""'Weitere Details': Kunden-Checkliste + Briefing-bearbeiten speichern es; Mail/PDF zeigen es."""
import io
from types import SimpleNamespace
from datetime import date

import email_service
from models import Event
from factories import make_event, reload
from briefing_pdf import build_briefing_pdf
from database import SessionLocal


def test_checkliste_speichert_weitere_details(client):
    eid = make_event()
    s = SessionLocal()
    ev = s.get(Event, eid)
    ev.checklist_token = "tok-wd-1"
    s.commit(); s.close()
    r = client.post("/checklist/tok-wd-1", data={
        "ansprechpartner_name": "A", "parkplatz": "Hof",
        "weitere_details": "Treffpunkt am Haupteingang"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert reload(Event, eid).cl_weitere_details == "Treffpunkt am Haupteingang"


def test_briefing_edit_speichert_weitere_details(admin):
    eid = make_event()
    admin.post(f"/admin/events/{eid}/checklist/edit", data={
        "ansprechpartner_name": "A", "weitere_details": "Bitte Bühne mitbringen"},
        follow_redirects=False)
    assert reload(Event, eid).cl_weitere_details == "Bitte Bühne mitbringen"


def test_briefing_edit_form_zeigt_feld_mit_wert(admin):
    eid = make_event(cl_weitere_details="Vorab-Notiz")
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert 'name="weitere_details"' in h and "Vorab-Notiz" in h


def test_briefing_mail_zeigt_weitere_details(mails):
    ev = SimpleNamespace(marke="Kindsalabim", anlass="Fest", kunde_firma="X", datum=date(2026, 8, 1),
                         startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                         produkte="Zaubershow", kunde_kontakt="A", kunde_telefon="0201", hinweise="",
                         teamleiter_id=None, cl_aufbau_von="", cl_aufbau_bis="", cl_abbau_von="",
                         cl_abbau_bis="", cl_aufbauort="", cl_parkplatz="", cl_teamkleidung="",
                         cl_verpflegung="", cl_weitere_details="Treffpunkt Haupteingang")
    dl = SimpleNamespace(id=1, vorname="Max", nachname="M", telefon="0151", email="m@x.de")
    email_service.send_briefing([dl], ev, "https://x")
    html = mails[-1][2]
    assert "Weitere Details" in html and "Treffpunkt Haupteingang" in html


def test_briefing_pdf_zeigt_weitere_details():
    ev = SimpleNamespace(marke="Kindsalabim", anlass="Fest", kunde_firma="X", datum=date(2026, 8, 1),
                         startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                         produkte="Zaubershow", kunde_kontakt="A", kunde_telefon="0201", hinweise="",
                         teamleiter_id=None, cl_aufbau_von="", cl_aufbau_bis="", cl_abbau_von="",
                         cl_abbau_bis="", cl_aufbauort="", cl_parkplatz="", cl_teamkleidung="",
                         cl_verpflegung="", cl_weitere_details="Bitte Buehne mitbringen")
    import pypdf
    pdf = build_briefing_pdf(ev, [], [])
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    # Karten-Layout: „Weitere Details" der Checkliste stehen jetzt in der Box „Besonderes"
    assert "Besonderes" in txt and "Buehne" in txt
