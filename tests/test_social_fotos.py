"""Eventfotos als Quick-Post an die Social-Media-App (Aykut, 03.10.2026).

Beide Apps teilen denselben R2-Speicher, es wandert nur der Schlüssel. Freigaben
sind bewusst keine Sperre, sondern eine Rückfrage: Der Kunde wird in der Checkliste
einmal gefragt, die Teamleitung kann im Bericht die Elternzustimmung bestätigen.
Fehlt beides, warnt die App und Aykut entscheidet. Versand ist in allen Tests gemockt.
"""
from datetime import date, datetime, timedelta

import routes.admin as admin_routes
from database import SessionLocal
from factories import make_dienstleister, make_event, reload
from models import Event, EventDatei, Kunde

TAG = date.today() - timedelta(days=3)


def _foto(event_id, name="bild1.jpg"):
    s = SessionLocal()
    try:
        d = EventDatei(event_id=event_id, r2_key=f"berichte/{event_id}/{name}",
                       filename=name, typ="bericht_foto",
                       uploaded_at=datetime.now().isoformat(timespec="seconds"))
        s.add(d); s.commit()
        return d.id
    finally:
        s.close()


def _setze(event_id, **felder):
    s = SessionLocal()
    try:
        ev = s.get(Event, event_id)
        for k, v in felder.items():
            setattr(ev, k, v)
        s.commit()
    finally:
        s.close()


# ── Warnhinweis ──────────────────────────────────────────────────────────────

def test_warnung_wenn_kunde_nicht_gefragt_wurde(db):
    eid = make_event(datum=TAG, kunde_firma="Ohne Freigabe GmbH")
    assert "nicht nach einer Freigabe gefragt" in admin_routes.social_warnung(db, reload(Event, eid))


def test_keine_warnung_bei_freigabe(db):
    eid = make_event(datum=TAG)
    _setze(eid, cl_foto_freigabe="Ja", bericht_eltern_ok="Ja")
    assert admin_routes.social_warnung(db, reload(Event, eid)) == ""


def test_warnung_bei_widerspruch_und_fehlender_elternzustimmung(db):
    eid = make_event(datum=TAG)
    _setze(eid, cl_foto_freigabe="Nein", bericht_eltern_ok="Nein")
    warnung = admin_routes.social_warnung(db, reload(Event, eid))
    assert "widersprochen" in warnung and "Eltern" in warnung


def test_freigabe_aus_dem_kundenprofil_gilt_auch_ohne_checkliste(db):
    """Stammkunden füllen keine Checkliste mehr aus – die Freigabe hängt am Kunden."""
    s = SessionLocal()
    try:
        k = Kunde(firma="Stammkunde ohne Checkliste", foto_freigabe="Ja")
        s.add(k); s.commit(); kid = k.id
    finally:
        s.close()
    eid = make_event(datum=TAG, kunde_id=kid)
    assert admin_routes.social_warnung(db, reload(Event, eid)) == ""


# ── Senden ───────────────────────────────────────────────────────────────────

def test_ausgewaehlte_fotos_werden_gesendet(admin, monkeypatch):
    gesendet = []
    monkeypatch.setattr(admin_routes, "social_quickpost_senden", lambda did: gesendet.append(did))
    eid = make_event(datum=TAG)
    f1, f2 = _foto(eid, "a.jpg"), _foto(eid, "b.jpg")
    r = admin.post(f"/admin/events/{eid}/social-fotos",
                   data={"datei_ids": [str(f1)]}, follow_redirects=False)
    assert r.status_code == 303 and "social=1" in r.headers["location"]
    assert gesendet == [f1] and f2 not in gesendet


def test_ohne_auswahl_passiert_nichts(admin, monkeypatch):
    gesendet = []
    monkeypatch.setattr(admin_routes, "social_quickpost_senden", lambda did: gesendet.append(did))
    eid = make_event(datum=TAG)
    _foto(eid)
    r = admin.post(f"/admin/events/{eid}/social-fotos", data={}, follow_redirects=False)
    assert "social=keine_auswahl" in r.headers["location"]
    assert gesendet == []


