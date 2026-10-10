"""Rückmeldungen aus dem E-Mail-Assistenten und der Weg vom Lead zum Kunden
(Aykut 08.10.2026).

Anlass: Nach den ersten Erstmails standen alle 111 Karten weiter auf „Neuer Lead",
und als die erste Firma Interesse zeigte, wusste die Events-App nichts davon.
"""
from types import SimpleNamespace

import httpx

import recherche
import vertrieb
from models import Benachrichtigung, Kunde, VertriebKontaktLog
from routes.admin import link_kunde

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}


def _mit_secret(monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})


def _kontakt(db, firma, email, status="lead"):
    k = Kunde(firma=firma, email=email, herkunft="akquise", pipeline_status=status)
    db.add(k); db.commit(); db.refresh(k)
    return k


def _status(db, kid):
    db.expire_all()
    return db.query(Kunde).filter(Kunde.id == kid).first().pipeline_status


# ── Schnittstelle ───────────────────────────────────────────────────────────

def test_gesendet_versteht_die_id_als_text(admin, db, monkeypatch):
    """Der Assistent speichert die Kunden-ID als Text und schickt "123" statt 123."""
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Text GmbH", "info@rm-text.example")
    r = admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
                   json={"kunde_id": str(k.id), "betreff": "Hallo",
                         "empfaenger": "info@rm-text.example"})
    assert r.status_code == 200
    assert _status(db, k.id) == "kontakt"


def test_gesendet_findet_den_kontakt_notfalls_ueber_die_adresse(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Adresse GmbH", "info@rm-adresse.example")
    r = admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
                   json={"kunde_id": "K-unbekannt", "betreff": "Hallo",
                         "empfaenger": "INFO@rm-adresse.example"})
    assert r.status_code == 200
    assert _status(db, k.id) == "kontakt"


def test_antwort_rueckt_auf_bedarf_und_laeutet_die_glocke(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Antwort GmbH", "info@rm-antwort.example", "kontakt")
    r = admin.post("/admin/crm/api/vertrieb/antwort", headers=GEHEIM,
                   json={"kunde_id": str(k.id), "betreff": "AW: Familienfest",
                         "email": "info@rm-antwort.example"})
    assert r.status_code == 200 and r.json()["status"] == "bedarf"
    assert _status(db, k.id) == "bedarf"
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "vertrieb_antwort",
        Benachrichtigung.titel.contains("Rueckmeldung Antwort GmbH")).count() == 1
    # Eine Antwort ist keine Versandmail und darf kein Tageslimit verbrauchen.
    assert db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == k.id,
                                               VertriebKontaktLog.weg == "antwort").count() == 1


