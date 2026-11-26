"""Teamleiter-Info an den Kunden geht 14 Tage vor dem Event raus (Aykut 26.11.2026,
vorher 7 Tage)."""
from datetime import timedelta

import routes.cron as cron
from database import SessionLocal
from factories import make_event, make_dienstleister, reload
from models import Event


def _lauf():
    s = SessionLocal()
    try:
        return cron._run_teamleiter_infos(s)
    finally:
        s.close()


def test_14_tage_vorher_ja_15_tage_nein(mails):
    tl = make_dienstleister()
    heute = cron._heute()
    e14 = make_event(datum=heute + timedelta(days=14), teamleiter_id=tl, kunde_email="k@x.de")
    e15 = make_event(datum=heute + timedelta(days=15), teamleiter_id=tl, kunde_email="k@x.de")
    _lauf()
    assert reload(Event, e14).teamleiter_mail_gesendet is True
    assert not reload(Event, e15).teamleiter_mail_gesendet
