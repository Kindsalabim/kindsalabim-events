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


ECHT_CSV = """Teil;Organisation;Art;Ort;Kontaktweg;Quelle;Veranstaltung;üblicher Termin;Ansprachemonat;Warum passt das;Beleg;Typ/Spur
1 Firma/Aussteller;Sparkasse Musterstadt;Aussteller;Musterstadt;info@spk-muster.de · 02324/203-0;https://spk-muster.de/sponsoring;Altstadtfest;Ende Mai;Okt–Dez;Eigener Kinderbereich;Snippet;Sparkasse
"""


def test_import_versteht_das_format_der_recherche_session(admin, db):
    """Mail und Telefon stehen in einer Zelle, der Monat ist ein Bereich."""
    _leeren()
    _import(admin, ECHT_CSV)
    k = db.query(Kunde).filter(Kunde.firma == "Sparkasse Musterstadt").first()
    assert k.email == "info@spk-muster.de"          # Telefon nicht mit in die Mailadresse
    assert k.telefon and k.telefon.startswith("02324")
    assert k.ansprachemonat == 10                   # „Okt–Dez" → erster Monat
    assert k.branche == "Sparkasse"
    assert k.quelle_beleg == "snippet"
    # Ungeprüfte Adressen sind in der Liste markiert
    assert "Adresse prüfen" in admin.get("/admin/crm/akquise").text


# ── Übergabe an den E-Mail-Assistenten ──────────────────────────────────────

def _kontakt(db, firma="Übergabe GmbH", email="info@uebergabe.example", status="lead"):
    k = Kunde(firma=firma, email=email, herkunft="akquise", pipeline_status=status,
              quelle="https://beispiel.de/liste", branche="Sparkasse")
    db.add(k); db.commit()
    return k


def test_uebergabe_respektiert_sperre_und_fehlende_mail(admin, db, monkeypatch):
    _leeren()
    import routes.crm as crm
    angefordert = []
    monkeypatch.setattr(crm, "entwurf_anfordern", lambda kid: angefordert.append(kid))
    frei = _kontakt(db, "Frei GmbH", "info@frei.example")
    gesperrt = _kontakt(db, "Gesperrt GmbH", "info@gesperrt.example")
    ohne = _kontakt(db, "Ohne Mail GmbH", "")
    vertrieb.sperren(db, "adresse", "info@gesperrt.example", "widerspruch")
    r = admin.post("/admin/crm/akquise/uebergeben",
                   data={"kunde_ids": [str(frei.id), str(gesperrt.id), str(ohne.id)]},
                   follow_redirects=False)
    ziel = r.headers["location"]
    assert "uebergeben=1" in ziel and "gesperrt_u=1" in ziel and "ohne_mail=1" in ziel
    assert angefordert == [frei.id]


def test_tageslimit_begrenzt_die_uebergabe(admin, db, monkeypatch):
    _leeren()
    import routes.crm as crm
    from notifications import set_setting
    angefordert = []
    monkeypatch.setattr(crm, "entwurf_anfordern", lambda kid: angefordert.append(kid))
    set_setting(db, vertrieb.LIMIT_KEY, "2"); db.commit()
    ids = [str(_kontakt(db, f"Limit {i} GmbH", f"info@limit{i}.example").id) for i in range(4)]
    admin.post("/admin/crm/akquise/uebergeben", data={"kunde_ids": ids}, follow_redirects=False)
    assert len(angefordert) == 2
    set_setting(db, vertrieb.LIMIT_KEY, ""); db.commit()


# ── Schnittstelle, die der Assistent nutzt ──────────────────────────────────

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}


def _mit_secret(monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})


def test_api_braucht_das_secret(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    assert admin.get("/admin/crm/api/vertrieb/pruefen?email=a@b.de").status_code == 401
    assert admin.get("/admin/crm/api/vertrieb/pruefen?email=a@b.de",
                     headers={"X-Vertrieb-Secret": "falsch"}).status_code == 401
    r = admin.get("/admin/crm/api/vertrieb/pruefen?email=a@b.de", headers=GEHEIM)
    assert r.status_code == 200 and r.json()["darf"] is True


def test_api_pruefen_sieht_die_sperre(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    vertrieb.sperren(db, "domain", "gesperrt.example", "widerspruch")
    r = admin.get("/admin/crm/api/vertrieb/pruefen?email=info@gesperrt.example", headers=GEHEIM)
    assert r.json()["darf"] is False and "gesperrt" in r.json()["grund"]


def test_api_gesendet_protokolliert_und_schiebt_die_pipeline(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Gesendet GmbH", "info@gesendet.example")
    r = admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
                   json={"kunde_id": k.id, "betreff": "Kinderprogramm für Ihr Fest"})
    assert r.status_code == 200
    db.expire_all()
    log = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == k.id).first()
    assert log.weg == "mail" and log.quelle == "https://beispiel.de/liste"
    assert db.query(Kunde).filter(Kunde.id == k.id).first().pipeline_status == "kontakt"


def test_api_widerspruch_sperrt_alle_ebenen(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Widerspruch GmbH", "info@widerspruch.example")
    admin.post("/admin/crm/api/vertrieb/sperren", headers=GEHEIM,
               json={"kunde_id": k.id, "grund": "widerspruch"})
    db.expire_all()
    assert vertrieb.darf_kontaktieren(db, email="anders@widerspruch.example")[0] is False
    assert db.query(Kunde).filter(Kunde.id == k.id).first().pipeline_status == "verloren"
    assert vertrieb.versand_gestoppt(db) is False      # einfacher Widerspruch stoppt nicht alles


def test_api_abmahnung_loest_den_notaus_aus(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Anwalt GmbH", "info@anwalt.example")
    admin.post("/admin/crm/api/vertrieb/sperren", headers=GEHEIM,
               json={"kunde_id": k.id, "grund": "abmahnung", "notiz": "Schreiben vom 05.10."})
    db.expire_all()
    assert vertrieb.versand_gestoppt(db) is True
    assert vertrieb.darf_kontaktieren(db, email="ganz@andere.example")[0] is False
    vertrieb.versand_stoppen(db, False)


def test_tageslimit_laesst_sich_einstellen(admin, db):
    """Aufwärmphase einer neuen Absenderadresse: erst 5, dann 10, dann hoch."""
    _leeren()
    admin.post("/admin/crm/akquise/limit", data={"limit": "5"}, follow_redirects=False)
    assert vertrieb.tageslimit(db) == 5
    assert "Heute noch 5 von 5" in admin.get("/admin/crm/akquise").text
    admin.post("/admin/crm/akquise/limit", data={"limit": "0"}, follow_redirects=False)
    assert vertrieb.tageslimit(db) == 5          # unsinnige Werte ändern nichts
    from notifications import set_setting
    set_setting(db, vertrieb.LIMIT_KEY, ""); db.commit()
