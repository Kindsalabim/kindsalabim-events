"""Review-Fixes Gruppe 3 (Robustheit):
- H5: Antwortfrist-Konstante deckt Mailtext UND frist_datum ab (kein Widerspruch mehr)
- M2: nachträglicher Serientag startet frisch als „Gebucht"
- M3: Serien-Anfragen überspringen abgesagte/abgeschlossene Tage
- M4: keine Doppel-Anfragen (UniqueConstraint (event_id, dienstleister_id))
- M13: externe Teamer werden im Event-Snapshot gesichert + wiederhergestellt
- M14: Event-Restore mit zwischenzeitlich gelöschten FKs bricht nicht ab
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Event, Verfuegbarkeitsanfrage, ExternerTeamer, GeloeschtesObjekt
from factories import make_event, make_dienstleister, make_anfrage, reload

HEUTE = date.today()


# ── H5: Frist-Konstante konsistent ────────────────────────────────────────────────

def test_frist_konstante_deckt_mailtext_und_db():
    import email_service
    from routes import admin
    assert email_service.ANFRAGE_FRIST_TAGE == admin.ANFRAGE_FRIST_TAGE == 3
    # Mailtext nennt exakt dieselbe Zahl (kein hartkodiertes „7 Tagen" mehr)
    dl = make_dl_obj()
    ev = reload(Event, make_event())
    html = _render_anfrage(dl, ev)
    assert "innerhalb von 3 Tagen" in html
    assert "7 Tagen" not in html


def make_dl_obj():
    from models import Dienstleister
    return reload(Dienstleister, make_dienstleister(email="x@y.de"))


def _render_anfrage(dl, ev):
    import email_service
    captured = {}
    orig = email_service._deliver
    email_service._deliver = lambda to, subject, html, anhaenge=None: captured.setdefault("html", html)
    try:
        email_service.send_verfuegbarkeitsanfrage(dl, ev, 1, "http://t", magic_url="http://t/m")
    finally:
        email_service._deliver = orig
    return captured.get("html", "")


# ── M4: keine Doppel-Anfragen ─────────────────────────────────────────────────────

def test_doppelte_anfrage_wird_von_db_abgelehnt():
    eid = make_event()
    did = make_dienstleister()
    make_anfrage(eid, did)
    s = SessionLocal()
    try:
        s.add(Verfuegbarkeitsanfrage(event_id=eid, dienstleister_id=did,
                                     rolle_anfrage="Teamer", status="Ausstehend"))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


# ── M3: Serien-Anfragen überspringen gesperrte Tage ───────────────────────────────

def test_serie_anfrage_ueberspringt_abgesagten_tag(admin, mails):
    import secrets
    sid = secrets.token_hex(8)
    tag1 = make_event(datum=HEUTE + timedelta(days=10), serien_id=sid, status="Gebucht")
    tag2 = make_event(datum=HEUTE + timedelta(days=11), serien_id=sid, status="Abgesagt")
    did = make_dienstleister(email="serie@y.de")
    admin.post(f"/admin/events/{tag1}/anfragen",
               data={"dienstleister_ids": [str(did)], "rolle": "Teamer", "serie": "true"},
               headers={"Origin": "http://testserver"}, follow_redirects=False)
    s = SessionLocal()
    try:
        n_tag1 = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=tag1, dienstleister_id=did).count()
        n_tag2 = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=tag2, dienstleister_id=did).count()
    finally:
        s.close()
    assert n_tag1 == 1          # gebuchter Tag: Anfrage angelegt
    assert n_tag2 == 0          # abgesagter Tag: übersprungen


# ── M2: nachträglicher Serientag startet als „Gebucht" ────────────────────────────

def test_serie_tag_add_startet_gebucht(admin):
    base = make_event(datum=HEUTE + timedelta(days=10), status="Briefing gesendet")
    admin.post(f"/admin/events/{base}/serie/add",
               data={"neu_datum": (HEUTE + timedelta(days=12)).strftime("%Y-%m-%d")},
               headers={"Origin": "http://testserver"}, follow_redirects=False)
    s = SessionLocal()
    try:
        ev_base = s.get(Event, base)
        neue = s.query(Event).filter(Event.serien_id == ev_base.serien_id,
                                     Event.id != base).all()
    finally:
        s.close()
    assert len(neue) == 1
    assert neue[0].status == "Gebucht"        # erbt NICHT „Briefing gesendet"


# ── M13/M14: Papierkorb – externe Teamer + tote FK ────────────────────────────────

def test_snapshot_und_restore_mit_externem_teamer_und_toter_fk():
    from papierkorb import archive_event, restore
    # Event mit externem Teamer + Verweis auf einen Dienstleister, der gleich gelöscht wird
    tote_did = make_dienstleister()
    eid = make_event(teamleiter_id=tote_did)
    s = SessionLocal()
    try:
        s.add(ExternerTeamer(event_id=eid, name="Aushilfe Max", telefon="0151"))
        s.commit()
        ev = s.get(Event, eid)
        archive_event(s, ev, "admin@test")
        # Event + Dienstleister hart löschen (teamleiter_id zeigt ins Leere)
        s.query(ExternerTeamer).filter_by(event_id=eid).delete()
        s.query(Event).filter_by(id=eid).delete()
        from models import Dienstleister
        s.query(Dienstleister).filter_by(id=tote_did).delete()
        s.commit()
        eintrag = s.query(GeloeschtesObjekt).filter_by(typ="event", objekt_id=eid).order_by(
            GeloeschtesObjekt.id.desc()).first()
        fehler, neue_id = restore(s, eintrag)
        s.commit()
        assert fehler is None
        neu = s.get(Event, neue_id)
        assert neu.teamleiter_id is None       # tote FK sauber gelöst (kein Absturz)
        ext = s.query(ExternerTeamer).filter_by(event_id=neue_id).all()
        assert len(ext) == 1 and ext[0].name == "Aushilfe Max"   # externer Teamer zurück
    finally:
        s.close()
