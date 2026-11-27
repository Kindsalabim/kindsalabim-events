"""Knallfrosch-Kunden bekommen keine Mail mit Kindsalabim-Absender (Aykut 27.11.2026)."""
from datetime import date, timedelta

import email_service
from email_service import _absender
from models import Event
from tests.factories import make_event

CFG = {"company_name": "Kindsalabim Kinderevents", "mail_from": "info@kindsalabim-events.de",
       "mail_reply_to": "info@kindsalabim.de", "mail_reply_to_knallfrosch": "info@knallfrosch-kinderevents.de"}


def test_absender_je_marke():
    assert _absender(CFG, "Kindsalabim") == ("Kindsalabim Kinderevents <info@kindsalabim-events.de>",
                                             "info@kindsalabim.de")
    von, antwort = _absender(CFG, "Knallfrosch")
    assert von.startswith("Knallfrosch Kinderevents <") and "Kindsalabim" not in von
    assert antwort == "info@knallfrosch-kinderevents.de"
    # erst nach Resend-Verifizierung: eigene Knallfrosch-Adresse
    von, _ = _absender({**CFG, "mail_from_knallfrosch": "info@knallfrosch-kinderevents.de"}, "Knallfrosch")
    assert von == "Knallfrosch Kinderevents <info@knallfrosch-kinderevents.de>"


def test_kundenmails_geben_die_marke_mit(monkeypatch, db):
    gesehen = []
    monkeypatch.setattr(email_service, "_deliver",
                        lambda to, subject, html, anhaenge=None, marke=None: gesehen.append(marke))
    eid = make_event(marke="Knallfrosch", kunde_email="kunde@example.com",
                     datum=date.today() + timedelta(days=10))
    ev = db.get(Event, eid)
    email_service.send_teamleiter_info(ev)
    email_service.send_checklist_email(ev, "https://example.com")
    assert gesehen == ["Knallfrosch", "Knallfrosch"]
