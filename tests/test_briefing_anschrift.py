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


def test_mail_teamleitung_steht_vor_dem_kunden(mails):
    """Die Kontaktkarte muss die Teamleitung ZUERST nennen – sonst ruft das Team
    instinktiv die Nummer an, die unter „Ansprechpartner" ganz oben steht."""
    import email_service
    team = [briefing_dl_ns(id=1, vorname="Kevin", nachname="Leiter", telefon="0170 111",
                           email="a@x.de"),
            briefing_dl_ns(id=2, email="b@x.de")]
    ev = briefing_event_ns(teamleiter_id=1, cl_ansprechpartner_name="Frau Klar",
                           cl_ansprechpartner_mobil="0177 999")
    email_service.send_briefing(team, ev, "https://x")
    html = mails[-1][2]
    assert "Wen du anrufst" in html
    assert "Erste Anlaufstelle" in html
    # Reihenfolge: Teamleitung vor Kunde
    assert html.index("0170 111") < html.index("0177 999")
    # Die Kundennummer bleibt erreichbar, nur erkennbar als zweite Wahl
    assert "0177 999" in html and "nicht erreichbar" in html


def test_mail_ohne_team_bleibt_die_alte_karte(mails):
    """Ein-Personen-Einsatz: Es gibt keine Teamleitung, also auch keine Rangfolge."""
    html = _html(briefing_event_ns(), mails)
    assert "Ansprechpartner Kunde" in html and "Wen du anrufst" not in html


def test_mail_anschrift_fallback_auf_veranstaltungsort(mails):
    ev = briefing_event_ns(veranstaltungsort="Eventstr. 9, 50667 Köln")  # keine cl_-Adresse
    html = _html(ev, mails)
    assert "Eventstr. 9, 50667 Köln" in html


def _pdf_text(ev, team=None):
    import pypdf
    pdf = build_briefing_pdf(ev, team if team is not None else [], [])
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_anschrift_und_kontakt_rangfolge():
    ev = briefing_event_ns(teamleiter_id=1,
                           cl_ansprechpartner_name="Frau Klar", cl_ansprechpartner_mobil="0177",
                           cl_firma_name="Kita Sonne", cl_strasse="Hauptstr. 5", cl_plz_ort="45127 Essen")
    txt = _pdf_text(ev, [briefing_dl_ns(id=1, nachname="Leiter", telefon="0170 111"),
                         briefing_dl_ns(id=2, vorname="Zoe")])
    assert "Veranstaltungsadresse" in txt and "Kita Sonne" in txt and "Hauptstr. 5" in txt
    # Kontaktkarte nennt die Teamleitung zuerst, den Kunden erkennbar danach
    assert "Wen du anrufst" in txt
    assert txt.index("0170 111") < txt.index("Frau Klar")
    # Hinweiszeilen brechen im schmalen Karten-Layout um → in Teilen prüfen
    assert "Erste Anlaufstelle" in txt
    assert "Bitte nur über die Teamleitung" in txt and "erreichbar ist" in txt


def test_pdf_ohne_teamleitung_bleibt_die_alte_karte():
    """Ohne gesetzte Teamleitung gibt es keine Rangfolge – Karte wie bisher."""
    txt = _pdf_text(briefing_event_ns(cl_ansprechpartner_name="Frau Klar"), [briefing_dl_ns()])
    assert "Ansprechpartner Kunde" in txt and "Frau Klar" in txt
    assert "Wen du anrufst" not in txt
