"""Briefing: PDF-Download, Einmal-Teamer (extern), Rechnung/Footer je Marke, Maske-Vorbelegung."""
import io

from types import SimpleNamespace
from datetime import date

import email_service
from models import ExternerTeamer
from factories import make_event, make_dienstleister, make_anfrage, reload
from briefing_pdf import build_briefing_pdf


def test_extern_teamer_add_and_delete(admin):
    eid = make_event()
    admin.post(f"/admin/events/{eid}/extern-teamer",
               data={"name": "Tom Extern", "telefon": "0177 123"}, follow_redirects=False)
    from database import SessionLocal
    s = SessionLocal()
    t = s.query(ExternerTeamer).filter_by(event_id=eid).first()
    assert t.name == "Tom Extern"
    tid = t.id
    s.close()
    admin.post(f"/admin/events/{eid}/extern-teamer/{tid}/delete", follow_redirects=False)
    s = SessionLocal()
    assert s.query(ExternerTeamer).filter_by(event_id=eid).count() == 0
    s.close()


def test_briefing_pdf_download(admin):
    eid = make_event()
    r = admin.get(f"/admin/events/{eid}/briefing/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF" and len(r.content) > 1000
    assert "attachment" in r.headers.get("content-disposition", "")


def test_briefing_pdf_enthaelt_team_und_externe():
    ev = SimpleNamespace(marke="Kindsalabim", anlass="Fest", kunde_firma="X", datum=date(2026, 8, 1),
                         startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                         produkte="Zaubershow", kunde_kontakt="Hr. A", kunde_telefon="0201",
                         hinweise="", teamleiter_id=1,
                         cl_aufbau_von="", cl_aufbau_bis="", cl_abbau_von="", cl_abbau_bis="",
                         cl_aufbauort="", cl_parkplatz="", cl_teamkleidung="", cl_verpflegung="")
    team = [SimpleNamespace(id=1, vorname="Lisa", nachname="Klein", telefon="0177")]
    externe = [SimpleNamespace(name="Tom Extern", telefon="0160")]
    import pypdf
    pdf = build_briefing_pdf(ev, team, externe)
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Lisa Klein" in txt and "Tom Extern" in txt and "extern" in txt


def _capture_briefing(marke, externe=None, mails=None):
    ev = SimpleNamespace(marke=marke, anlass="Fest", kunde_firma="X", datum=date(2026, 8, 1),
                         startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                         produkte="Zaubershow", kunde_kontakt="Hr. A", kunde_telefon="0201",
                         hinweise="", teamleiter_id=None,
                         cl_aufbau_von="", cl_aufbau_bis="", cl_abbau_von="", cl_abbau_bis="",
                         cl_aufbauort="", cl_parkplatz="", cl_teamkleidung="", cl_verpflegung="")
    dl = SimpleNamespace(id=1, vorname="Max", nachname="M", telefon="0151", email="max@example.com")
    email_service.send_briefing([dl], ev, "https://x", externe=externe)
    return mails[-1][2]  # html


def test_briefing_rechnung_knallfrosch(mails):
    html = _capture_briefing("Knallfrosch", mails=mails)
    i = html.index("Rechnung senden an")
    block = html[i:i + 400]
    assert "Malca &amp; Akmanoglu GbR" in block and "personal@knallfrosch-kinderevents.de" in block
    assert "Kindsalabim" not in block


def test_briefing_footer_knallfrosch_ohne_kindsalabim(mails):
    html = _capture_briefing("Knallfrosch", mails=mails)
    assert "kindsalabim" not in html.lower()
    assert "info@knallfrosch-kinderevents.de" in html


def test_briefing_roster_enthaelt_externe(mails):
    ext = [SimpleNamespace(name="Tom Extern", telefon="0160")]
    html = _capture_briefing("Kindsalabim", externe=ext, mails=mails)
    assert "Tom Extern" in html and "extern" in html


def test_briefing_edit_vorbelegung_aus_event(admin):
    eid = make_event(kunde_firma="Glasfaser GmbH", kunde_kontakt="Frau Schmidt",
                     kunde_telefon="0201 99", veranstaltungsort="Musterstr. 1, 45127 Essen",
                     checkliste_uebersprungen=True)
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert 'value="Frau Schmidt"' in h and 'value="Glasfaser GmbH"' in h
    assert 'value="Musterstr. 1"' in h and 'value="45127 Essen"' in h
