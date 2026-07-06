"""Trennung Kundendaten (intern) vs. Veranstaltung (fürs Team-Briefing):
- Firmenadresse (kunde_adresse) wird gespeichert (intern, nicht im Briefing)
- Veranstaltungsort = Firmenadresse, außer „andere Adresse" (ort_abweichend)
- Ansprechpartner vor Ort (vor_ort_*) getrennt vom Buchungskontakt
- Briefing zeigt den Vor-Ort-Kontakt (Fallback cl_* → vor_ort_* → kunde_kontakt),
  aber NICHT die interne Firmenadresse
"""
from datetime import date, timedelta

import email_service
from models import Event
from factories import make_event, reload, briefing_event_ns, briefing_dl_ns

BALD = date.today() + timedelta(days=14)


def _form(**over):
    base = {"anlass": "Fest", "datum": BALD.isoformat(), "startzeit": "12:00", "endzeit": "16:00",
            "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht",
            "kunde_firma": "Muster AG", "kunde_adresse": "Hauptstr. 1, 45127 Essen"}
    base.update(over)
    return base


def test_ort_default_ist_firmenadresse(admin):
    eid = make_event()
    admin.post(f"/admin/events/{eid}/edit", data=_form(), follow_redirects=False)
    ev = reload(Event, eid)
    assert ev.kunde_adresse == "Hauptstr. 1, 45127 Essen"
    assert ev.veranstaltungsort == "Hauptstr. 1, 45127 Essen"   # ohne Häkchen = Firmenadresse


def test_ort_abweichend_wird_uebernommen(admin):
    eid = make_event()
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(ort_abweichend="1", veranstaltungsort="Marktplatz, 44137 Dortmund"),
               follow_redirects=False)
    ev = reload(Event, eid)
    assert ev.veranstaltungsort == "Marktplatz, 44137 Dortmund"
    assert ev.kunde_adresse == "Hauptstr. 1, 45127 Essen"       # Firmenadresse bleibt separat


def test_vor_ort_kontakt_getrennt_vom_buchungskontakt(admin):
    eid = make_event()
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(kunde_kontakt="Frau Müller", kunde_telefon="0201 111",
                          vor_ort_name="Herr Schmidt", vor_ort_telefon="0170 999"),
               follow_redirects=False)
    ev = reload(Event, eid)
    assert ev.kunde_kontakt == "Frau Müller"        # Buchungskontakt (intern)
    assert ev.vor_ort_name == "Herr Schmidt"        # Ansprechpartner vor Ort (fürs Team)
    assert ev.vor_ort_telefon == "0170 999"


def test_create_event_ort_und_vor_ort(admin):
    r = admin.post("/admin/events/new",
                   data=_form(vor_ort_name="Vor-Ort Anna", vor_ort_telefon="0151 222"),
                   follow_redirects=False)
    assert r.status_code == 303
    from database import SessionLocal
    s = SessionLocal()
    try:
        ev = s.query(Event).filter(Event.kunde_firma == "Muster AG").order_by(Event.id.desc()).first()
        assert ev.veranstaltungsort == "Hauptstr. 1, 45127 Essen"   # = Firmenadresse
        assert ev.vor_ort_name == "Vor-Ort Anna"
    finally:
        s.close()


def test_briefing_zeigt_vor_ort_nicht_firmenadresse(mails):
    ev = briefing_event_ns(veranstaltungsort="Marktplatz, 44137 Dortmund",
                           kunde_adresse="Geheime Firmenstr. 9, 45127 Essen",
                           vor_ort_name="Herr Schmidt", vor_ort_telefon="0170 999",
                           kunde_kontakt="Frau Müller (Buchung)", kunde_telefon="0201 111")
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x")
    html = mails[-1][2]
    assert "Herr Schmidt" in html and "0170 999" in html          # Vor-Ort-Kontakt sichtbar
    assert "Geheime Firmenstr." not in html                        # interne Firmenadresse NICHT
    assert "Frau Müller" not in html                               # Buchungskontakt NICHT (Vor-Ort hat Vorrang)
    assert "Marktplatz, 44137 Dortmund" in html                    # Veranstaltungsort schon


def test_briefing_fallback_auf_buchungskontakt(mails):
    # Kein cl_* und kein vor_ort_* → Fallback auf den alten Buchungskontakt (Altdaten)
    ev = briefing_event_ns(vor_ort_name="", vor_ort_telefon="",
                           kunde_kontakt="Alt Kontakt", kunde_telefon="0201 5")
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x")
    assert "Alt Kontakt" in mails[-1][2]
