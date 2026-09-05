# -*- coding: utf-8 -*-
"""Zwei Befunde vom 06.09.2026 (Fall Diakoniewerk Essen):

1. Die Teamleitung lädt Fotos zum Eventbericht hoch – im Admin-Bereich waren sie
   nirgends zu sehen. Die Dateien lagen die ganze Zeit in R2, die Event-Seite
   fragte den Typ `bericht_foto` schlicht nie ab.
2. Ungültige Dateien (falsches Format, zu groß) wurden beim Upload stillschweigend
   verworfen. Die Teamleitung glaubt dann, die Fotos seien angekommen.

Dazu das Sammel-Formular für die Teamer-Stundensätze: ohne hinterlegten Satz
entsteht weder Auto-Bestellung noch Honorar-Schätzung.
"""
import io

from auth import create_token
from models import Admin, Dienstleister, EventDatei
from factories import make_dienstleister, make_event, portal_login

BUERO_MAIL = "buero.stundensatz@example.de"


def _foto_anlegen(db, event_id, filename="fest.jpg"):
    db.add(EventDatei(event_id=event_id, r2_key=f"events/{event_id}/bericht_foto/x.jpg",
                      filename=filename, typ="bericht_foto",
                      uploaded_at="2026-09-06T10:00:00+00:00"))
    db.commit()


# ── 1. Berichtsfotos in der Admin-Ansicht ────────────────────────────────────

def test_event_detail_zeigt_berichtsfotos(admin, db, monkeypatch):
    import routes.admin as admin_routes
    monkeypatch.setattr(admin_routes, "generate_presigned_url",
                        lambda key, expires=3600: f"https://r2.example/{key}")
    eid = make_event(bericht_eingereicht_am="06.09.2026")
    _foto_anlegen(db, eid, "gruppenbild.jpg")

    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "Fotos vom Event" in r.text
    assert "https://r2.example/events/" in r.text


def test_event_detail_sagt_es_wenn_keine_fotos_da_sind(admin, db):
    """Sonst bleibt offen, ob es keine Fotos gibt oder sie nur nicht angezeigt werden."""
    eid = make_event(bericht_eingereicht_am="06.09.2026")
    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "Keine Fotos hochgeladen" in r.text


def test_fotos_erscheinen_auch_vor_dem_abschicken(admin, db, monkeypatch):
    import routes.admin as admin_routes
    monkeypatch.setattr(admin_routes, "generate_presigned_url",
                        lambda key, expires=3600: f"https://r2.example/{key}")
    eid = make_event()                      # Bericht noch nicht eingereicht
    _foto_anlegen(db, eid)
    r = admin.get(f"/admin/events/{eid}")
    assert "Fotos vom Event" in r.text


# ── 2. Upload meldet verworfene Dateien ──────────────────────────────────────

def _upload(client, event_id, dateien):
    return client.post(f"/portal/events/{event_id}/fotos", files=dateien,
                       follow_redirects=False)


def test_upload_meldet_abgelehnte_dateien(client, db, uploads):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    c = portal_login(client, did)
    r = _upload(c, eid, [
        ("file", ("gut.jpg", io.BytesIO(b"x" * 10), "image/jpeg")),
        ("file", ("schlecht.heic", io.BytesIO(b"x" * 10), "image/heic")),
    ])
    assert r.status_code == 303
    assert "abgelehnt=1" in r.headers["location"]
    assert uploads == ["gut.jpg"]          # das gültige Bild ist trotzdem drin


def test_upload_ohne_probleme_meldet_nichts(client, db, uploads):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    c = portal_login(client, did)
    r = _upload(c, eid, [("file", ("gut.jpg", io.BytesIO(b"x" * 10), "image/jpeg"))])
    assert r.status_code == 303
    assert "abgelehnt" not in r.headers["location"]


def test_berichtsseite_erklaert_abgelehnte_dateien(client, db):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    c = portal_login(client, did)
    r = c.get(f"/portal/bericht/{eid}?abgelehnt=2")
    assert r.status_code == 200
    assert "2 Bilder konnten nicht gespeichert werden" in r.text


# ── 3. Stundensätze-Sammelformular ───────────────────────────────────────────

def test_stundensaetze_belegt_leere_felder_mit_regelsatz(admin, db):
    did = make_dienstleister(vorname="Ohne", nachname="Satz")
    r = admin.get("/admin/stundensaetze")
    assert r.status_code == 200
    assert f'name="satz_{did}"' in r.text
    assert 'value="20,00"' in r.text


def test_stundensaetze_zeigt_bestehenden_wert_unveraendert(admin, db):
    did = make_dienstleister(nachname="Bosse", stundensatz_teamer=25.0)
    r = admin.get("/admin/stundensaetze")
    feld = r.text.split(f'name="satz_{did}"')[1].split(">")[0]
    assert 'value="25,00"' in feld


def test_reine_kuenstler_stehen_nicht_in_der_liste(admin, db):
    """Künstler bekommen eine Pauschale je Job, keinen Stundensatz."""
    did = make_dienstleister(rolle="Künstler", nachname="Zauberer")
    r = admin.get("/admin/stundensaetze")
    assert f'name="satz_{did}"' not in r.text


def test_beides_bekommt_einen_teamer_satz(admin, db):
    did = make_dienstleister(rolle="Beides", nachname="Haller")
    r = admin.get("/admin/stundensaetze")
    assert f'name="satz_{did}"' in r.text


def test_speichern_schreibt_die_saetze(admin, db):
    a = make_dienstleister(nachname="AaTeamer")
    b = make_dienstleister(nachname="AbTeamer")
    r = admin.post("/admin/stundensaetze",
                   data={f"satz_{a}": "20,00", f"satz_{b}": "25,00"},
                   follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Dienstleister, a).stundensatz_teamer == 20.0
    assert db.get(Dienstleister, b).stundensatz_teamer == 25.0


def test_leeres_feld_loescht_den_satz(admin, db):
    did = make_dienstleister(stundensatz_teamer=30.0)
    admin.post("/admin/stundensaetze", data={f"satz_{did}": ""}, follow_redirects=False)
    db.expire_all()
    assert db.get(Dienstleister, did).stundensatz_teamer is None


def test_unlesbare_eingabe_behaelt_den_alten_wert(admin, db):
    did = make_dienstleister(stundensatz_teamer=22.0)
    admin.post("/admin/stundensaetze", data={f"satz_{did}": "zwanzig"},
               follow_redirects=False)
    db.expire_all()
    assert db.get(Dienstleister, did).stundensatz_teamer == 22.0


def test_kuenstler_satz_bleibt_unangetastet(admin, db):
    """Das Formular kennt nur den Teamer-Satz – der Künstler-Satz darf nicht leerlaufen."""
    did = make_dienstleister(rolle="Beides", stundensatz_kuenstler=60.0)
    admin.post("/admin/stundensaetze", data={f"satz_{did}": "20"}, follow_redirects=False)
    db.expire_all()
    assert db.get(Dienstleister, did).stundensatz_kuenstler == 60.0


def test_buero_kommt_nicht_an_die_stundensaetze(client, db):
    a = db.query(Admin).filter(Admin.email == BUERO_MAIL).first()
    if not a:
        a = Admin(email=BUERO_MAIL, name="Bürokraft", password_hash="x", aktiv=True)
        db.add(a)
    a.rolle = "buero"
    db.commit()
    client.cookies.set("admin_token",
                       create_token({"sub": BUERO_MAIL, "role": "admin"}, expires_minutes=60))
    assert client.get("/admin/stundensaetze").status_code == 403
    assert client.post("/admin/stundensaetze", data={}).status_code == 403
