"""Verbindungs-Monitor (Aykut 10.10.2026).

Vom 06. bis 09.10.2026 scheiterten alle Versandmeldungen des E-Mail-Assistenten mit
HTTP 500, und niemand merkte es. Jetzt landet jeder Aufruf zwischen den Apps mit
Ergebnis im Verbindungslog, die Seite „Verbindungen" zeigt eine Ampel, und die Glocke
meldet eine gestörte Verbindung einmal am Tag.

Kein Test erreicht das Netz: ausgehende Aufrufe laufen gegen gemockte urlopen-Aufrufe.
"""
import urllib.request
from datetime import datetime, timedelta

import verbindungen
from database import SessionLocal
from factories import make_event
from models import AppEinstellung, Benachrichtigung, EventDatei, Kunde, Verbindungslog

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}


def _leeren():
    s = SessionLocal()
    try:
        s.query(Verbindungslog).delete()
        s.query(AppEinstellung).filter(
            AppEinstellung.key.like("verbindung_glocke:%")).delete(synchronize_session=False)
        s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "verbindung_fehler").delete()
        s.commit()
    finally:
        s.close()


def _mit_secret(monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})


def _log(db, schnittstelle):
    db.expire_all()
    return (db.query(Verbindungslog).filter(Verbindungslog.schnittstelle == schnittstelle)
            .order_by(Verbindungslog.id).all())


def _glocken(db):
    db.expire_all()
    return db.query(Benachrichtigung).filter(Benachrichtigung.typ == "verbindung_fehler").count()


def _kein_netz(monkeypatch, fehler=OSError("Verbindung abgelehnt")):
    def _urlopen(*a, **kw):
        raise fehler
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)


# ── Eingehend: Aufrufe des E-Mail-Assistenten ────────────────────────────────

def test_erfolgreiche_meldung_wird_protokolliert(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    k = Kunde(firma="Monitor OK GmbH", email="info@monitor-ok.example", herkunft="akquise",
              pipeline_status="lead")
    db.add(k); db.commit()
    r = admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
                   json={"kunde_id": str(k.id), "betreff": "Hallo"})
    assert r.status_code == 200
    eintraege = _log(db, "assistent.gesendet")
    assert len(eintraege) == 1 and eintraege[0].ok and eintraege[0].status_code == 200
    assert eintraege[0].richtung == "ein"
    assert _glocken(db) == 0


def test_falsches_secret_ist_ein_fehler_mit_klartext(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    admin.post("/admin/crm/api/vertrieb/gesendet", headers={"X-Vertrieb-Secret": "falsch"},
               json={"kunde_id": 1})
    e = _log(db, "assistent.gesendet")[-1]
    assert not e.ok and e.status_code == 401
    assert "Secret" in e.fehler


def test_glocke_meldet_einmal_am_tag_je_verbindung(admin, db, monkeypatch):
    _leeren()
    _mit_secret(monkeypatch)
    for _ in range(3):
        admin.post("/admin/crm/api/vertrieb/antwort", headers=GEHEIM,
                   json={"kunde_id": "999999"})                    # unbekannt → 404
    assert len(_log(db, "assistent.antwort")) == 3                 # alles protokolliert
    assert _glocken(db) == 1                                       # aber nur eine Glocke
    # eine andere gestörte Verbindung bekommt ihre eigene Meldung
    admin.post("/admin/crm/api/vertrieb/angebot", headers=GEHEIM, json={"kunde_id": "999999"})
    assert _glocken(db) == 2


def test_andere_pfade_werden_nicht_protokolliert(admin, db):
    _leeren()
    admin.get("/admin/crm/akquise")
    db.expire_all()
    assert db.query(Verbindungslog).count() == 0


# ── Ausgehend: Events-App ruft die anderen Apps ─────────────────────────────

def test_uebergabe_an_assistent_ohne_netz_wird_als_fehler_erfasst(db, monkeypatch):
    _leeren()
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {
        "assistent_api_url": "http://assistent.invalid", "assistent_api_secret": "x"})
    _kein_netz(monkeypatch)
    k = Kunde(firma="Monitor Aus GmbH", email="info@monitor-aus.example", herkunft="akquise",
              pipeline_status="lead", anlass="Test")
    db.add(k); db.commit()
    crm.entwurf_anfordern(k.id)
    e = _log(db, "assistent.entwurf")[-1]
    assert not e.ok and "Verbindung abgelehnt" in e.fehler
    assert e.bezug == f"kunde-{k.id}" and e.richtung == "aus"
    assert _glocken(db) == 1


def test_fehlende_render_variable_ist_sichtbar(db, monkeypatch):
    _leeren()
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {})
    _kein_netz(monkeypatch)
    k = Kunde(firma="Monitor Leer GmbH", email="info@monitor-leer.example", herkunft="akquise")
    db.add(k); db.commit()
    crm.entwurf_anfordern(k.id)
    assert "fehlt in Render" in _log(db, "assistent.entwurf")[-1].fehler


def test_foto_an_social_app_erfolg_und_fehler(db, monkeypatch):
    _leeren()
    import routes.admin as adm
    monkeypatch.setattr(adm, "get_config", lambda: {
        "social_api_url": "http://social.invalid", "social_api_secret": "x"})
    eid = make_event()
    d = EventDatei(event_id=eid, r2_key="k/foto.jpg", filename="foto.jpg",
                   typ="bericht_foto", uploaded_at=datetime.now().isoformat())
    db.add(d); db.commit()

    class _Antwort:
        status = 200
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _Antwort())
    adm.social_quickpost_senden(d.id)
    assert _log(db, "social.quickpost")[-1].ok

    _kein_netz(monkeypatch)
    adm.social_quickpost_senden(d.id)
    e = _log(db, "social.quickpost")[-1]
    assert not e.ok and "Foto nicht angekommen" in e.fehler


