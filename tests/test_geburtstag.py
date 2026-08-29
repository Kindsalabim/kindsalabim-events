"""Geburtsdatum im Dienstleister-Profil + Glocke am Geburtstag."""
from datetime import date, timedelta

from database import SessionLocal
from models import Dienstleister, Benachrichtigung
from routes.cron import _run_geburtstage
from validation import parse_geburtsdatum
from factories import make_dienstleister, portal_login


def _setze(did, **felder):
    s = SessionLocal()
    try:
        d = s.query(Dienstleister).filter(Dienstleister.id == did).first()
        for k, v in felder.items():
            setattr(d, k, v)
        s.commit()
    finally:
        s.close()


# ── Validierung ──────────────────────────────────────────────────────────────

def test_geburtsdatum_parsen():
    assert parse_geburtsdatum("") == (True, None)
    assert parse_geburtsdatum("1990-05-17") == (True, date(1990, 5, 17))
    assert parse_geburtsdatum("17.05.1990")[0] is False      # falsches Format
    morgen = (date.today() + timedelta(days=1)).isoformat()
    assert parse_geburtsdatum(morgen)[0] is False            # Zukunft
    assert parse_geburtsdatum("1850-01-01")[0] is False      # unplausibel alt


def test_alter_wird_berechnet(db):
    did = make_dienstleister()
    heute = date.today()
    # Geburtstag heute vor 30 Jahren → exakt 30
    _setze(did, geburtsdatum=heute.replace(year=heute.year - 30))
    db.expire_all()
    assert db.query(Dienstleister).filter(Dienstleister.id == did).first().alter == 30


# ── Glocke ───────────────────────────────────────────────────────────────────

def test_glocke_am_geburtstag_und_nur_einmal(db):
    did = make_dienstleister()
    heute = date.today()
    _setze(did, geburtsdatum=heute.replace(year=heute.year - 25), aktiv=True)
    vorher = db.query(Benachrichtigung).filter(Benachrichtigung.typ == "geburtstag").count()

    assert _run_geburtstage(db) >= 1
    db.expire_all()
    neu = db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "geburtstag").order_by(Benachrichtigung.id.desc()).first()
    assert "Geburtstag heute" in neu.titel
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "geburtstag").count() == vorher + 1

    # Zweiter Cron-Lauf am selben Tag meldet nichts mehr
    assert _run_geburtstage(db) == 0
    db.expire_all()
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "geburtstag").count() == vorher + 1


def test_keine_glocke_an_anderen_tagen(db):
    did = make_dienstleister()
    _setze(did, geburtsdatum=date.today() - timedelta(days=40), aktiv=True,
           geburtstag_erinnert_am=None)
    vorher = db.query(Benachrichtigung).filter(Benachrichtigung.typ == "geburtstag").count()
    _run_geburtstage(db)
    db.expire_all()
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "geburtstag").count() == vorher


def test_inaktive_dienstleister_zaehlen_nicht(db):
    did = make_dienstleister()
    heute = date.today()
    _setze(did, geburtsdatum=heute.replace(year=heute.year - 25), aktiv=False,
           geburtstag_erinnert_am=None)
    vorher = db.query(Benachrichtigung).filter(Benachrichtigung.typ == "geburtstag").count()
    _run_geburtstage(db)
    db.expire_all()
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.typ == "geburtstag").count() == vorher


# ── Formulare ────────────────────────────────────────────────────────────────

def test_portal_speichert_geburtstag(client, db):
    did = make_dienstleister()
    c = portal_login(client, did)
    r = c.post("/portal/profil", data={"geburtsdatum": "1995-03-08", "mobilitaet": "Auto"},
               follow_redirects=False)
    assert r.status_code == 303 and "fehler" not in r.headers["location"]
    db.expire_all()
    assert db.query(Dienstleister).filter(
        Dienstleister.id == did).first().geburtsdatum == date(1995, 3, 8)


def test_portal_profil_zeigt_geburtstagsfeld(client, db):
    did = make_dienstleister()
    _setze(did, geburtsdatum=date(1995, 3, 8))
    seite = portal_login(client, did).get("/portal/profil").text
    assert 'name="geburtsdatum"' in seite
    assert "1995-03-08" in seite


def test_portal_lehnt_zukunft_ab(client, db):
    did = make_dienstleister()
    c = portal_login(client, did)
    morgen = (date.today() + timedelta(days=1)).isoformat()
    r = c.post("/portal/profil", data={"geburtsdatum": morgen, "mobilitaet": "Auto"},
               follow_redirects=False)
    assert "fehler=geburtsdatum" in r.headers["location"]
    db.expire_all()
    assert db.query(Dienstleister).filter(Dienstleister.id == did).first().geburtsdatum is None


def test_admin_formular_zeigt_und_speichert_geburtstag(admin, db):
    did = make_dienstleister()
    d = db.query(Dienstleister).filter(Dienstleister.id == did).first()
    r = admin.post(f"/admin/dienstleister/{did}/edit", data={
        "vorname": d.vorname, "nachname": d.nachname, "email": d.email,
        "rolle": "Teamer", "mobilitaet": "Auto", "geburtsdatum": "1988-12-24",
    }, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.query(Dienstleister).filter(
        Dienstleister.id == did).first().geburtsdatum == date(1988, 12, 24)
    assert "24.12.1988" in admin.get(f"/admin/dienstleister/{did}").text
