"""Büro-/Disposition-Rolle: gesperrte Bereiche, ausgeblendete Konditionen.

Der `admin`-Fixture-Zugang (a@b.de) hat keinen Admin-Datensatz und gilt damit
weiter als Inhaber – bestehende Tests bleiben davon unberührt.
"""
from auth import create_token
from models import Admin, Dienstleister, Event, Kunde
from factories import make_dienstleister, make_event

BUERO_MAIL = "buero.rollentest@example.de"


def _buero(client, db):
    """Legt (einmalig) einen Büro-Zugang an und loggt den Client damit ein."""
    a = db.query(Admin).filter(Admin.email == BUERO_MAIL).first()
    if not a:
        a = Admin(email=BUERO_MAIL, name="Bürokraft", password_hash="x", aktiv=True)
        db.add(a)
    a.rolle = "buero"
    db.commit()
    client.cookies.set("admin_token",
                       create_token({"sub": BUERO_MAIL, "role": "admin"}, expires_minutes=60))
    return client


def _dienstleister(db):
    did = make_dienstleister(stundensatz_teamer=25.0, stundensatz_kuenstler=60.0)
    return db.query(Dienstleister).filter(Dienstleister.id == did).first()


# ── Gesperrte Bereiche ───────────────────────────────────────────────────────

def test_buero_kommt_nicht_in_buchhaltung_papierkorb_zugaenge(client, db):
    c = _buero(client, db)
    for url in ("/admin/buchhaltung", "/admin/papierkorb", "/admin/admins"):
        r = c.get(url)
        assert r.status_code == 403, url
        assert "Kein Zugriff" in r.text


def test_inhaber_kommt_weiter_ueberall_rein(admin):
    for url in ("/admin/buchhaltung", "/admin/papierkorb", "/admin/admins"):
        assert admin.get(url).status_code == 200, url


def test_buero_darf_events_nicht_loeschen(client, db):
    eid = make_event()
    c = _buero(client, db)
    assert c.post(f"/admin/events/{eid}/delete").status_code == 403
    db.expire_all()
    assert db.query(Event).filter(Event.id == eid).first() is not None


def test_buero_darf_dienstleister_und_kunden_nicht_loeschen(client, db):
    d = _dienstleister(db)
    k = Kunde(firma="Rollen-Kunde GmbH")
    db.add(k); db.commit(); db.refresh(k)
    c = _buero(client, db)
    assert c.post(f"/admin/dienstleister/{d.id}/delete").status_code == 403
    assert c.post(f"/admin/crm/{k.id}/delete").status_code == 403
    db.expire_all()
    assert db.query(Dienstleister).filter(Dienstleister.id == d.id).first() is not None
    assert db.query(Kunde).filter(Kunde.id == k.id).first() is not None


# ── Disposition darf weiterarbeiten ──────────────────────────────────────────

def test_buero_darf_dispositions_bereiche_oeffnen(client, db):
    c = _buero(client, db)
    for url in ("/admin/dashboard", "/admin/events/new", "/admin/dienstleister",
                "/admin/reservierungen", "/admin/crm"):
        assert c.get(url).status_code == 200, url


def test_menue_zeigt_gesperrte_bereiche_nicht(client, db):
    c = _buero(client, db)
    seite = c.get("/admin/dashboard").text
    assert "/admin/buchhaltung" not in seite
    assert "/admin/papierkorb" not in seite
    assert "/admin/admins" not in seite


# ── Konditionen ──────────────────────────────────────────────────────────────

def test_stundensaetze_fuer_buero_ausgeblendet(client, db):
    d = _dienstleister(db)
    c = _buero(client, db)
    detail = c.get(f"/admin/dienstleister/{d.id}").text
    assert "Stundensatz Teamer" not in detail
    assert "Status-Scoring" not in detail
    formular = c.get(f"/admin/dienstleister/{d.id}/edit").text
    assert "stundensatz_teamer" not in formular
    assert ">Löschen<" not in formular


def test_inhaber_sieht_stundensaetze(admin, db):
    d = _dienstleister(db)
    detail = admin.get(f"/admin/dienstleister/{d.id}").text
    assert "Stundensatz Teamer" in detail
    assert "stundensatz_teamer" in admin.get(f"/admin/dienstleister/{d.id}/edit").text


def test_speichern_durch_buero_laesst_stundensaetze_stehen(client, db):
    d = _dienstleister(db)
    c = _buero(client, db)
    r = c.post(f"/admin/dienstleister/{d.id}/edit", data={
        "vorname": "Rollen", "nachname": "Test-Neu", "email": d.email,
        "rolle": "Teamer", "mobilitaet": "Auto",
    }, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    d2 = db.query(Dienstleister).filter(Dienstleister.id == d.id).first()
    assert d2.nachname == "Test-Neu"          # Änderung ist angekommen …
    assert d2.stundensatz_teamer == 25.0      # … die Konditionen bleiben unangetastet
    assert d2.stundensatz_kuenstler == 60.0