def test_angebot_rueckt_auf_angebot(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Angebot GmbH", "info@rm-angebot.example", "bedarf")
    r = admin.post("/admin/crm/api/vertrieb/angebot", headers=GEHEIM,
                   json={"kunde_id": str(k.id), "betreff": "Ihr Angebot"})
    assert r.status_code == 200
    assert _status(db, k.id) == "angebot"


def test_rueckmeldungen_schieben_nie_rueckwaerts(admin, db, monkeypatch):
    """Eine späte Antwort darf ein gebuchtes oder verlorenes Event nicht zurücksetzen."""
    _mit_secret(monkeypatch)
    gebucht = _kontakt(db, "Rueckmeldung Gebucht GmbH", "info@rm-gebucht.example", "gebucht")
    verloren = _kontakt(db, "Rueckmeldung Verloren GmbH", "info@rm-verloren.example", "verloren")
    for k in (gebucht, verloren):
        for pfad in ("antwort", "angebot", "gesendet"):
            admin.post(f"/admin/crm/api/vertrieb/{pfad}", headers=GEHEIM,
                       json={"kunde_id": k.id})
    assert _status(db, gebucht.id) == "gebucht"
    assert _status(db, verloren.id) == "verloren"


def test_neue_endpunkte_brauchen_das_secret(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Geheim GmbH", "info@rm-geheim.example")
    for pfad in ("antwort", "angebot"):
        assert admin.post(f"/admin/crm/api/vertrieb/{pfad}",
                          json={"kunde_id": k.id}).status_code == 401
    assert _status(db, k.id) == "lead"


def test_akquise_seite_zeigt_den_letzten_schritt(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Rueckmeldung Anzeige GmbH", "info@rm-anzeige.example")
    html = admin.get("/admin/crm/akquise").text
    assert "Erstmail verschickt" not in html.split("Rueckmeldung Anzeige GmbH", 1)[1][:1500]
    admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
               json={"kunde_id": k.id, "betreff": "Hallo"})
    html = admin.get("/admin/crm/akquise").text
    assert "Erstmail verschickt" in html.split("Rueckmeldung Anzeige GmbH", 1)[1][:1500]


# ── Event angelegt: aus dem Lead wird ein Kunde ─────────────────────────────

def _ev():
    return SimpleNamespace(kunde_adresse=None, kunde_id=None)


def test_event_macht_akquise_kontakt_zum_kunden(db):
    """Firmenname im Event anders geschrieben, die Domain stimmt."""
    k = _kontakt(db, "Stadtverwaltung Rueckmeldestadt", "familie@rueckmeldestadt.example",
                 "angebot")
    ev = _ev()
    link_kunde(db, ev, "Stadt Rueckmeldestadt", "Frau Muster", "",
               "m.muster@rueckmeldestadt.example", "Kindsalabim")
    db.commit()
    db.expire_all()
    k = db.query(Kunde).filter(Kunde.id == k.id).first()
    assert ev.kunde_id == k.id
    assert (k.herkunft, k.pipeline_status) == ("bestand", "gebucht")
    assert db.query(Kunde).filter(Kunde.firma == "Stadt Rueckmeldestadt").count() == 0


def test_freemail_adresse_verknuepft_keine_fremde_akquise_firma(db):
    k = _kontakt(db, "Freemail Akquise GmbH", "chef.akquise@gmail.com")
    ev = _ev()
    link_kunde(db, ev, "Ganz Andere Privatfeier", "", "", "jemand@gmail.com", "Kindsalabim")
    db.commit()
    db.expire_all()
    assert ev.kunde_id != k.id
    k = db.query(Kunde).filter(Kunde.id == k.id).first()
    assert (k.herkunft, k.pipeline_status) == ("akquise", "lead")


def test_event_mit_gleichem_firmennamen_bucht_den_akquise_kontakt(db):
    k = _kontakt(db, "Namensgleich Rueckmeldung AG", "info@namensgleich.example", "bedarf")
    ev = _ev()
    link_kunde(db, ev, "namensgleich rueckmeldung ag", "", "", "", "Kindsalabim")
    db.commit()
    db.expire_all()
    k = db.query(Kunde).filter(Kunde.id == k.id).first()
    assert (k.herkunft, k.pipeline_status) == ("bestand", "gebucht")


# ── Recherche: Mitgliedschaft ist der Anlass ────────────────────────────────

def test_netzwerk_haekchen_setzt_marker_und_regel(admin, db, monkeypatch):
    gestartet = []
    monkeypatch.setattr(recherche, "auftrag_ausfuehren", lambda aid: gestartet.append(aid))

    def _kein_netz(*a, **kw):
        raise AssertionError("Im Test darf keine echte Anfrage rausgehen")
    monkeypatch.setattr(httpx, "post", _kein_netz)

    admin.post("/admin/crm/akquise/recherche", follow_redirects=False,
               data={"auftrag": "Allbau GmbH Essen, Sparkasse Essen", "netzwerk": "1"})
    from models import Rechercheauftrag
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == gestartet[-1]).first()
    assert a.auftrag.startswith(recherche.NETZWERK_MARKER)
    text = recherche.nachricht_fuer(a.auftrag)
    assert not text.startswith("[")
    assert "Mitglied im Netzwerk Erfolgsfaktor Familie" in text
    flach = " ".join(text.split())
    assert "kein eigenes Familienfest belegen" in flach
    assert "audit berufundfamilie" in flach          # Zusatzbelege in den Anlass
    assert "Keine Pressestelle" in flach
    assert "bewerbung@" in flach                     # Bewerbungspostfach ist tabu
    assert "nicht der Monat des Festes" in flach     # Ansprachemonat = Planungszeit


def test_ohne_haekchen_bleibt_der_auftrag_unveraendert():
    assert recherche.nachricht_fuer("Wohnungsgesellschaften im Ruhrgebiet") == \
        "Wohnungsgesellschaften im Ruhrgebiet"


def test_nachmeldung_mit_altem_datum_verbraucht_kein_heutiges_limit(admin, db, monkeypatch):
    """Mails, deren Meldung damals nicht ankam, werden nachgemeldet. Das darf das
    Tageslimit von heute nicht aufbrauchen."""
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Nachmeldung GmbH", "info@nachmeldung.example")
    vorher = vertrieb.heute_verschickt(db)
    r = admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
                   json={"kunde_id": str(k.id), "betreff": "Hallo",
                         "gesendet_am": "2026-10-06T08:24:00"})
    assert r.status_code == 200
    assert _status(db, k.id) == "kontakt"
    assert vertrieb.heute_verschickt(db) == vorher
    e = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == k.id).one()
    assert e.erstellt_am == "2026-10-06T08:24:00"


