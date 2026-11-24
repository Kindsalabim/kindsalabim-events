"""Serie „nur komplett vergeben“ (Aykut 24.11.2026): ein Schalter an der Serie; neue
Anfragen über alle Tage bekommen eine gemeinsame Gruppe, die Person sagt im Portal
einmal für alle Tage zu oder ab. Gilt nur für Anfragen ab dem Einschalten."""
from datetime import date, timedelta

from database import SessionLocal
from models import Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login
from models import Event

TAG = date.today() + timedelta(days=30)


def _serie(sid, n=3, **kw):
    return [make_event(datum=TAG + timedelta(days=i), serien_id=sid, anzahl_teamer=1, **kw)
            for i in range(n)]


def _dl():
    return make_dienstleister(gewerbeschein_vorliegt=True, dsgvo_unterzeichnet=True)


def _anfragen(did, ids):
    s = SessionLocal()
    try:
        return [s.query(Verfuegbarkeitsanfrage).filter_by(event_id=e, dienstleister_id=did).first()
                for e in ids]
    finally:
        s.close()


def test_schalter_gilt_fuer_alle_termine(admin):
    ids = _serie("sk-schalter")
    admin.post(f"/admin/events/{ids[1]}/serie-komplett", data={"wert": "1"})
    assert all(reload(Event, e).serie_komplett for e in ids)
    admin.post(f"/admin/events/{ids[1]}/serie-komplett", data={})
    assert not any(reload(Event, e).serie_komplett for e in ids)


def test_anfrage_alle_tage_bildet_gruppe_und_mail_sagt_zusammen(admin, mails):
    ids = _serie("sk-gruppe")
    admin.post(f"/admin/events/{ids[0]}/serie-komplett", data={"wert": "1"})
    did = _dl()
    admin.post(f"/admin/events/{ids[0]}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Teamer", "serie": "1"})
    gr = {a.komplett_gruppe for a in _anfragen(did, ids)}
    assert len(gr) == 1 and None not in gr
    assert "alle 3 Tage" in mails[-1][2]


def test_ohne_schalter_keine_gruppe(admin, mails):
    ids = _serie("sk-ohne")
    did = _dl()
    admin.post(f"/admin/events/{ids[0]}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Teamer", "serie": "1"})
    assert all(a.komplett_gruppe is None for a in _anfragen(did, ids))
    assert "jeden Tag einzeln" in mails[-1][2]


def test_eine_zusage_gilt_fuer_alle_tage(admin):
    ids = _serie("sk-ja")
    did = _dl()
    aids = [make_anfrage(e, did, status="Ausstehend", komplett_gruppe="g-ja") for e in ids]
    portal_login(admin, did)
    html = admin.get("/portal").text
    assert "An allen 3 Tagen dabei" in html
    assert html.count(f"/portal/antwort/") == 1        # eine Karte für die ganze Serie
    admin.post(f"/portal/antwort/{aids[0]}", data={"antwort": "Ja"})
    assert [a.status for a in _anfragen(did, ids)] == ["Ja", "Ja", "Ja"]


def test_eine_absage_gilt_fuer_alle_tage(admin):
    ids = _serie("sk-nein")
    did = _dl()
    aids = [make_anfrage(e, did, status="Ausstehend", komplett_gruppe="g-nein") for e in ids]
    portal_login(admin, did)
    admin.post(f"/portal/antwort/{aids[1]}", data={"antwort": "Nein"})
    assert [a.status for a in _anfragen(did, ids)] == ["Nein", "Nein", "Nein"]


def test_ein_tag_voll_dann_keine_zusage(admin):
    ids = _serie("sk-voll")
    make_anfrage(ids[2], _dl(), status="Ja", rolle="Teamer")   # Tag 3 schon besetzt
    did = _dl()
    aids = [make_anfrage(e, did, status="Ausstehend", komplett_gruppe="g-voll") for e in ids]
    portal_login(admin, did)
    r = admin.post(f"/portal/antwort/{aids[0]}", data={"antwort": "Ja"}, follow_redirects=False)
    assert "besetzt=" in r.headers["location"]
    assert [a.status for a in _anfragen(did, ids)] == ["Ausstehend"] * 3


def test_einzeltage_bleiben_einzeln(admin):
    ids = _serie("sk-einzeln", n=2)
    did = _dl()
    aids = [make_anfrage(e, did, status="Ausstehend") for e in ids]
    portal_login(admin, did)
    admin.post(f"/portal/antwort/{aids[0]}", data={"antwort": "Ja"})
    assert [a.status for a in _anfragen(did, ids)] == ["Ja", "Ausstehend"]
