"""Privatkunde/Vorkasse + separate Rechnungs-Mailadresse:
- Vorkasse-Erinnerung 14 Tage vor Privatkunden-Events (einmalig)
- Erinnerung nach dem Event, wenn eine spezielle Rechnungs-Mail hinterlegt ist
  (CRM-Profil oder Kunden-Checkliste)
- Checklisten-Feld „Rechnungs-E-Mail" wird in die Kundenkartei übernommen"""
from datetime import date, timedelta

from database import SessionLocal
from factories import make_event, reload
from models import Event, Kunde, Benachrichtigung
from routes.cron import _run_rechnung_erinnerungen


def _meldungen(teil):
    s = SessionLocal()
    try:
        return (s.query(Benachrichtigung)
                .filter(Benachrichtigung.typ == "rechnung_erinnerung",
                        Benachrichtigung.titel.contains(teil)).all())
    finally:
        s.close()


def _make_kunde(**kw):
    s = SessionLocal()
    try:
        k = Kunde(firma=kw.pop("firma", "Kunde GmbH"), **kw)
        s.add(k); s.commit()
        return k.id
    finally:
        s.close()


def test_vorkasse_erinnerung_14_tage_vorher_einmalig(db):
    eid = make_event(datum=date.today() + timedelta(days=10), privatkunde=True,
                     kunde_firma="Familie Vorkasse", kunde_email="fam@vk.example")
    _run_rechnung_erinnerungen(db)
    assert reload(Event, eid).vorkasse_erinnert is True
    m = _meldungen("Familie Vorkasse")
    assert len(m) == 1 and "fam@vk.example" in m[0].text
    _run_rechnung_erinnerungen(db)
    assert len(_meldungen("Familie Vorkasse")) == 1     # keine Wiederholung


def test_vorkasse_nicht_zu_frueh_und_nicht_ohne_flag(db):
    zu_frueh = make_event(datum=date.today() + timedelta(days=30), privatkunde=True,
                          kunde_firma="Zu Früh GmbH")
    firmenkunde = make_event(datum=date.today() + timedelta(days=10),
                             kunde_firma="Firmenkunde AG")
    _run_rechnung_erinnerungen(db)
    assert reload(Event, zu_frueh).vorkasse_erinnert is False
    assert reload(Event, firmenkunde).vorkasse_erinnert is False


def test_rechnungsadresse_erinnerung_nach_event(db):
    kid = _make_kunde(firma="Rechnungsmail AG", rechnung_email="invoice@ag.example")
    eid = make_event(datum=date.today() - timedelta(days=1), kunde_id=kid,
                     kunde_firma="Rechnungsmail AG")
    _run_rechnung_erinnerungen(db)
    assert reload(Event, eid).rechnung_mail_erinnert is True
    m = _meldungen("Rechnungsmail AG")
    assert len(m) == 1 and "invoice@ag.example" in m[0].text
    _run_rechnung_erinnerungen(db)
    assert len(_meldungen("Rechnungsmail AG")) == 1     # einmalig


def test_keine_erinnerung_wenn_rechnung_gestellt(db):
    kid = _make_kunde(firma="Schon Bezahlt GmbH", rechnung_email="x@sb.example")
    eid = make_event(datum=date.today() - timedelta(days=1), kunde_id=kid,
                     kunde_firma="Schon Bezahlt GmbH", rechnung_gestellt=True)
    _run_rechnung_erinnerungen(db)
    assert reload(Event, eid).rechnung_mail_erinnert is False
    assert _meldungen("Schon Bezahlt") == []


def test_checkliste_uebernimmt_rechnungsmail_in_kartei(client):
    kid = _make_kunde(firma="Checklisten AG")
    eid = make_event(datum=date.today() + timedelta(days=20), kunde_id=kid,
                     kunde_firma="Checklisten AG", checklist_token="cl-re-test-1")
    r = client.post("/checklist/cl-re-test-1", data={
        "ansprechpartner_name": "Frau Check", "ansprechpartner_mobil": "0151 9",
        "rechnung_email": "billing@cl.example",
    })
    assert r.status_code == 200
    assert reload(Event, eid).cl_rechnung_email == "billing@cl.example"
    assert reload(Kunde, kid).rechnung_email == "billing@cl.example"  # in Kartei übernommen
