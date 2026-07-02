"""Review-Fixes Gruppe 1 (Sicherheits-Quick-Wins):
- H3: Portal-Foto-Delete darf NUR bericht_foto löschen (nie Auftragsbestätigung/Planung)
- H1: Backup-CSV enthält keine Login-Geheimnisse (magic_token etc.)
- H4: HTML-Escaping von Nutzereingaben in Mail-Templates
- M1: Dienstleister-Löschen löst auch Event.logistiker_id
- M10: Same-Origin-Middleware lehnt Origin: null ab
"""
from datetime import date

from database import SessionLocal
from models import Event, EventDatei, Dienstleister
from factories import make_event, make_dienstleister, make_anfrage, reload
from conftest import login_portal


def _add_datei(event_id, typ):
    s = SessionLocal()
    try:
        d = EventDatei(event_id=event_id, r2_key=f"events/{event_id}/{typ}/x.pdf",
                       filename=f"{typ}.pdf", typ=typ, uploaded_at="2026-07-01T10:00:00")
        s.add(d); s.commit()
        return d.id
    finally:
        s.close()


# ── H3: Portal-Foto-Delete Typ-Sperre ────────────────────────────────────────────

def test_teamleiter_kann_auftragsbestaetigung_nicht_loeschen(client):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    ab_id = _add_datei(eid, "auftragsbestaetigung")
    login_portal(client, did)
    r = client.post(f"/portal/events/{eid}/fotos/{ab_id}/delete")
    assert r.status_code == 404                       # abgewiesen …
    assert reload(EventDatei, ab_id) is not None      # … Datei bleibt erhalten


def test_teamleiter_kann_planungsdatei_nicht_loeschen(client):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    pl_id = _add_datei(eid, "planung")
    login_portal(client, did)
    r = client.post(f"/portal/events/{eid}/fotos/{pl_id}/delete")
    assert r.status_code == 404
    assert reload(EventDatei, pl_id) is not None


def test_teamleiter_kann_eigenes_foto_loeschen(client):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    foto_id = _add_datei(eid, "bericht_foto")
    login_portal(client, did)
    r = client.post(f"/portal/events/{eid}/fotos/{foto_id}/delete", follow_redirects=False)
    assert r.status_code == 303                       # Erfolg (Redirect ins Bericht-Formular)
    assert reload(EventDatei, foto_id) is None        # Foto ist weg


# ── H1: Backup-CSV ohne Login-Geheimnisse ────────────────────────────────────────

def test_backup_csv_enthaelt_keine_tokens():
    from routes.cron import _model_to_csv, _CSV_GEHEIM
    s = SessionLocal()
    try:
        kopf_dl = _model_to_csv([], Dienstleister).decode("utf-8-sig").splitlines()[0]
        kopf_ev = _model_to_csv([], Event).decode("utf-8-sig").splitlines()[0]
    finally:
        s.close()
    assert "magic_token" not in kopf_dl
    assert "password_hash" not in kopf_dl
    assert "checklist_token" not in kopf_ev
    # Nicht-geheime Nutzspalten bleiben erhalten
    assert "email" in kopf_dl
    assert "anlass" in kopf_ev


# ── H4: Mail-Escaping ─────────────────────────────────────────────────────────────

def test_info_row_escaped_html():
    from email_service import _info_row
    row = _info_row("Parkplatz", '<script>alert(1)</script>')
    assert "<script>" not in row
    assert "&lt;script&gt;" in row


def test_absage_grund_escaped():
    from email_service import _esc
    # Der Absagegrund des Dienstleisters wird escaped in die Admin-Mail gesetzt.
    assert _esc('<b>x</b>') == "&lt;b&gt;x&lt;/b&gt;"


# ── M1: Logistiker-Verknüpfung beim Löschen ──────────────────────────────────────

def test_dienstleister_loeschen_loest_logistiker(admin):
    did = make_dienstleister()
    eid = make_event()
    s = SessionLocal()
    try:
        ev = s.get(Event, eid); ev.logistiker_id = did; s.commit()
    finally:
        s.close()
    r = admin.post(f"/admin/dienstleister/{did}/delete", follow_redirects=False)
    assert r.status_code == 303                        # kein 500 durch FK-Bruch
    assert reload(Dienstleister, did) is None
    assert reload(Event, eid).logistiker_id is None    # Verknüpfung gelöst


# ── M10: CSRF-Middleware lehnt Origin: null ab ───────────────────────────────────

def test_origin_null_wird_abgelehnt(client):
    r = client.post("/admin/login", data={"email": "x@y.de", "password": "z"},
                    headers={"Origin": "null"})
    assert r.status_code == 403
