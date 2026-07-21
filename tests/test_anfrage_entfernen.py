"""Admin kann einen Dienstleister vom Event entfernen (Anfrage löschen).

Hintergrund (Aykut): Bei einem mehrtägigen Event wurde eine Künstlerin versehentlich
für BEIDE Tage eingetragen („Für beide Tage anfragen" nicht abgewählt). Sie kann aber
nur an einem Tag. Der Admin braucht eine Möglichkeit, sie von einem Tag zu entfernen.
"""
from datetime import date

from factories import make_event, make_dienstleister, make_anfrage, reload
from models import Event, Verfuegbarkeitsanfrage
from database import SessionLocal


def _anfrage_existiert(aid):
    s = SessionLocal()
    try:
        return s.get(Verfuegbarkeitsanfrage, aid) is not None
    finally:
        s.close()


def test_entfernen_loescht_anfrage(admin):
    eid = make_event()
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    r = admin.post(f"/admin/events/{eid}/anfrage/{aid}/entfernen", follow_redirects=False)
    assert r.status_code == 303
    assert not _anfrage_existiert(aid)


def test_entfernen_nur_dieser_tag_bei_serie(admin):
    # Zwei Serientage, Künstlerin auf beiden – nur Tag 1 entfernen, Tag 2 bleibt.
    tag1 = make_event(anlass="Sparkasse", datum=date(2026, 9, 12), serien_id="serie-x")
    tag2 = make_event(anlass="Sparkasse", datum=date(2026, 9, 13), serien_id="serie-x")
    did = make_dienstleister()
    a1 = make_anfrage(tag1, did, status="Ja", rolle="Künstler")
    a2 = make_anfrage(tag2, did, status="Ja", rolle="Künstler")
    admin.post(f"/admin/events/{tag1}/anfrage/{a1}/entfernen", follow_redirects=False)
    assert not _anfrage_existiert(a1)      # Tag 1 weg
    assert _anfrage_existiert(a2)          # Tag 2 bleibt


def test_entfernen_loest_teamleiter_und_logistiker(admin):
    did = make_dienstleister()
    eid = make_event(teamleiter_id=did, logistiker_id=did)
    aid = make_anfrage(eid, did, status="Ja")
    admin.post(f"/admin/events/{eid}/anfrage/{aid}/entfernen", follow_redirects=False)
    ev = reload(Event, eid)
    assert ev.teamleiter_id is None
    assert ev.logistiker_id is None


def test_entfernen_falsche_event_zuordnung_404(admin):
    # Anfrage-ID gehört zu einem anderen Event → kein Löschen über die falsche URL
    eid_a = make_event()
    eid_b = make_event()
    did = make_dienstleister()
    aid = make_anfrage(eid_a, did, status="Ja")
    r = admin.post(f"/admin/events/{eid_b}/anfrage/{aid}/entfernen", follow_redirects=False)
    assert r.status_code == 404
    assert _anfrage_existiert(aid)         # unangetastet


def test_entfernen_button_im_detail(admin):
    eid = make_event()
    did = make_dienstleister()
    aid = make_anfrage(eid, did, status="Ja")
    h = admin.get(f"/admin/events/{eid}").text
    assert f"/admin/events/{eid}/anfrage/{aid}/entfernen" in h
