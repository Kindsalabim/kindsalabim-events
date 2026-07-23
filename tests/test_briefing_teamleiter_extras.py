"""Teamleiter-Briefing: Eventbericht-Hinweis (inkl. Fotos) + markengerechtes
Infoblatt-PDF als Anhang – nur für die Teamleitung, nicht für Teamer/Künstler."""
import email_service
from factories import briefing_event_ns, briefing_dl_ns


def _sende(event, empfaenger):
    mails = []
    orig = email_service._deliver
    email_service._deliver = lambda to, subject, html, anhaenge=None: mails.append(
        {"to": to, "html": html, "anhaenge": [a[0] for a in (anhaenge or [])]})
    try:
        email_service.send_briefing(empfaenger, event, "http://t")
    finally:
        email_service._deliver = orig
    return mails


def test_teamleiter_bekommt_hinweis_und_infoblatt():
    ev = briefing_event_ns(teamleiter_id=1)
    tl = briefing_dl_ns(id=1, email="tl@example.com")
    teamer = briefing_dl_ns(id=2, vorname="Tina", email="teamer@example.com")
    mails = {m["to"]: m for m in _sende(ev, [tl, teamer])}

    tl_mail = mails["tl@example.com"]
    assert "Eventbericht" in tl_mail["html"] and "2–3 Fotos" in tl_mail["html"]
    assert tl_mail["anhaenge"] == ["Teamleiter-Infoblatt Kindsalabim.pdf"]

    teamer_mail = mails["teamer@example.com"]
    assert "Eventbericht ausfüllen" not in teamer_mail["html"]
    assert teamer_mail["anhaenge"] == []


def test_infoblatt_folgt_der_marke():
    ev = briefing_event_ns(teamleiter_id=1, marke="Knallfrosch")
    tl = briefing_dl_ns(id=1, email="tl@example.com")
    mails = _sende(ev, [tl])
    assert mails[0]["anhaenge"] == ["Teamleiter-Infoblatt Knallfrosch.pdf"]


def test_ohne_teamleiter_keine_extras():
    ev = briefing_event_ns(teamleiter_id=None)
    dl = briefing_dl_ns(id=5, email="x@example.com")
    mails = _sende(ev, [dl])
    assert "Eventbericht ausfüllen" not in mails[0]["html"]
    assert mails[0]["anhaenge"] == []
