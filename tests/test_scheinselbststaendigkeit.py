"""Scheinselbstständigkeits-Vorsorge: AGB-Bestätigung, Selbstauskunft,
Nachweis-Dossier, Anwalts-Scoring (V7)."""
from datetime import date

from database import SessionLocal
from models import Dienstleister
from factories import make_dienstleister, make_event, make_anfrage, reload, portal_login
import scoring


def _dl(**kw):
    return make_dienstleister(**kw)


# ── AGB ───────────────────────────────────────────────────────────────────────

def test_agb_seite_im_portal_einsehbar(client):
    portal_login(client, _dl())
    h = client.get("/portal/agb").text
    assert "Allgemeine Geschäftsbedingungen" in h
    assert "Malca &amp; Akmanoglu GbR" in h and "Kindsalabim Kinderevents" in h
    assert "§ 11 Allgemeine Bestimmungen" in h
    # Datenschutz-Verweis zeigt ins Portal, kein toter externer Link
    assert "im Dienstleister-Portal" in h and "LINK XXX" not in h


def test_agb_bestaetigung_speichert_zeitstempel_und_ip(client):
    did = _dl()
    portal_login(client, did)
    r = client.post("/portal/profil/agb", data={"agb_akzeptiert": "true"},
                    follow_redirects=False)
    assert r.status_code == 303 and "agb=1" in r.headers["location"]
    d = reload(Dienstleister, did)
    assert d.agb_akzeptiert_am and d.agb_ip
    # Karte zeigt grünen Status statt Formular
    h = client.get("/portal/profil").text
    assert "Bestätigt am" in h


def test_agb_ohne_haken_wird_abgelehnt(client):
    did = _dl()
    portal_login(client, did)
    r = client.post("/portal/profil/agb", data={}, follow_redirects=False)
    assert "agb_fehler=1" in r.headers["location"]
    assert reload(Dienstleister, did).agb_akzeptiert_am is None


def test_agb_anfrage_button_mailt_nur_unbestaetigte(admin, mails):
    offen = _dl()
    fertig = _dl(agb_akzeptiert_am="2026-08-01T10:00:00")
    inaktiv = _dl(aktiv=False)
    r = admin.post("/admin/dienstleister/agb-anfrage", follow_redirects=False)
    assert r.status_code == 303 and "agb_angefragt=" in r.headers["location"]
    empfaenger = [m[0] for m in mails if "Zusammenarbeits-Bedingungen" in m[1]]
    assert reload(Dienstleister, offen).email in empfaenger
    assert reload(Dienstleister, fertig).email not in empfaenger
    assert reload(Dienstleister, inaktiv).email not in empfaenger


# ── Selbstauskunft ────────────────────────────────────────────────────────────

def test_selbstauskunft_speichert_neue_felder(client):
    did = _dl()
    portal_login(client, did)
    client.post("/portal/profil", data={
        "weitere_auftraggeber": "true", "betriebshaftpflicht": "true",
        "website": "https://beispiel-profil.example"}, follow_redirects=False)
    d = reload(Dienstleister, did)
    assert d.weitere_auftraggeber and d.betriebshaftpflicht
    assert d.website == "https://beispiel-profil.example"


def test_admin_karte_zeigt_selbstauskunft_und_agb_status(admin):
    did = _dl(weitere_auftraggeber=True, agb_akzeptiert_am="2026-08-10T09:00:00")
    h = admin.get(f"/admin/dienstleister/{did}").text
    assert "Weitere Auftraggeber" in h and "lt. Selbstauskunft ja" in h
    assert "bestätigt am 2026-08-10" in h
    assert "dossier.pdf" in h


# ── Scoring (Anwalts-System V7) ───────────────────────────────────────────────

def test_scoring_berechnung_wie_excel():
    # Score = Gewicht × Ausprägung; kritische Schwelle 130
    werte = {"weisung": 3, "eingliederung": 3, "stundensatz": 2}   # 60 + 60 + 30 = 150
    assert scoring.gesamt_score(werte) == 150
    assert scoring.ampel(150) == "rot"
    assert scoring.ampel(129) == "gelb"
    assert scoring.ampel(99) == "gruen"
    assert scoring.MAX_SCORE == 3 * sum(g for _, _, g in scoring.KRITERIEN)


def test_scoring_parse_ist_robust():
    assert scoring.parse_werte(None) == {}
    assert scoring.parse_werte("kaputt{") == {}
    assert scoring.parse_werte('{"weisung": 9, "unbekannt": 1}') == {"weisung": 3}


def test_scoring_speichern_und_ampel_in_karte(admin):
    did = _dl()
    daten = {f"sc_{k}": "0" for k, _, _ in scoring.KRITERIEN}
    daten.update({"sc_weisung": "3", "sc_eingliederung": "3", "sc_persoenlich": "1"})  # 140 → rot
    r = admin.post(f"/admin/dienstleister/{did}/scoring", data=daten, follow_redirects=False)
    assert r.status_code == 303
    d = reload(Dienstleister, did)
    assert d.scoring_datum == date.today().isoformat()
    assert scoring.gesamt_score(scoring.parse_werte(d.scoring_json)) == 140
    h = admin.get(f"/admin/dienstleister/{did}").text
    assert "140 Punkte" in h and "🔴" in h


def test_scoring_formular_zeigt_alle_kriterien(admin):
    h = admin.get(f"/admin/dienstleister/{_dl()}").text
    assert "Status-Scoring" in h
    for _, label, _ in scoring.KRITERIEN:
        assert label.split(" (")[0] in h


# ── Nachweis-Dossier ──────────────────────────────────────────────────────────

def test_dossier_pdf_mit_historie(admin):
    did = _dl(vorname="Doro", nachname="Dossier")
    make_anfrage(make_event(), did, status="Ja")
    make_anfrage(make_event(), did, status="Nein")
    make_anfrage(make_event(), did, status="Abgelaufen")
    r = admin.get(f"/admin/dienstleister/{did}/dossier.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 2000


def test_dossier_pdf_auch_ohne_anfragen(admin):
    r = admin.get(f"/admin/dienstleister/{_dl()}/dossier.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