def test_zeitpunkt_in_der_zukunft_zaehlt_als_jetzt(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Zukunft GmbH", "info@zukunft.example")
    admin.post("/admin/crm/api/vertrieb/gesendet", headers=GEHEIM,
               json={"kunde_id": k.id, "gesendet_am": "2099-01-01T00:00:00"})
    e = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == k.id).one()
    assert not e.erstellt_am.startswith("2099")


# ── Postgres: keine Text-ID gegen die Zahlenspalte ──────────────────────────
# SQLite vergleicht 123 und "123" klaglos, Postgres bricht mit HTTP 500 ab
# („operator does not exist: integer = character varying"). So scheiterten bis
# 08.10.2026 alle Versandmeldungen des Assistenten, ohne dass ein Test es sah.
# Deshalb wird hier jede Abfrage so übersetzt, wie Postgres sie bekäme.

def _postgres_sql(db, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.dialects.postgresql import psycopg
    import database
    gesehen = []

    def _merken(ctx):
        gesehen.append(str(ctx.statement.compile(dialect=psycopg.dialect())))
    event.listen(database.SessionLocal, "do_orm_execute", _merken)
    return gesehen, lambda: event.remove(database.SessionLocal, "do_orm_execute", _merken)


def test_meldungen_vergleichen_die_id_als_zahl(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = _kontakt(db, "Postgres Typ GmbH", "info@pg-typ.example")
    gesehen, aufraeumen = _postgres_sql(db, monkeypatch)
    try:
        for pfad in ("gesendet", "antwort", "angebot", "sperren"):
            r = admin.post(f"/admin/crm/api/vertrieb/{pfad}", headers=GEHEIM,
                           json={"kunde_id": str(k.id), "betreff": "x", "grund": "eigene"})
            assert r.status_code == 200, pfad
    finally:
        aufraeumen()
    ids = [q for q in gesehen if "kunden.id =" in q]
    assert ids, "Die Abfrage nach der Kunden-ID wurde nicht gesehen"
    for q in ids:
        assert "kunden.id = %(id_1)s::VARCHAR" not in q, q


# ── Anlass und Ansprachemonat bearbeiten (Aykut 10.10.2026) ─────────────────
# Die Vertriebs-Session empfahl, den Anlass zu korrigieren, das Formular hatte
# dafür aber kein Feld.

def test_anlass_und_monat_im_formular_bearbeitbar(admin, db):
    k = _kontakt(db, "Anlass Bearbeiten GmbH", "info@anlass-edit.example")
    k.anlass = "Mitglied im Netzwerk Erfolgsfaktor Familie"
    db.commit()
    h = admin.get(f"/admin/crm/{k.id}/edit").text
    assert 'name="anlass"' in h and 'name="ansprachemonat"' in h
    r = admin.post(f"/admin/crm/{k.id}/edit", follow_redirects=False, data={
        "firma": "Anlass Bearbeiten GmbH", "email": "info@anlass-edit.example",
        "pipeline_status": "lead", "anlass": "Eigenes Sommerfest für Beschäftigte",
        "ansprachemonat": "2"})
    assert r.status_code == 303
    db.expire_all()
    k = db.query(Kunde).filter(Kunde.id == k.id).first()
    assert k.anlass == "Eigenes Sommerfest für Beschäftigte"
    assert k.ansprachemonat == 2


def test_bestandskunde_ohne_akquisefelder_behaelt_den_anlass(admin, db):
    """Das Formular eines Bestandskunden hat die Felder nicht. Speichern darf einen
    vorhandenen Anlass (z. B. aus einer früheren Akquise) nicht löschen."""
    k = Kunde(firma="Bestand Anlass AG", herkunft="bestand", pipeline_status="gebucht",
              anlass="Alter Anlass", ansprachemonat=5)
    db.add(k); db.commit()
    h = admin.get(f"/admin/crm/{k.id}/edit").text
    assert 'name="anlass"' not in h
    admin.post(f"/admin/crm/{k.id}/edit", follow_redirects=False,
               data={"firma": "Bestand Anlass AG", "pipeline_status": "gebucht"})
    db.expire_all()
    k = db.query(Kunde).filter(Kunde.id == k.id).first()
    assert (k.anlass, k.ansprachemonat) == ("Alter Anlass", 5)
