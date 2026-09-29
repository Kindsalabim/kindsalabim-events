"""Eigene Aktionszeit je Anfrage (Aykut, 29.09.2026): Die Veranstaltung läuft 12–18 Uhr,
die Zaubershow aber nur 15–16 Uhr. Ohne eigene Zeit stand in der Anfrage 12–18 Uhr, und
der Künstler wäre viel zu früh angereist. Außerdem: Budget auch bei zugesagten Einsätzen
im Portal (Lars musste deswegen per WhatsApp nachfragen).
"""
from datetime import date, timedelta
from types import SimpleNamespace

import ankunft
from choices import einsatzzeit_text
from factories import make_anfrage, make_dienstleister, make_event, portal_login, reload
from models import Verfuegbarkeitsanfrage

TAG = date.today() + timedelta(days=30)


def _event():
    return make_event(datum=TAG, startzeit="12:00", endzeit="18:00",
                      kunde_firma="Stadtfest mit Bühne", produkte="Zaubershow")


# ── Text-Helfer ──────────────────────────────────────────────────────────────

def test_einsatzzeit_text():
    assert einsatzzeit_text(SimpleNamespace(einsatz_von="15:00", einsatz_bis="16:00")) == "15:00–16:00 Uhr"
    assert einsatzzeit_text(SimpleNamespace(einsatz_von="15:00", einsatz_bis=None)) == "ab 15:00 Uhr"
    assert einsatzzeit_text(SimpleNamespace(einsatz_von=None, einsatz_bis=None)) == ""


def test_ankunft_richtet_sich_nach_der_eigenen_zeit():
    ev = SimpleNamespace(startzeit="12:00", produkte="Zaubershow", ankunft_modus="60",
                         ankunft_text=None, material_mitnahme=False)
    ohne = ankunft.ankunft_fuer(ev, None)
    mit = ankunft.ankunft_fuer(ev, SimpleNamespace(einsatz_von="15:00"))
    assert "11:00" in ohne
    assert "14:00" in mit


# ── Anfrage senden ───────────────────────────────────────────────────────────

def test_anfrage_mail_nennt_die_eigene_aktionszeit(admin, mails):
    eid = _event()
    did = make_dienstleister(vorname="Zauber", rolle="Künstler", kuenstler_sparte="Showact")
    admin.post(f"/admin/events/{eid}/anfragen",
               data={"dienstleister_ids": [str(did)], "rolle": "Künstler",
                     "einsatz_von": "15:00", "einsatz_bis": "16:00", "budget": "300"})
    from models import Dienstleister
    adresse = reload(Dienstleister, did).email
    [(_, _betreff, html)] = [m for m in mails if m[0] == adresse]
    assert "Deine Aktionszeit" in html and "15:00 – 16:00 Uhr" in html
    assert "12:00 – 18:00 Uhr" in html          # Rahmen der Veranstaltung bleibt sichtbar
    a = [x for x in _anfragen(eid) if x.dienstleister_id == did][0]
    assert (a.einsatz_von, a.einsatz_bis) == ("15:00", "16:00")


def test_anfrage_ohne_eigene_zeit_bleibt_wie_bisher(admin, mails):
    eid = _event()
    did = make_dienstleister(vorname="Ganztags", rolle="Teamer")
    admin.post(f"/admin/events/{eid}/anfragen",
               data={"dienstleister_ids": [str(did)], "rolle": "Teamer"})
    from models import Dienstleister
    adresse = reload(Dienstleister, did).email
    [(_, _betreff, html)] = [m for m in mails if m[0] == adresse]
    assert "Deine Aktionszeit" not in html
    assert "12:00 – 18:00 Uhr" in html


def _anfragen(event_id):
    from database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == event_id).all()
    finally:
        s.close()


# ── Nachträglich ändern ──────────────────────────────────────────────────────

def test_aktionszeit_nachtraeglich_setzen_und_loeschen(admin):
    eid = _event()
    did = make_dienstleister(rolle="Künstler")
    aid = make_anfrage(eid, did, status="Ja", rolle="Künstler")
    admin.post(f"/admin/events/{eid}/anfrage/{aid}/aendern",
               data={"rolle": "Künstler", "einsatz_von": "15:00", "einsatz_bis": "16:00"})
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert (a.einsatz_von, a.einsatz_bis) == ("15:00", "16:00")
    admin.post(f"/admin/events/{eid}/anfrage/{aid}/aendern", data={"rolle": "Künstler"})
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.einsatz_von is None and a.einsatz_bis is None


# ── Portal ───────────────────────────────────────────────────────────────────

def test_portal_zeigt_aktionszeit_und_budget_beim_einsatz(client):
    eid = _event()
    did = make_dienstleister(vorname="Portal", rolle="Künstler")
    make_anfrage(eid, did, status="Ja", rolle="Künstler", budget=300.0,
                 einsatz_von="15:00", einsatz_bis="16:00")
    portal_login(client, did)
    html = client.get("/portal").text
    assert "Deine Aktionszeit: 15:00–16:00 Uhr" in html
    assert "Budget: 300,00 € pauschal" in html      # vorher nur bei offenen Anfragen sichtbar


def test_portal_ohne_eigene_zeit_zeigt_keine_zusatzzeile(client):
    eid = _event()
    did = make_dienstleister(vorname="Ohnezeit", rolle="Teamer")
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    portal_login(client, did)
    html = client.get("/portal").text
    assert "Deine Aktionszeit" not in html


# ── Briefing-PDF ─────────────────────────────────────────────────────────────

def test_briefing_pdf_nennt_die_aktionszeit():
    from briefing_pdf import build_briefing_pdf
    from models import Event
    eid = _event()
    ev = reload(Event, eid)
    team = [SimpleNamespace(id=1, vorname="Zauber", nachname="Künstlerin", telefon="0201 1",
                            kuenstler_sparte="Showact")]
    mit = build_briefing_pdf(ev, team, [], rollen={1: "Künstler"}, zeiten={1: "15:00–16:00 Uhr"})
    ohne = build_briefing_pdf(ev, team, [], rollen={1: "Künstler"})
    assert len(mit) > 1000 and len(ohne) > 1000
    assert mit != ohne
