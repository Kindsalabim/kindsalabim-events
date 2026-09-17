# -*- coding: utf-8 -*-
"""Anfrage zurückziehen – mit Nachricht an den Dienstleister (17.09.2026).

Anlass: Ein Kunde nahm nach missverständlicher Bestätigung nur das Kinderschminken
an, die zwei Bastel-Teamer waren schon angefragt. Der Mülleimer löschte still –
die Anfrage-Mail blieb im Postfach, niemand erfuhr den Grund. Der Mülleimer bleibt
(stiller Weg), das Zurückziehen ist der Weg mit Nachricht.
"""
from models import Dienstleister, Event, EventHonorar, Verfuegbarkeitsanfrage
from factories import make_anfrage, make_dienstleister, make_event, reload


def _ziehen(admin, eid, aid, **data):
    data.setdefault("grund", "kunde")
    return admin.post(f"/admin/events/{eid}/anfrage/{aid}/zurueckziehen", data=data,
                      follow_redirects=False)


def _an(mails, did):
    email = reload(Dienstleister, did).email
    return [m for m in mails if m[0] == email]


def test_offene_anfrage_wird_entfernt_und_gemeldet(admin, db, mails):
    did = make_dienstleister(vorname="Lisa")
    eid = make_event(anlass="Sommerfest")
    aid = make_anfrage(eid, did, status="Ausstehend")
    r = _ziehen(admin, eid, aid)
    assert r.status_code == 303
    assert "zurueckgezogen=Lisa" in r.headers["location"]
    assert "mailfehler" not in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid) is None
    [(to, betreff, html)] = _an(mails, did)
    assert "nicht mehr aktuell" in betreff
    assert "Der Kunde hat die Buchung geändert." in html
    assert "storniert" not in html


def test_zusage_wird_storniert(admin, db, mails):
    did = make_dienstleister(stundensatz_teamer=20.0)
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ja")
    db.add(EventHonorar(event_id=eid, dienstleister_id=did, geschaetzt=100.0))
    db.commit()
    _ziehen(admin, eid, aid, grund="planung")
    [(to, betreff, html)] = _an(mails, did)
    assert "Einsatz abgesagt" in betreff
    assert "storniert" in html
    assert "Planung ist ein Fehler passiert" in html
    db.expire_all()
    assert db.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                         EventHonorar.dienstleister_id == did).count() == 0


def test_eigener_satz_steht_escaped_in_der_mail(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    _ziehen(admin, eid, aid, zusatz="Beim nächsten Mal <b>gern</b> wieder!")
    [(_, _, html)] = _an(mails, did)
    assert "Beim nächsten Mal &lt;b&gt;gern&lt;/b&gt; wieder!" in html


def test_unbekannter_grund_faellt_auf_kunde_zurueck(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    _ziehen(admin, eid, aid, grund="quatsch")
    [(_, _, html)] = _an(mails, did)
    assert "Der Kunde hat die Buchung geändert." in html


def test_bedarf_senken_teamer(admin, db, mails):
    did = make_dienstleister()
    eid = make_event(anzahl_teamer=2)
    aid = make_anfrage(eid, did, status="Ausstehend")
    _ziehen(admin, eid, aid, bedarf_senken="true")
    assert reload(Event, eid).anzahl_teamer == 1


def test_bedarf_senken_kuenstler_und_nie_unter_null(admin, db, mails):
    did = make_dienstleister(rolle="Künstler")
    eid = make_event(anzahl_kuenstler=0, anzahl_teamer=3)
    aid = make_anfrage(eid, did, status="Ausstehend", rolle="Künstler")
    _ziehen(admin, eid, aid, bedarf_senken="true")
    ev = reload(Event, eid)
    assert ev.anzahl_kuenstler == 0
    assert ev.anzahl_teamer == 3


def test_ohne_haekchen_bleibt_der_bedarf(admin, db, mails):
    did = make_dienstleister()
    eid = make_event(anzahl_teamer=2)
    aid = make_anfrage(eid, did, status="Ausstehend")
    _ziehen(admin, eid, aid)
    assert reload(Event, eid).anzahl_teamer == 2


def test_notiz_an_der_karte_wird_angehaengt(admin, db, mails):
    did = make_dienstleister(notizen="Fährt gern mit.")
    eid = make_event(anlass="Herbstfest")
    aid = make_anfrage(eid, did, status="Ja")
    _ziehen(admin, eid, aid)
    notizen = reload(Dienstleister, did).notizen
    assert notizen.startswith("Fährt gern mit.\n")
    assert "Herbstfest" in notizen and "nach Zusage" in notizen
    assert "Der Kunde hat die Buchung geändert." in notizen


def test_teamleitung_wird_geloest(admin, db, mails):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did)
    aid = make_anfrage(eid, did, status="Ja")
    _ziehen(admin, eid, aid)
    assert reload(Event, eid).teamleiter_id is None


def test_bei_eigener_absage_passiert_nichts(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Nein")
    _ziehen(admin, eid, aid)
    assert reload(Verfuegbarkeitsanfrage, aid) is not None
    assert _an(mails, did) == []


def test_mailfehler_entfernt_trotzdem_und_meldet_es(admin, db, mails, monkeypatch):
    import email_service

    def kaputt(*a, **kw):
        raise RuntimeError("Resend down")
    monkeypatch.setattr(email_service, "_deliver", kaputt)
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    r = _ziehen(admin, eid, aid)
    assert "mailfehler=1" in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid) is None


def test_muelleimer_bleibt_still(admin, db, mails):
    did = make_dienstleister()
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    admin.post(f"/admin/events/{eid}/anfrage/{aid}/entfernen", follow_redirects=False)
    assert reload(Verfuegbarkeitsanfrage, aid) is None
    assert _an(mails, did) == []


def test_knopf_nur_bei_offen_zugesagt_abgelaufen(admin, db):
    eid = make_event()
    ids = {s: make_anfrage(eid, make_dienstleister(), status=s)
           for s in ("Ausstehend", "Ja", "Abgelaufen", "Nein")}
    html = admin.get(f"/admin/events/{eid}").text
    for s in ("Ausstehend", "Ja", "Abgelaufen"):
        assert f'id="zz-{ids[s]}"' in html, s
    assert f'id="zz-{ids["Nein"]}"' not in html


def test_banner_nach_dem_zurueckziehen(admin, db):
    eid = make_event()
    assert "wurde per Mail informiert" in admin.get(
        f"/admin/events/{eid}?zurueckgezogen=Lisa").text
    assert "Die Mail konnte nicht gesendet werden" in admin.get(
        f"/admin/events/{eid}?zurueckgezogen=Lisa&mailfehler=1").text
