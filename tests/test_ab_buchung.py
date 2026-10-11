"""Auftragsbestätigung verschickt → Buchung (Aykut 11.10.2026).

Regel: Wo eine AB rausgeht, gehört ein Event in die App. Geschäftskunden haben ihre
Reservierung in der Events-App, die wird bei eindeutigem Treffer automatisch zur
Buchung. Privatkunden mit AB (rund 5 %) haben keine Reservierung hier: Die Glocke
bringt ein vorausgefülltes „Neues Event“, Aykut prüft und speichert. Nichts wird
geraten: Mehrere Treffer → Glocke fragt.
"""
from datetime import date, timedelta
from urllib.parse import unquote

from models import Benachrichtigung, Event, Kunde, Reservierung, Verbindungslog

GEHEIM = {"X-Vertrieb-Secret": "test-geheim"}
TAG = date.today() + timedelta(days=60)


def _mit_secret(monkeypatch):
    import routes.crm as crm
    monkeypatch.setattr(crm, "get_config", lambda: {"assistent_api_secret": "test-geheim"})


def _res(db, firma, email, tag=TAG, serien_id=None, art="ZB"):
    r = Reservierung(datum=tag, kunde_firma=firma, kunde_email=email, startzeit="14:00",
                     endzeit="16:00", art=art, anlass="Sommerfest",
                     veranstaltungsort="Markt 1, 45127 Essen", serien_id=serien_id,
                     frist=tag, erstellt_am="2026-10-11T10:00:00")
    db.add(r); db.commit(); db.refresh(r)
    return r.id


def _ab(admin, **daten):
    daten.setdefault("datum", TAG.isoformat())
    daten.setdefault("ab_nummer", "AB-2026-0042")
    return admin.post("/admin/crm/api/buchung/ab", headers=GEHEIM, json=daten)


def _letzte_glocke(db):
    db.expire_all()
    return (db.query(Benachrichtigung).filter(Benachrichtigung.typ == "ab_verschickt")
            .order_by(Benachrichtigung.id.desc()).first())


def test_reservierung_wird_automatisch_zur_buchung(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    rid = _res(db, "AB Werke GmbH", "event@ab-werke.example")
    r = _ab(admin, empfaenger="event@ab-werke.example", firma="AB Werke GmbH")
    assert r.status_code == 200 and r.json()["ergebnis"] == "umgewandelt"
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.id == rid).first() is None
    ev = db.query(Event).filter(Event.id == r.json()["event_id"]).one()
    assert ev.status == "Gebucht" and ev.kunde_firma == "AB Werke GmbH"
    g = _letzte_glocke(db)
    assert "Gebucht: AB Werke GmbH" in g.titel and "AB-2026-0042" in g.text
    assert g.link == f"/admin/events/{ev.id}/edit"
    # CRM: Kunde verknüpft und auf „Gebucht“
    k = db.query(Kunde).filter(Kunde.id == ev.kunde_id).one()
    assert k.pipeline_status == "gebucht"


