"""Akquise-Bereich: Sperrliste, Not-Aus, Protokoll und CSV-Import (Aykut 04.10.2026).

Kaltakquise ist rechtlich heikel. Der Unterschied zur Akquise von Hand: Eine Maschine
vergisst nicht, weiß aber auch nicht von selbst, wen sie nie wieder anschreiben darf.
Deshalb prüft GENAU EINE Funktion vor jedem Versand, und zwar technisch, nicht per KI.
"""
import io
from datetime import datetime

import vertrieb
from database import SessionLocal
from models import Kunde, VertriebKontaktLog, VertriebSperre


def _leeren():
    s = SessionLocal()
    try:
        s.query(VertriebSperre).delete()
        s.query(VertriebKontaktLog).delete()
        s.query(Kunde).filter(Kunde.herkunft == "akquise").delete()
        s.commit()
        vertrieb.versand_stoppen(s, False)
    finally:
        s.close()


# ── Sperrliste ──────────────────────────────────────────────────────────────

def test_adresse_und_domain_sperren(db):
    _leeren()
    assert vertrieb.darf_kontaktieren(db, email="info@beispiel.de")[0] is True
    vertrieb.sperren(db, "adresse", "Info@Beispiel.de", "widerspruch")
    darf, grund = vertrieb.darf_kontaktieren(db, email="info@beispiel.de")
    assert darf is False and "gesperrt" in grund
    # andere Adresse derselben Firma noch frei – bis die Domain gesperrt wird
    assert vertrieb.darf_kontaktieren(db, email="event@beispiel.de")[0] is True
    vertrieb.sperren(db, "domain", "beispiel.de", "widerspruch")
    assert vertrieb.darf_kontaktieren(db, email="event@beispiel.de")[0] is False
    assert vertrieb.darf_kontaktieren(db, email="x@mail.beispiel.de")[0] is False


def test_unternehmen_wird_trotz_rechtsform_erkannt(db):
    _leeren()
    vertrieb.sperren(db, "unternehmen", "Muster Wohnbau GmbH", "unterlassung")
    for schreibweise in ("Muster Wohnbau GmbH", "muster wohnbau", "Muster Wohnbau gGmbH"):
        assert vertrieb.darf_kontaktieren(db, firma=schreibweise)[0] is False
    assert vertrieb.darf_kontaktieren(db, firma="Andere Wohnbau AG")[0] is True


def test_person_sperren(db):
    _leeren()
    vertrieb.sperren(db, "person", "Max Mustermann", "widerspruch")
    assert vertrieb.darf_kontaktieren(db, person="Max Mustermann")[0] is False
    assert vertrieb.darf_kontaktieren(db, person="Erika Musterfrau")[0] is True


def test_nie_wieder_sperrt_alle_ebenen_auf_einmal(admin, db):
    """Ein Widerspruch gilt für Adresse, Domain und Unternehmen zugleich."""
    _leeren()
    k = Kunde(firma="Beispiel Stadtwerke GmbH", email="info@stadtwerke-beispiel.de",
              herkunft="akquise", pipeline_status="lead")
    db.add(k); db.commit()
    admin.post(f"/admin/crm/akquise/{k.id}/sperren", data={"grund": "widerspruch"},
               follow_redirects=False)
    db.expire_all()
    assert vertrieb.darf_kontaktieren(db, email="info@stadtwerke-beispiel.de")[0] is False
    assert vertrieb.darf_kontaktieren(db, email="marketing@stadtwerke-beispiel.de")[0] is False
    assert vertrieb.darf_kontaktieren(db, firma="Beispiel Stadtwerke")[0] is False
    assert db.query(Kunde).filter(Kunde.id == k.id).first().pipeline_status == "verloren"


def test_freemail_domain_wird_nicht_gesperrt(db):
    """Sonst wäre nach einem Widerspruch halb gmail.de gesperrt."""
    _leeren()
    k = Kunde(firma="Einzelunternehmer Test", email="jemand@gmail.com", herkunft="akquise")
    db.add(k); db.commit()
    vertrieb.sperren_fuer_kunde(db, k)
    assert vertrieb.darf_kontaktieren(db, email="jemand@gmail.com")[0] is False
    assert vertrieb.darf_kontaktieren(db, email="jemand.anderes@gmail.com")[0] is True


# ── Not-Aus ─────────────────────────────────────────────────────────────────

