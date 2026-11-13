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


def test_abschluss_karte_zeigt_rechnungsangaben(admin):
    # Aykut 04.11.2026: Hinweis direkt neben „Als gestellt markieren", nicht nur per Glocke
    kid = _make_kunde(firma="Hinweis Karte AG", rechnung_email="buchhaltung@hk.example")
    eid = make_event(datum=date.today() - timedelta(days=1), kunde_id=kid,
                     kunde_firma="Hinweis Karte AG", cl_rechnung_firma="HK Holding SE")
    html = admin.get(f"/admin/events/{eid}").text
    assert "Besondere Rechnungsangaben" in html
    assert "mailto:buchhaltung@hk.example" in html and "HK Holding SE" in html
    ohne = make_event(datum=date.today() - timedelta(days=1), kunde_firma="Normal GmbH")
    assert "Besondere Rechnungsangaben" not in admin.get(f"/admin/events/{ohne}").text


def test_erechnung_kartei_checkliste_und_hinweise(admin, client, db):
    # Aykut 13.11.2026: E-Rechnungspflicht ab 2027 → X-Rechnung/ZUGFeRD optional ankreuzbar
    from choices import erechnung_wert
    assert erechnung_wert([]) is None
    assert erechnung_wert(["ZUGFeRD", "X-Rechnung"]) == "X-Rechnung, ZUGFeRD"
    # Kundenkartei: ankreuzen, speichern, wieder anzeigen
    r = admin.post("/admin/crm/new", data={"firma": "ERechnung AG", "erechnung": ["ZUGFeRD"],
                                           "leitweg_id": "05113000-12345-67"},
                   follow_redirects=False)
    kid = int(r.headers["location"].rstrip("/").split("/")[-1])
    assert reload(Kunde, kid).erechnung == "ZUGFeRD"
    assert reload(Kunde, kid).leitweg_id == "05113000-12345-67"
    kartei = admin.get(f"/admin/crm/{kid}").text
    assert "E-Rechnung: ZUGFeRD" in kartei and "Leitweg-ID: 05113000-12345-67" in kartei
    # Checkliste: Auswahl am Event und in der Kartei; Hinweis + Glocke nach dem Event
    eid = make_event(datum=date.today() + timedelta(days=10), kunde_id=kid,
                     kunde_firma="ERechnung AG", kunde_email="k@er.example")
    admin.post(f"/admin/events/{eid}/checklist", follow_redirects=False)
    tok = reload(Event, eid).checklist_token
    assert "X-Rechnung" in client.get(f"/checklist/{tok}").text
    client.post(f"/checklist/{tok}", data={
        "ansprechpartner_name": "X", "verpflegung": "Ja", "teamkleidung": "Ja", "ort_gleich": "Ja",
        "erechnung": ["X-Rechnung", "ZUGFeRD"], "leitweg_id": "05113000-99999-11"})
    assert reload(Event, eid).cl_erechnung == "X-Rechnung, ZUGFeRD"
    assert reload(Kunde, kid).erechnung == "X-Rechnung, ZUGFeRD"
    assert reload(Event, eid).cl_leitweg_id == reload(Kunde, kid).leitweg_id == "05113000-99999-11"
    assert "Als E-Rechnung im Format X-Rechnung, ZUGFeRD erstellen" in admin.get(f"/admin/events/{eid}").text
    vorbei = make_event(datum=date.today() - timedelta(days=1), kunde_id=kid,
                        kunde_firma="ERechnung AG Glocke")
    _run_rechnung_erinnerungen(db)
    assert any("E-Rechnung im Format" in m.text and "Leitweg-ID: 05113000-99999-11" in m.text
               for m in _meldungen("ERechnung AG Glocke"))
    assert reload(Event, vorbei).rechnung_mail_erinnert is True