# ── Seite und Aufräumen ─────────────────────────────────────────────────────

def test_seite_zeigt_ampel_je_verbindung(admin, db, monkeypatch):
    _leeren()
    verbindungen.protokollieren("assistent.gesendet", True, 200)
    verbindungen.protokollieren("social.quickpost", False, None, "Foto nicht angekommen: x")
    h = admin.get("/admin/verbindungen").text
    for schluessel in verbindungen.SCHNITTSTELLEN:
        assert schluessel in h                       # auch nie gerufene stehen da
    assert 'data-ampel="gruen"' in h and 'data-ampel="rot"' in h and 'data-ampel="grau"' in h
    assert "Foto nicht angekommen" in h
    assert 'href="/admin/verbindungen"' in h        # in der Navigation


def test_eintraege_aelter_als_30_tage_werden_geloescht(db):
    _leeren()
    alt = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
    db.add(Verbindungslog(erstellt_am=alt, schnittstelle="assistent.pruefen", ok=True))
    db.commit()
    verbindungen.protokollieren("assistent.pruefen", True, 200)
    db.expire_all()
    eintraege = db.query(Verbindungslog).all()
    assert len(eintraege) == 1 and eintraege[0].erstellt_am != alt


def test_tabelle_laesst_sich_in_postgres_anlegen():
    """Tests laufen gegen SQLite. Die neue Tabelle muss auch als Postgres-DDL sauber
    sein (Vorfall 03.09.2026: ein ALTER scheiterte in Postgres still)."""
    from sqlalchemy.dialects.postgresql import psycopg
    from sqlalchemy.schema import CreateTable
    ddl = str(CreateTable(Verbindungslog.__table__).compile(dialect=psycopg.dialect()))
    assert "CREATE TABLE verbindungslog" in ddl
    assert "ok BOOLEAN" in ddl and "DEFAULT" not in ddl


# ── Abgleich mit dem Schnittstellen-Vertrag (11.10.2026) ────────────────────

def _uebergabe_abfangen(monkeypatch):
    import json
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {
        "assistent_api_url": "http://assistent.invalid", "assistent_api_secret": "x"})
    gesendet = {}

    class _Antwort:
        status = 200
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _urlopen(req, timeout=0):
        gesendet.update(json.loads(req.data.decode("utf-8")))
        return _Antwort()
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return crm, gesendet


def test_sammelpostfach_geht_ohne_namen_an_den_assistenten(db, monkeypatch):
    """Der Assistent liest mail_art nicht und erkennt ein Sammelpostfach nur am leeren
    Ansprechpartner (Vertrag 2.1)."""
    crm, gesendet = _uebergabe_abfangen(monkeypatch)
    k = Kunde(firma="Sammel GmbH", email="info@sammel.example", herkunft="akquise",
              ansprechpartner="Max Schmidt", mail_art="funktion", anlass="Test")
    db.add(k); db.commit()
    crm.entwurf_anfordern(k.id)
    assert gesendet["ansprechpartner"] == "" and gesendet["mail_art"] == "funktion"


def test_persoenliche_adresse_behaelt_den_namen(db, monkeypatch):
    crm, gesendet = _uebergabe_abfangen(monkeypatch)
    k = Kunde(firma="Person GmbH", email="m.schmidt@person.example", herkunft="akquise",
              ansprechpartner="Max Schmidt", mail_art="person", anlass="Test")
    db.add(k); db.commit()
    crm.entwurf_anfordern(k.id)
    assert gesendet["ansprechpartner"] == "Max Schmidt"


def test_alle_meldungen_antworten_mit_genau_200(admin, db, monkeypatch):
    """Der Assistent wertet nur HTTP 200 als Erfolg (Vertrag 2.2). 201 oder 204 hielte
    er für gescheitert."""
    _mit_secret(monkeypatch)
    k = Kunde(firma="Status 200 GmbH", email="info@status200.example", herkunft="akquise",
              pipeline_status="lead")
    db.add(k); db.commit()
    assert admin.get("/admin/crm/api/vertrieb/pruefen?email=x@y.example",
                     headers=GEHEIM).status_code == 200
    for pfad in ("gesendet", "antwort", "angebot", "sperren"):
        r = admin.post(f"/admin/crm/api/vertrieb/{pfad}", headers=GEHEIM,
                       json={"kunde_id": str(k.id), "betreff": "x", "grund": "eigene"})
        assert r.status_code == 200, pfad


def test_sperren_ohne_treffer_ist_kein_erfolg(admin, db, monkeypatch):
    """Findet die Events-App den Kontakt nicht, darf sie nicht 200 melden: Der
    Assistent hielte den Widerspruch sonst für erledigt."""
    import vertrieb
    _mit_secret(monkeypatch)
    r = admin.post("/admin/crm/api/vertrieb/sperren", headers=GEHEIM,
                   json={"kunde_id": "999999", "grund": "widerspruch", "notiz": "x"})
    assert r.status_code == 404
    # Anwaltspost ohne Treffer: Not-Aus greift trotzdem, die Antwort zeigt aber den Fehler
    r = admin.post("/admin/crm/api/vertrieb/sperren", headers=GEHEIM,
                   json={"kunde_id": "999999", "grund": "abmahnung", "notiz": "x"})
    assert r.status_code == 404
    assert vertrieb.versand_gestoppt(db)
    vertrieb.versand_stoppen(db, False)
