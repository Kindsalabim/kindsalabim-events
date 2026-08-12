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


def test_checkliste_speichert_abweichende_rechnungsadresse(client, db):
    eid = make_event(datum=date.today() + timedelta(days=20),
                     kunde_firma="Signatur GmbH", checklist_token="cl-re-test-2")
    r = client.post("/checklist/cl-re-test-2", data={
        "ansprechpartner_name": "Hr. Sig",
        "rechnung_firma": "Signatur Holding GmbH & Co. KG",
        "rechnung_strasse": "Rechnungsweg 1", "rechnung_plz_ort": "45127 Essen",
    })
    assert r.status_code == 200
    ev = reload(Event, eid)
    assert ev.cl_rechnung_firma == "Signatur Holding GmbH & Co. KG"
    assert ev.cl_rechnung_strasse == "Rechnungsweg 1"
    # Anzeige im Event unter Kunden-Angaben
    from conftest import create_token  # admin-Client bauen wie in conftest
    client.cookies.set("admin_token", create_token({"sub": "a@b.de", "role": "admin"}, expires_minutes=60))
    h = client.get(f"/admin/events/{eid}").text
    assert "Signatur Holding GmbH &amp; Co. KG" in h


def test_erinnerung_auch_bei_abweichender_firmierung_ohne_mail(db):
    eid = make_event(datum=date.today() - timedelta(days=1),
                     kunde_firma="Nur Adresse GmbH",
                     cl_rechnung_firma="Nur Adresse Holding SE",
                     cl_rechnung_plz_ort="45127 Essen")
    _run_rechnung_erinnerungen(db)
    assert reload(Event, eid).rechnung_mail_erinnert is True
    m = _meldungen("Nur Adresse GmbH")
    assert len(m) == 1
    assert "Nur Adresse Holding SE" in m[0].text and "45127 Essen" in m[0].text