def test_quickpost_schickt_schluessel_und_eckdaten(monkeypatch):
    """Es wandert nur der R2-Schlüssel, kein Bild – beide Apps teilen den Speicher."""
    eid = make_event(datum=TAG, kunde_firma="Stadtwerke Musterstadt",
                     veranstaltungsort="Markt 1, 45127 Essen", anlass="Weihnachtsfeier",
                     produkte="Kinderschminken, Ballonmodellage")
    _setze(eid, cl_foto_freigabe="Ja")
    fid = _foto(eid, "fest.jpg")
    gesendet = {}

    class _Antwort:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=0):
        import json
        gesendet["url"] = req.full_url
        gesendet["secret"] = req.headers.get("X-social-secret")
        gesendet["daten"] = json.loads(req.data.decode())
        return _Antwort()

    monkeypatch.setattr(admin_routes, "get_config",
                        lambda: {"social_api_url": "https://social.example",
                                 "social_api_secret": "geheim"})
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    admin_routes.social_quickpost_senden(fid)

    assert gesendet["url"] == "https://social.example/api/quickpost"
    assert gesendet["secret"] == "geheim"
    d = gesendet["daten"]
    assert d["foto"].startswith("r2:berichte/")
    assert d["kunde"] == "Stadtwerke Musterstadt" and d["ort"] == "Essen"
    assert d["anlass"] == "Weihnachtsfeier" and d["kunde_nennen"] is True
    assert d["quelle_id"] == f"event-{eid}-datei-{fid}"
    s = SessionLocal()
    try:
        assert s.get(EventDatei, fid).social_gesendet_am      # nur nach Erfolg gesetzt
    finally:
        s.close()


def test_ohne_konfiguration_wird_nichts_gesendet(monkeypatch):
    eid = make_event(datum=TAG)
    fid = _foto(eid, "ohne-config.jpg")
    monkeypatch.setattr(admin_routes, "get_config", lambda: {})
    admin_routes.social_quickpost_senden(fid)
    s = SessionLocal()
    try:
        assert s.get(EventDatei, fid).social_gesendet_am is None
    finally:
        s.close()


# ── Freigaben erfassen ───────────────────────────────────────────────────────

def test_checkliste_speichert_freigabe_am_event_und_am_kunden(client, db):
    import uuid
    s = SessionLocal()
    try:
        k = Kunde(firma="Checklisten-Kunde")
        s.add(k); s.commit(); kid = k.id
    finally:
        s.close()
    eid = make_event(datum=date.today() + timedelta(days=10), kunde_id=kid)
    token = str(uuid.uuid4())
    _setze(eid, checklist_token=token)
    ev = reload(Event, eid)
    client.post(f"/checklist/{token}", data={
        "ansprechpartner_name": "Fr. Test", "verpflegung": "Ja", "teamkleidung": "Ja",
        "firma_name": ev.kunde_firma, "foto_freigabe": "Ja"})
    assert reload(Event, eid).cl_foto_freigabe == "Ja"
    assert reload(Kunde, kid).foto_freigabe == "Ja"


def test_bericht_speichert_elternzustimmung_optional(client, db):
    did = make_dienstleister()
    eid = make_event(datum=TAG, teamleiter_id=did)
    from factories import portal_login
    portal_login(client, did)
    client.post(f"/portal/bericht/{eid}", data={"kinder": "20–50", "eltern_ok": "Ja"})
    assert reload(Event, eid).bericht_eltern_ok == "Ja"
    # Zweiter Bericht ohne Angabe überschreibt die Antwort nicht
    client.post(f"/portal/bericht/{eid}", data={"kinder": "20–50"})
    assert reload(Event, eid).bericht_eltern_ok == "Ja"
