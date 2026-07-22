"""CRM-Verknüpfen füllt Kundenprofile: Adresse + leere Felder aus dem Event nachziehen.
Hintergrund: link_kunde legte Profile ohne Adresse an → das Kunden-Autofill im
Event-Formular blieb leer (Aykuts Fall B, 22.07.2026). Gepflegte CRM-Daten
dürfen dabei nie überschrieben werden."""
from types import SimpleNamespace

from factories import reload
from models import Kunde
from routes.admin import link_kunde, _adresse_in_profil


def _ev(adresse=None):
    return SimpleNamespace(kunde_adresse=adresse, kunde_id=None)


def test_adresse_wird_in_teile_zerlegt():
    k = Kunde(firma="x")
    assert _adresse_in_profil(k, "Musterweg 5, 45127 Essen")
    assert (k.strasse, k.plz, k.ort) == ("Musterweg 5", "45127", "Essen")


def test_adresse_ohne_plz_landet_in_strasse():
    k = Kunde(firma="x")
    assert _adresse_in_profil(k, "Gewerbepark Süd, Halle 3")
    assert k.strasse == "Gewerbepark Süd, Halle 3" and not k.plz and not k.ort


def test_gepflegte_adresse_bleibt_unangetastet():
    k = Kunde(firma="x", strasse="Alte Straße 1")
    assert not _adresse_in_profil(k, "Musterweg 5, 45127 Essen")
    assert k.strasse == "Alte Straße 1"


def test_neuer_kunde_bekommt_adresse_und_kontakt(db):
    ev = _ev("Beispielstr. 2, 45127 Essen")
    link_kunde(db, ev, "Backfill Neu GmbH", "Max Muster", "0201 99", "max@neu.de", "Knallfrosch")
    db.commit()
    k = db.query(Kunde).filter(Kunde.firma == "Backfill Neu GmbH").one()
    assert (k.strasse, k.plz, k.ort) == ("Beispielstr. 2", "45127", "Essen")
    assert (k.ansprechpartner, k.telefon, k.email) == ("Max Muster", "0201 99", "max@neu.de")
    assert ev.kunde_id == k.id


def test_bestehendes_profil_wird_nachgefuellt_aber_nie_ueberschrieben(db):
    db.add(Kunde(firma="Backfill Alt AG", email="crm@alt.de"))   # lückenhaftes Altprofil
    db.commit()
    ev = _ev("Neuweg 9, 44135 Dortmund")
    link_kunde(db, ev, "backfill alt ag", "Erika Alt", "0231 11", "event@alt.de", "Kindsalabim")
    db.commit()
    k = db.query(Kunde).filter(Kunde.firma == "Backfill Alt AG").one()
    assert (k.strasse, k.plz, k.ort) == ("Neuweg 9", "44135", "Dortmund")   # Lücke gefüllt
    assert k.ansprechpartner == "Erika Alt" and k.telefon == "0231 11"      # Lücken gefüllt
    assert k.email == "crm@alt.de"                                          # CRM gewinnt


def test_backfill_fuellt_altprofile_aus_juengstem_event(db):
    from datetime import date
    from main import backfill_kunden
    from factories import make_event
    db.add(Kunde(firma="Backfill Startup KG", telefon="0201 55"))   # Altprofil mit Lücken
    db.commit()
    kid = db.query(Kunde).filter(Kunde.firma == "Backfill Startup KG").one().id
    make_event(kunde_firma="Backfill Startup KG", kunde_id=kid, datum=date(2025, 5, 1),
               kunde_adresse="Altweg 1, 40210 Düsseldorf", kunde_kontakt="Alt Kontakt",
               kunde_telefon="0211 1", kunde_email="alt@startup.de")
    make_event(kunde_firma="Backfill Startup KG", kunde_id=kid, datum=date(2026, 6, 1),
               kunde_adresse="Neuweg 2, 45127 Essen", kunde_email="neu@startup.de")
    backfill_kunden()
    k = reload(Kunde, kid)
    assert (k.strasse, k.plz, k.ort) == ("Neuweg 2", "45127", "Essen")   # jüngstes Event zuerst
    assert k.email == "neu@startup.de"
    assert k.ansprechpartner == "Alt Kontakt"   # Lücke aus dem älteren Event gefüllt
    assert k.telefon == "0201 55"               # bestehender CRM-Wert bleibt


def test_backfill_ist_idempotent_und_laesst_volle_profile_in_ruhe(db):
    from main import backfill_kunden
    db.add(Kunde(firma="Backfill Voll GmbH", strasse="Fertigstr. 1", plz="45127", ort="Essen",
                 ansprechpartner="Frau Fertig", telefon="0201 66", email="voll@fertig.de",
                 aktualisiert_am="2026-01-01T00:00:00"))
    db.commit()
    backfill_kunden(); backfill_kunden()
    k = db.query(Kunde).filter(Kunde.firma == "Backfill Voll GmbH").one()
    db.refresh(k)
    assert k.aktualisiert_am == "2026-01-01T00:00:00"   # nicht angefasst


def test_event_anlegen_mit_verknuepfung_fuellt_profil(admin, db):
    r = admin.post("/admin/events/new", data={
        "anlass": "Sommerfest", "datum": "2026-08-05", "startzeit": "14:00", "endzeit": "18:00",
        "kunde_firma": "Backfill E2E GmbH", "kunde_adresse": "Endtestweg 7, 45356 Essen",
        "kunde_kontakt": "Enno Ende", "kunde_telefon": "0201 77", "kunde_email": "e@e2e.de",
        "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht",
        "crm_verknuepfen": "true",
    }, follow_redirects=False)
    assert r.status_code == 303
    k = db.query(Kunde).filter(Kunde.firma == "Backfill E2E GmbH").one()
    assert (k.strasse, k.plz, k.ort) == ("Endtestweg 7", "45356", "Essen")
    # Damit liefert das Event-Formular die Daten jetzt im Autofill-JSON mit
    assert "Endtestweg 7" in admin.get("/admin/events/new").text
