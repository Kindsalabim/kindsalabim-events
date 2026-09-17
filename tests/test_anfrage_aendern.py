# -*- coding: utf-8 -*-
"""Anfrage nachträglich ändern: Rolle, Budget, Logistik (17.09.2026).

Anlass: Eine Kinderschminkerin war als Teamerin + Logistikerin angefragt worden,
eingesetzt wird sie als Künstlerin mit Pauschalbudget und ohne Lagerfahrt.
"""
from models import Dienstleister, Event, EventHonorar, Verfuegbarkeitsanfrage
from factories import make_anfrage, make_dienstleister, make_event, reload


def _aendern(admin, eid, aid, **data):
    return admin.post(f"/admin/events/{eid}/anfrage/{aid}/aendern", data=data,
                      follow_redirects=False)


def _an(mails, did):
    email = reload(Dienstleister, did).email
    return [m for m in mails if m[0] == email]


def test_teamerin_wird_kuenstlerin_mit_budget_ohne_logistik(admin, db, mails):
    did = make_dienstleister(vorname="Mara")
    eid = make_event(logistiker_id=did)
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Teamer", als_logistiker=True)
    r = _aendern(admin, eid, aid, rolle="Künstler", budget="180,00", benachrichtigen="true")
    assert r.status_code == 303 and "geaendert=Mara" in r.headers["location"]
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert (a.rolle_anfrage, a.budget, a.als_logistiker) == ("Künstler", 180.0, False)
    assert reload(Event, eid).logistiker_id is None
    [(_, betreff, html)] = _an(mails, did)
    assert "Anfrage angepasst" in betreff
    assert "Künstler" in html and "180,00 € pauschal" in html
    assert "nicht ins Lager" in html


def test_deutsches_tausenderformat(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Künstler", budget=100.0)
    _aendern(admin, eid, aid, rolle="Künstler", budget="1.200,00")
    assert reload(Verfuegbarkeitsanfrage, aid).budget == 1200.0


def test_teamer_hat_kein_budget(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Künstler", budget=150.0)
    _aendern(admin, eid, aid, rolle="Teamer", budget="150")
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.rolle_anfrage == "Teamer" and a.budget is None


def test_ohne_haekchen_keine_mail(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    r = _aendern(admin, eid, aid, rolle="Künstler", budget="90")
    assert _an(mails, did) == []
    assert "informiert" not in r.headers["location"]


def test_nichts_geaendert_nichts_passiert(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Teamer")
    r = _aendern(admin, eid, aid, rolle="Teamer", benachrichtigen="true")
    assert "geaendert" not in r.headers["location"]
    assert _an(mails, did) == []


def test_honorar_schaetzung_wird_neu_berechnet(admin, db, mails):
    did = make_dienstleister(stundensatz_teamer=20.0)
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ja", rolle="Teamer")
    db.add(EventHonorar(event_id=eid, dienstleister_id=did, geschaetzt=999.0))
    db.commit()
    _aendern(admin, eid, aid, rolle="Künstler", budget="200")
    db.expire_all()
    h = db.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                      EventHonorar.dienstleister_id == did).one()
    from honorare import lernfaktor        # geteilte Test-DB: Faktor kann ≠ 1 sein
    assert h.geschaetzt == round(200.0 * lernfaktor(db), 2)


def test_erfasste_rechnung_bleibt_unangetastet(admin, db, mails):
    did = make_dienstleister(stundensatz_teamer=20.0)
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ja", rolle="Teamer")
    db.add(EventHonorar(event_id=eid, dienstleister_id=did, geschaetzt=80.0, tatsaechlich=95.0))
    db.commit()
    try:
        _aendern(admin, eid, aid, rolle="Künstler", budget="200")
        db.expire_all()
        h = db.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                          EventHonorar.dienstleister_id == did).one()
        assert (h.geschaetzt, h.tatsaechlich) == (80.0, 95.0)
    finally:
        # Geteilte Test-DB: Ein Ist-Wert bliebe sonst liegen und verfälscht den
        # Lernfaktor in test_honorare.py (erwartet exakt 1,2).
        db.query(EventHonorar).filter(EventHonorar.event_id == eid).delete()
        db.commit()


def test_bei_zusage_geht_korrigierte_bestellung_raus(admin, db, mails, monkeypatch):
    import bestellung
    aufgerufen = []
    monkeypatch.setattr(bestellung, "bestellung_erzeugen_async", lambda aid: aufgerufen.append(aid))
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ja", rolle="Teamer",
                       bestellung_am="2026-09-10T10:00:00", bestellung_r2_key="alt.pdf")
    _aendern(admin, eid, aid, rolle="Künstler", budget="180", benachrichtigen="true")
    assert aufgerufen == [aid]
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.bestellung_am is None and a.bestellung_r2_key is None
    [(_, _, html)] = _an(mails, did)
    assert "neue Bestellung" in html


def test_offene_anfrage_erzeugt_keine_bestellung(admin, db, mails, monkeypatch):
    import bestellung
    aufgerufen = []
    monkeypatch.setattr(bestellung, "bestellung_erzeugen_async", lambda aid: aufgerufen.append(aid))
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    _aendern(admin, eid, aid, rolle="Künstler", budget="180")
    assert aufgerufen == []


def test_abgesagte_anfrage_nicht_aenderbar(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Nein", rolle="Teamer")
    _aendern(admin, eid, aid, rolle="Künstler", budget="180", benachrichtigen="true")
    assert reload(Verfuegbarkeitsanfrage, aid).rolle_anfrage == "Teamer"
    assert _an(mails, did) == []


def test_fenster_ist_vorausgefuellt(admin, db):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Künstler", budget=180.0,
                       als_logistiker=True)
    html = admin.get(f"/admin/events/{eid}").text
    dialog = html.split(f'id="ae-{aid}"')[1].split("</dialog>")[0]
    assert 'value="Künstler" checked' in dialog
    assert 'value="180,00"' in dialog
    assert 'name="als_logistiker" value="true" checked' in dialog
