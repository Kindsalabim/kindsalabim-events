"""Auto-Nachbesetzung (Vorschlag mit 1-Klick) + Absage-Dringlichkeit.

Teil 1: Lücken-Vorschlag im Event-Detail (Admin).
Teil 2: nachträgliche Absage – < 48 h gesperrt (Telefon-Hinweis), < 7 Tage Mail erzwungen.
"""
from datetime import date, timedelta

from models import Verfuegbarkeitsanfrage, Benachrichtigung
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login
from database import SessionLocal
from notifications import set_mail_enabled

BALD = date.today() + timedelta(days=20)
GESTERN = date.today() - timedelta(days=1)


def _set_mail(typ, on):
    s = SessionLocal()
    try:
        set_mail_enabled(s, typ, on)
        s.commit()
    finally:
        s.close()


def _letzte_glocke_text(typ):
    s = SessionLocal()
    try:
        b = (s.query(Benachrichtigung).filter(Benachrichtigung.typ == typ)
             .order_by(Benachrichtigung.id.desc()).first())
        return b.text if b else ""
    finally:
        s.close()


# ── Teil 1: Auto-Nachbesetzung – Vorschlag mit 1-Klick ────────────────────────

def test_vorschlag_box_bei_luecke(admin):
    eid = make_event(datum=BALD, anzahl_teamer=2)
    bestaetigt = make_dienstleister(vorname="Bestaetigt")
    make_anfrage(eid, bestaetigt, status="Ja", rolle="Teamer")
    make_dienstleister(vorname="Ersatzina")  # frei, noch nicht angefragt
    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "Team noch nicht komplett" in r.text
    assert "Vorschlag Teamer" in r.text          # Kasten + konkreter 1-Klick-Vorschlag
    assert "anfragen</button>" in r.text          # der ✓-anfragen-Button ist da


def test_keine_box_wenn_team_komplett(admin):
    eid = make_event(datum=BALD, anzahl_teamer=1)
    did = make_dienstleister()
    make_anfrage(eid, did, status="Ja", rolle="Teamer")
    r = admin.get(f"/admin/events/{eid}")
    assert "Team noch nicht komplett" not in r.text


def test_keine_box_bei_zaubershow(admin):
    eid = make_event(datum=BALD, anzahl_teamer=2, zaubershow_event=True)
    make_dienstleister(vorname="Frei")
    r = admin.get(f"/admin/events/{eid}")
    assert "Team noch nicht komplett" not in r.text


def test_einklick_anfrage_legt_ausstehende_anfrage_an(admin):
    eid = make_event(datum=BALD, anzahl_teamer=2)
    did = make_dienstleister(vorname="Ersatz")
    r = admin.post(f"/admin/events/{eid}/anfragen",
                   data={"dienstleister_ids": [str(did)], "rolle": "Teamer"},
                   follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    a = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=eid, dienstleister_id=did).first()
    assert a is not None and a.status == "Ausstehend"
    s.close()


# ── Teil 2: Absage-Dringlichkeit ──────────────────────────────────────────────

def test_absage_unter_48h_gesperrt(client, mails):
    eid = make_event(datum=date.today(), startzeit="12:00")  # < 48 h entfernt
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    portal_login(client, did)
    r = client.post(f"/portal/absage/{aid}", data={"grund": "krank"}, follow_redirects=False)
    assert r.status_code == 303
    assert "absage_gesperrt" in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"   # unverändert
    assert len(mails) == 0                                      # keine Mail


def test_absage_unter_7_tage_erzwingt_mail_trotz_schalter_aus(client, mails):
    _set_mail("dl_absage", False)                  # Büro-Mail eigentlich AUS
    eid = make_event(datum=date.today() + timedelta(days=3), startzeit="12:00")
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    portal_login(client, did)
    r = client.post(f"/portal/absage/{aid}", data={"grund": "krank"}, follow_redirects=False)
    assert r.status_code == 303
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Nein"
    assert len(mails) == 1                          # trotzdem verschickt (dringend)
    _set_mail("dl_absage", True)                    # Default wiederherstellen


def test_absage_ueber_7_tage_respektiert_schalter_aus(client, mails):
    _set_mail("dl_absage", False)
    eid = make_event(datum=date.today() + timedelta(days=14), startzeit="12:00")
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    portal_login(client, did)
    client.post(f"/portal/absage/{aid}", data={"grund": ""}, follow_redirects=False)
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Nein"
    assert len(mails) == 0                          # weit weg + Schalter aus → keine Mail
    _set_mail("dl_absage", True)


def test_dashboard_zeigt_telefon_hinweis_unter_48h(client):
    eid = make_event(datum=date.today(), startzeit="12:00")
    did = make_dienstleister()
    make_anfrage(eid, did, status="Ja")
    portal_login(client, did)
    r = client.get("/portal")
    assert r.status_code == 200
    assert "telefonisch im Büro" in r.text
    assert f"/portal/absage/" not in r.text         # Absage-Formular ausgeblendet


# ── Teil 3: Konkreter Ersatzvorschlag im Glockentext ──────────────────────────

def test_glocke_ablauf_enthaelt_vorschlag():
    eid = make_event(datum=BALD, anzahl_teamer=1)
    asked = make_dienstleister()
    make_anfrage(eid, asked, status="Ausstehend", rolle="Teamer", frist_datum=GESTERN)
    make_dienstleister(rolle="Teamer")              # freier Ersatz vorhanden
    s = SessionLocal()
    from routes.cron import _run_abgelaufene_anfragen
    _run_abgelaufene_anfragen(s)
    s.close()
    assert "Vorschlag" in _letzte_glocke_text("anfrage_abgelaufen")


def test_glocke_absage_auf_anfrage_enthaelt_vorschlag(client):
    eid = make_event(datum=BALD, anzahl_teamer=1)
    asked = make_dienstleister()
    aid = make_anfrage(eid, asked, status="Ausstehend", rolle="Teamer")
    make_dienstleister(rolle="Teamer")
    portal_login(client, asked)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Nein"}, follow_redirects=False)
    assert "Vorschlag" in _letzte_glocke_text("dl_absage")


def test_glocke_nachtraegliche_absage_enthaelt_vorschlag(client):
    eid = make_event(datum=date.today() + timedelta(days=14), startzeit="12:00", anzahl_teamer=1)
    confirmed = make_dienstleister()
    aid = make_anfrage(eid, confirmed, status="Ja", rolle="Teamer")
    make_dienstleister(rolle="Teamer")
    portal_login(client, confirmed)
    client.post(f"/portal/absage/{aid}", data={"grund": ""}, follow_redirects=False)
    assert "Vorschlag" in _letzte_glocke_text("dl_absage")
