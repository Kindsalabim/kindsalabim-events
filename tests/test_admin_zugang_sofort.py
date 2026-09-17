"""Admin-Zugänge wirken sofort (17.09.2026, Vergleich mit dem Anfrage-Assistenten).

Vorher prüfte get_admin_user nur die Signatur des 30-Tage-Tokens: Ein gelöschter
oder deaktivierter Zugang blieb bis zu 30 Tage eingeloggt – ein gelöschter
Büro-Zugang sogar mit Vollzugriff. Ein Passwort-Reset beendete alte Logins nicht.
"""
from datetime import datetime, timedelta

from auth import create_token
from database import SessionLocal
from models import Admin

MAIL = "zugang.sofort@example.de"


def _zugang(aktiv=True, rolle="inhaber", sv=0):
    s = SessionLocal()
    try:
        a = s.query(Admin).filter(Admin.email == MAIL).first()
        if not a:
            a = Admin(email=MAIL, password_hash="x")
            s.add(a)
        a.aktiv, a.rolle, a.sitzung_version = aktiv, rolle, sv
        s.commit()
        return a.id
    finally:
        s.close()


def _loeschen():
    s = SessionLocal()
    try:
        s.query(Admin).filter(Admin.email == MAIL).delete()
        s.commit()
    finally:
        s.close()


def _als(client, **token_extra):
    client.cookies.set("admin_token", create_token(
        {"sub": MAIL, "role": "admin", **token_extra}, expires_minutes=60))
    return client


def test_aktiver_zugang_ohne_sv_bleibt_eingeloggt(client):
    """Tokens von vor dem Deploy (ohne sv) dürfen niemanden rauswerfen."""
    _zugang()
    r = _als(client).get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 200


def test_geloeschter_zugang_fliegt_sofort_raus(client):
    _zugang(rolle="buero")
    _loeschen()
    c = _als(client)
    for url in ("/admin/dashboard", "/admin/buchhaltung"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/login", url


def test_deaktivierter_zugang_fliegt_sofort_raus(client):
    _zugang(aktiv=False)
    r = _als(client).get("/admin/dashboard", follow_redirects=False)
    assert r.headers.get("location") == "/admin/login"


def test_login_seite_ohne_endlosschleife_fuer_geloeschte(client):
    _loeschen()
    r = _als(client).get("/admin/login", follow_redirects=False)
    assert r.status_code == 200


def test_passwort_reset_beendet_alte_sitzungen(client):
    _zugang()
    c = _als(client, sv=0)
    assert c.get("/admin/dashboard", follow_redirects=False).status_code == 200
    s = SessionLocal()
    try:
        a = s.query(Admin).filter(Admin.email == MAIL).first()
        a.reset_token = "reset-sofort-test"
        a.reset_token_expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        s.commit()
    finally:
        s.close()
    r = c.post("/admin/reset/reset-sofort-test", data={"password": "neuesPasswort1"},
               follow_redirects=False)
    assert r.status_code == 303
    assert c.get("/admin/dashboard", follow_redirects=False).headers.get("location") == "/admin/login"
    # neuer Login mit der neuen Version klappt
    assert _als(client, sv=1).get("/admin/dashboard", follow_redirects=False).status_code == 200


def test_unbekannter_zugang_bekommt_keinen_vollzugriff(db):
    from rechte import ist_buero
    assert ist_buero(db, {"sub": "gibt.es.nicht@example.de"})


def test_deaktivieren_und_reaktivieren(admin):
    aid = _zugang()
    r = admin.post(f"/admin/admins/{aid}/aktiv", follow_redirects=False)
    assert "ok=deaktiviert" in r.headers["location"]
    assert "deaktiviert" in admin.get("/admin/admins").text
    r = admin.post(f"/admin/admins/{aid}/aktiv", follow_redirects=False)
    assert "ok=aktiviert" in r.headers["location"]


def test_sich_selbst_deaktivieren_geht_nicht(admin, db):
    ich = db.query(Admin).filter(Admin.email == "a@b.de").first()
    r = admin.post(f"/admin/admins/{ich.id}/aktiv", follow_redirects=False)
    assert "fehler=geschuetzt" in r.headers["location"]
    db.refresh(ich)
    assert ich.aktiv
