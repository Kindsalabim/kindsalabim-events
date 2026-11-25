"""Anmelde-Link fürs Portal (Lara Lenuweit, 25.11.2026): zwei Anfrage-Mails kurz
nacheinander → der Link aus der ersten Mail muss weiter gehen; derselbe Link muss auf
Handy UND Laptop klappen. Gültig bleibt er bis zum Ablauf (36 h ab der letzten Mail)."""
from datetime import datetime, timedelta

from database import SessionLocal
from auth import create_magic_token
from factories import make_dienstleister, reload
from models import Dienstleister


def _token(did):
    s = SessionLocal()
    try:
        return create_magic_token(s.get(Dienstleister, did), s)
    finally:
        s.close()


def _klick(client, token):
    r = client.get(f"/portal/auth/{token}", follow_redirects=False)
    client.cookies.clear()
    return r.headers["location"]


def test_zweite_mail_entwertet_ersten_link_nicht(client):
    did = make_dienstleister()
    t1 = _token(did)
    t2 = _token(did)
    assert t1 == t2
    assert "error" not in _klick(client, t1)


def test_link_klappt_mehrfach(client):
    did = make_dienstleister()
    t = _token(did)
    assert "error" not in _klick(client, t)     # Laptop
    assert "error" not in _klick(client, t)     # Handy


def test_abgelaufener_link_wird_ersetzt(client):
    did = make_dienstleister()
    alt = _token(did)
    s = SessionLocal()
    d = s.get(Dienstleister, did)
    d.magic_token_expires = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    s.commit(); s.close()
    assert "error" in _klick(client, alt)
    neu = _token(did)
    assert neu != alt
    assert "error" not in _klick(client, neu)


def test_neue_mail_verlaengert_gueltigkeit():
    did = make_dienstleister()
    _token(did)
    s = SessionLocal()
    d = s.get(Dienstleister, did)
    d.magic_token_expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    s.commit(); s.close()
    _token(did)
    rest = datetime.fromisoformat(reload(Dienstleister, did).magic_token_expires) - datetime.utcnow()
    assert rest > timedelta(hours=35)
