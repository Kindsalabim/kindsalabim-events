"""Briefing (Mail + PDF): Ansprechpartner/Veranstaltungsanschrift aus Checkliste + Teamleiter-Hinweis."""
import io

import email_service
from briefing_pdf import build_briefing_pdf
from factories import briefing_event_ns, briefing_dl_ns


def test_mail_none_string_wird_leer(mails):
    ev = briefing_event_ns(kunde_kontakt="None", kunde_telefon="None")
    email_service.send_briefing([briefing_dl_ns(telefon="None")], ev, "https://x")
    html = mails[-1][2]
    assert ">None<" not in html and ">None " not in html


def test_team_telefon_bricht_nicht_um(mails):
    ev = briefing_event_ns(teamleiter_id=1)
    email_service.send_briefing([briefing_dl_ns(id=1, telefon="+4917655787913")], ev, "https://x")
    html = mails[-1][2]
    assert "+4917655787913" in html and "white-space:nowrap" in html


def test_pdf_none_string_wird_leer():
    import io
    import pypdf
    ev = briefing_event_ns(kunde_kontakt="None", kunde_telefon="None")
    pdf = build_briefing_pdf(ev, [briefing_dl_ns(telefon="None")], [])
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "None" not in txt


def _html(ev, mails):
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x")
    return mails[-1][2]


def test_mail_ansprechpartner_aus_checkliste_bevorzugt(mails):
    ev = briefing_event_ns(cl_ansprechpartner_name="Frau Klar", cl_ansprechpartner_mobil="0177 9",
                           kunde_kontakt="Alt", kunde_telefon="0000")
    html = _html(ev, mails)
    assert "Frau Klar" in html and "0177 9" in html
    assert "Ansprechpartner Kunde" in html        # Karten-Titel (wie im PDF)


def test_mail_veranstaltungsanschrift_aus_checkliste(mails):
    ev = briefing_event_ns(cl_firma_name="Kita Sonne", cl_strasse="Hauptstr. 5", cl_plz_ort="45127 Essen")
    html = _html(ev, mails)
    assert "Veranstaltungsadresse" in html         # Karten-Titel (wie im PDF)
    assert "Kita Sonne" in html and "Hauptstr. 5" in html and "45127 Essen" in html


def test_mail_teamleiter_hinweis(mails):
    html = _html(briefing_event_ns(), mails)
    # Kontakt-Regel steht jetzt in der Ansprechpartner-Karte
    assert "nur über die Teamleitung" in html and "font-weight:700" in html


def test_mail_anschrift_fallback_auf_veranstaltungsort(mails):
    ev = briefing_event_ns(veranstaltungsort="Eventstr. 9, 50667 Köln")  # keine cl_-Adresse
    html = _html(ev, mails)
    assert "Eventstr. 9, 50667 Köln" in html


def _pdf_text(ev):
    import pypdf
    pdf = build_briefing_pdf(ev, [], [])
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_anschrift_und_ansprechpartner_und_hinweis():
    ev = briefing_event_ns(cl_ansprechpartner_name="Frau Klar", cl_ansprechpartner_mobil="0177",
                           cl_firma_name="Kita Sonne", cl_strasse="Hauptstr. 5", cl_plz_ort="45127 Essen")
    txt = _pdf_text(ev)
    # Karten-Layout (Vorlage „Briefing 2.0"): Boxen heißen jetzt „Veranstaltungsadresse"
    # und „Ansprechpartner Kunde"; der Teamleiter-Hinweis steht in der Ansprechpartner-Box.
    assert "Veranstaltungsadresse" in txt and "Kita Sonne" in txt and "Hauptstr. 5" in txt
    assert "Ansprechpartner Kunde" in txt and "Frau Klar" in txt
    # (kann im schmalen Karten-Layout umbrechen → Teile einzeln prüfen)
    assert "NUR über die" in txt and "Teamleitung" in txt
