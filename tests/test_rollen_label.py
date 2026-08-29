"""Rollen-Bezeichnung in Mails/PDF: „Teamleitung" nur, wenn es wirklich ein Team gibt."""
import email_service
from choices import rollen_label
from briefing_pdf import build_briefing_pdf
from factories import briefing_event_ns, briefing_dl_ns


def test_label_haengt_an_der_teamgroesse():
    assert rollen_label(1) == "Ansprechpartner vor Ort"
    assert rollen_label(0) == "Ansprechpartner vor Ort"
    assert rollen_label(None) == "Ansprechpartner vor Ort"
    assert rollen_label(2) == "Teamleitung"


def test_briefing_mail_allein_ohne_teamleitung(mails):
    ev = briefing_event_ns(teamleiter_id=1)
    email_service.send_briefing([briefing_dl_ns(id=1)], ev, "https://x")
    html = mails[-1][2]
    assert "Ansprechpartner vor Ort:" in html
    assert "Teamleitung:" not in html


def test_briefing_mail_im_team_mit_teamleitung(mails):
    ev = briefing_event_ns(teamleiter_id=1)
    team = [briefing_dl_ns(id=1, email="a@x.de"), briefing_dl_ns(id=2, email="b@x.de")]
    email_service.send_briefing(team, ev, "https://x")
    assert any("Teamleitung:" in m[2] for m in mails)


def test_bericht_erinnerung_passt_die_anrede_an(mails):
    ev = briefing_event_ns()
    email_service.send_bericht_erinnerung(briefing_dl_ns(), ev, "https://x", team_groesse=1)
    assert "du warst Ansprechpartner vor Ort" in mails[-1][2]
    email_service.send_bericht_erinnerung(briefing_dl_ns(), ev, "https://x", team_groesse=3)
    assert "du warst Teamleitung" in mails[-1][2]


def test_briefing_pdf_nutzt_dasselbe_label():
    import fitz
    ev = briefing_event_ns(teamleiter_id=1)
    allein = fitz.open(stream=build_briefing_pdf(ev, [briefing_dl_ns(id=1)], []),
                       filetype="pdf")
    text_allein = allein[0].get_text()
    allein.close()
    assert "Ansprechpartner vor Ort:" in text_allein and "Teamleitung" not in text_allein

    team = fitz.open(stream=build_briefing_pdf(
        ev, [briefing_dl_ns(id=1), briefing_dl_ns(id=2, vorname="Zoe")], []), filetype="pdf")
    text_team = team[0].get_text()
    team.close()
    assert "Teamleitung" in text_team