def test_notaus_blockiert_alles(db):
    _leeren()
    assert vertrieb.darf_kontaktieren(db, email="frei@beispiel.de")[0] is True
    vertrieb.versand_stoppen(db, True)
    darf, grund = vertrieb.darf_kontaktieren(db, email="frei@beispiel.de")
    assert darf is False and "gestoppt" in grund
    vertrieb.versand_stoppen(db, False)
    assert vertrieb.darf_kontaktieren(db, email="frei@beispiel.de")[0] is True


def test_notaus_ueber_die_seite(admin, db):
    _leeren()
    admin.post("/admin/crm/akquise/notaus", data={"stoppen": "1"}, follow_redirects=False)
    assert vertrieb.versand_gestoppt(db) is True
    assert "gestoppt" in admin.get("/admin/crm/akquise").text
    admin.post("/admin/crm/akquise/notaus", data={"stoppen": "0"}, follow_redirects=False)
    assert vertrieb.versand_gestoppt(db) is False


# ── Protokoll ───────────────────────────────────────────────────────────────

def test_protokoll_haelt_quelle_fest(db):
    _leeren()
    k = Kunde(firma="Protokoll GmbH", email="info@protokoll.example",
              herkunft="akquise", quelle="https://beispiel.de/aussteller")
    db.add(k); db.commit()
    vertrieb.protokollieren(db, k, "mail", "Kinderprogramm für Ihr Fest")
    eintrag = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == k.id).first()
    assert eintrag.empfaenger == "info@protokoll.example"
    assert eintrag.quelle == "https://beispiel.de/aussteller"
    assert eintrag.weg == "mail" and eintrag.erstellt_am


# ── CSV-Import ──────────────────────────────────────────────────────────────

CSV = """Organisation;Art;Ort;Kontaktweg;Quelle;Veranstaltung;Ansprachemonat;Warum passt das
Stadtmarketing Musterstadt;Veranstalter;Musterstadt;stadtmarketing@musterstadt.de;https://musterstadt.de/fest;Parkfest;Dezember;Bucht Bühnenprogramm
Wohnbau Musterstadt eG;Aussteller;Musterstadt;info@wohnbau-muster.de;https://musterstadt.de/aussteller;Parkfest;3;Stand mit Kinderaktion
Ohne Beleg GmbH;Aussteller;Musterstadt;info@ohnebeleg.de;;Parkfest;3;Nur vermutet
"""


def _import(admin, text=CSV):
    return admin.post("/admin/crm/akquise/import",
                      files={"datei": ("liste.csv", io.BytesIO(text.encode("utf-8")), "text/csv")},
                      follow_redirects=False)


def test_import_uebernimmt_nur_belegte_zeilen(admin, db):
    _leeren()
    r = _import(admin)
    assert r.status_code == 303
    assert "neu=2" in r.headers["location"] and "ohne_quelle=1" in r.headers["location"]
    k = db.query(Kunde).filter(Kunde.firma == "Wohnbau Musterstadt eG").first()
    assert k.herkunft == "akquise" and k.pipeline_status == "lead"
    assert k.quelle.startswith("https://") and k.ansprachemonat == 3
    assert k.akquise_art == "Aussteller" and k.anlass == "Parkfest"
    # Monatsname wird genauso verstanden wie die Zahl
    sm = db.query(Kunde).filter(Kunde.firma == "Stadtmarketing Musterstadt").first()
    assert sm.ansprachemonat == 12
    assert db.query(Kunde).filter(Kunde.firma == "Ohne Beleg GmbH").first() is None


def test_import_ueberspringt_gesperrte_und_doppelte(admin, db):
    _leeren()
    _import(admin)
    vertrieb.sperren(db, "domain", "wohnbau-muster.de", "widerspruch")
    db.query(Kunde).filter(Kunde.firma == "Wohnbau Musterstadt eG").delete()
    db.commit()
    r = _import(admin)
    assert "neu=0" in r.headers["location"]
    assert "gesperrt=1" in r.headers["location"] and "doppelt=1" in r.headers["location"]
    assert db.query(Kunde).filter(Kunde.firma == "Wohnbau Musterstadt eG").first() is None


def test_akquise_kontakte_stehen_nicht_in_der_kundenliste(admin, db):
    _leeren()
    _import(admin)
    assert "Stadtmarketing Musterstadt" in admin.get("/admin/crm/akquise").text
    assert "Stadtmarketing Musterstadt" not in admin.get("/admin/crm").text