def test_akquise_kontakt_wird_beim_umwandeln_zum_kunden(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    k = Kunde(firma="Akquise AB AG", email="info@akquise-ab.example", herkunft="akquise",
              pipeline_status="angebot")
    db.add(k); db.commit()
    _res(db, "Akquise AB AG", "info@akquise-ab.example")
    _ab(admin, empfaenger="info@akquise-ab.example", firma="Akquise AB AG")
    db.expire_all()
    k = db.query(Kunde).filter(Kunde.id == k.id).one()
    assert (k.herkunft, k.pipeline_status) == ("bestand", "gebucht")


def test_firmen_domain_reicht_als_treffer(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    _res(db, "Domain Treffer GmbH", "info@domain-treffer.example")
    r = _ab(admin, empfaenger="m.mueller@domain-treffer.example", firma="Anders geschrieben")
    assert r.json()["ergebnis"] == "umgewandelt"


def test_serie_wird_komplett_gebucht(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    for d in (0, 1, 3):
        _res(db, "Serie AB GmbH", "info@serie-ab.example", tag=TAG + timedelta(days=d),
             serien_id="serie-ab-test")
    r = _ab(admin, empfaenger="info@serie-ab.example")
    assert r.json()["ergebnis"] == "umgewandelt"
    db.expire_all()
    evs = db.query(Event).filter(Event.kunde_firma == "Serie AB GmbH").all()
    assert len(evs) == 3 and len({e.serien_id for e in evs}) == 1 and evs[0].serien_id
    assert db.query(Reservierung).filter(Reservierung.serien_id == "serie-ab-test").count() == 0


def test_mehrere_treffer_werden_nicht_geraten(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    tag = TAG + timedelta(days=20)
    a = _res(db, "Doppel GmbH", "info@doppel.example", tag=tag)
    b = _res(db, "Doppel GmbH", "info@doppel.example", tag=tag)
    r = _ab(admin, datum=tag.isoformat(), empfaenger="info@doppel.example")
    assert r.json()["ergebnis"] == "mehrdeutig"
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.id.in_([a, b])).count() == 2
    assert "mehrere Reservierungen" in _letzte_glocke(db).text


def test_privatkunde_bekommt_vorausgefuelltes_event(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    tag = TAG + timedelta(days=30)
    r = _ab(admin, datum=tag.isoformat(), privat=True, firma="", kontakt="Emine Aslan",
            empfaenger="emine.aslan@gmail.com", telefon="0170 123", startzeit="15:00",
            endzeit="16:00", ort="Rosenweg 3, 45289 Essen", anlass="Kindergeburtstag",
            art="Z")
    assert r.json()["ergebnis"] == "vorlage"
    db.expire_all()
    assert db.query(Event).filter(Event.datum == tag).count() == 0     # nichts angelegt
    g = _letzte_glocke(db)
    assert g.link.startswith("/admin/events/new?vorlage=1")
    h = admin.get(g.link).text
    assert "Vorausgefüllt aus der Auftragsbestätigung" in h
    for wert in ("Emine Aslan", "0170 123", "Rosenweg 3, 45289 Essen", "Kindergeburtstag",
                 tag.isoformat(), "Aus der Auftragsbestätigung AB-2026-0042"):
        assert wert in unquote(h), wert


def test_freemail_verbindet_keine_fremden_privatkunden(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    tag = TAG + timedelta(days=40)
    rid = _res(db, "Familie Fremd", "jemand.anderes@gmail.com", tag=tag)
    r = _ab(admin, datum=tag.isoformat(), privat=True, kontakt="Jake Blade",
            empfaenger="jake.blade@gmail.com")
    assert r.json()["ergebnis"] == "vorlage"
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.id == rid).first() is not None


def test_schon_gebuchtes_event_wird_nicht_verdoppelt(admin, db, monkeypatch):
    from factories import make_event
    _mit_secret(monkeypatch)
    tag = TAG + timedelta(days=50)
    make_event(datum=tag, kunde_firma="Schon Da GmbH", kunde_email="info@schon-da.example")
    vorher = db.query(Benachrichtigung).filter(Benachrichtigung.typ == "ab_verschickt").count()
    r = _ab(admin, datum=tag.isoformat(), empfaenger="info@schon-da.example")
    assert r.json()["ergebnis"] == "schon_gebucht"
    db.expire_all()
    assert db.query(Event).filter(Event.datum == tag).count() == 1
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "ab_verschickt").count() == vorher


def test_fehlerfaelle_und_monitor(admin, db, monkeypatch):
    _mit_secret(monkeypatch)
    assert admin.post("/admin/crm/api/buchung/ab", json={"datum": TAG.isoformat()}
                      ).status_code == 401
    assert _ab(admin, datum="nächsten Samstag").status_code == 422
    db.expire_all()
    letzte = (db.query(Verbindungslog).filter(Verbindungslog.schnittstelle == "assistent.ab")
              .order_by(Verbindungslog.id.desc()).first())
    assert letzte and not letzte.ok and letzte.status_code == 422


def test_knopf_umwandeln_funktioniert_weiter(admin, db):
    rid = _res(db, "Knopf GmbH", "info@knopf.example", tag=TAG + timedelta(days=70))
    r = admin.post(f"/admin/reservierungen/{rid}/umwandeln", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/edit")
    db.expire_all()
    assert db.query(Reservierung).filter(Reservierung.id == rid).first() is None
