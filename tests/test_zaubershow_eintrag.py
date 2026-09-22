"""Zaubershow in gemischten Events: eigener (Z)-Kalendereintrag.

Vorfall 22.09.2026 (Feuerwehr Bochum): Zaubershow + weitere Aktionen → Kalender
zeigte nur (div.). Am Telefon sah der Tag frei aus, obwohl Aykut zaubert.
Kalender ist in allen Tests gemockt.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import calendar_service
from database import SessionLocal
from factories import make_event, reload
from models import Event

TAG = date.today() + timedelta(days=60)


class _Kalender:
    """Merkt sich alle Aufrufe statt an Google zu schreiben."""
    def __init__(self):
        self.aufrufe, self._n = [], 0

    def events(self):
        return self

    def insert(self, calendarId, body):
        self._n += 1
        self.aufrufe.append(("insert", body["summary"], body["start"]))
        self._antwort = {"id": f"neu-{self._n}"}
        return self

    def update(self, calendarId, eventId, body):
        self.aufrufe.append(("update", eventId, body["summary"]))
        self._antwort = {}
        return self

    def delete(self, calendarId, eventId):
        self.aufrufe.append(("delete", eventId))
        self._antwort = {}
        return self

    def execute(self):
        return self._antwort


def _kalender_an(monkeypatch):
    k = _Kalender()
    monkeypatch.setattr(calendar_service, "_service", lambda: k)
    monkeypatch.setattr(calendar_service, "get_config",
                        lambda: {"google_calendar_credentials": "{}",
                                 "calendar_id_kindsalabim": "k@x.de",
                                 "calendar_id_knallfrosch": "f@x.de"})
    return k


def _ev(produkte, **kw):
    basis = dict(produkte=produkte, produkte_freitext="", veranstaltungsort="44791 Bochum",
                 anlass="Tag der offenen Tür", kunde_kontakt="", kunde_firma="Feuerwehr Bochum",
                 status="Gebucht", marke="Kindsalabim", datum=TAG, startzeit="11:00",
                 endzeit="17:00", show_startzeit=None, show_endzeit=None,
                 kalender_event_id=None, show_kalender_event_id=None, id=1,
                 kunde_telefon="", anzahl_teamer=0, anzahl_kuenstler=0, hinweise="")
    basis.update(kw)
    return SimpleNamespace(**basis)


def test_eigener_eintrag_nur_bei_gemischten_events():
    ja = calendar_service.zaubershow_eigener_eintrag
    assert ja(_ev("Zaubershow, Hüpfburg"))
    assert ja(_ev("Zaubershow, Kinderschminken"))
    assert not ja(_ev("Zaubershow"))                      # Titel ist schon (Z)
    assert not ja(_ev("Zaubershow, Ballonmodellage"))     # (ZB)
    assert not ja(_ev("Zaubershow, Bastelworkshop"))      # (WORKSHOP+Z)
    assert not ja(_ev("Hüpfburg, Kinderschminken"))       # keine Show


def test_zwei_eintraege_div_und_z(monkeypatch):
    k = _kalender_an(monkeypatch)
    ev = _ev("Zaubershow, Hüpfburg", show_startzeit="14:00", show_endzeit="14:45")
    assert calendar_service.sync_event(ev) is None
    titel = [a[1] for a in k.aufrufe if a[0] == "insert"]
    assert titel[0].startswith("(div.) Bochum")
    assert titel[1].startswith("(Z) Bochum")
    show = [a for a in k.aufrufe if a[0] == "insert"][1]
    assert show[2]["dateTime"].endswith("T14:00:00")
    assert ev.kalender_event_id and ev.show_kalender_event_id


def test_show_ohne_ende_dauert_eine_stunde():
    body = calendar_service._show_body(_ev("Zaubershow, Hüpfburg", show_startzeit="15:30"))
    assert body["end"]["dateTime"].endswith("T16:30:00")


def test_show_eintrag_verschwindet_wenn_nicht_mehr_noetig(monkeypatch):
    k = _kalender_an(monkeypatch)
    ev = _ev("Zaubershow", show_startzeit="14:00", kalender_event_id="haupt",
             show_kalender_event_id="show-alt")
    calendar_service.sync_event(ev)
    assert ("delete", "show-alt") in k.aufrufe
    assert ev.show_kalender_event_id is None


def test_abgesagt_markiert_auch_die_show(monkeypatch):
    k = _kalender_an(monkeypatch)
    ev = _ev("Zaubershow, Hüpfburg", show_startzeit="14:00", status="Abgesagt",
             kalender_event_id="haupt", show_kalender_event_id="show")
    calendar_service.sync_event(ev)
    assert ("update", "show", calendar_service._title(ev, "Z")) in k.aufrufe
    assert calendar_service._title(ev, "Z").startswith("ABGESAGT – (Z)")


def test_formular_speichert_show_zeit_und_warnt_ohne(admin, monkeypatch):
    monkeypatch.setattr(calendar_service, "sync_event_async", lambda eid: None)
    eid = make_event(datum=TAG, kunde_firma="Feuerwehr Bochum Test",
                     produkte="Zaubershow, Hüpfburg")
    html = admin.get(f"/admin/events/{eid}").text
    assert "Uhrzeit der Zaubershow fehlt" in html
    form = admin.get(f"/admin/events/{eid}/edit").text
    assert 'id="show-zeit"' in form and 'name="show_startzeit"' in form

    ev = reload(Event, eid)
    daten = {"anlass": ev.anlass, "datum": TAG.isoformat(), "startzeit": "11:00",
             "endzeit": "17:00", "kunde_adresse": ev.veranstaltungsort,
             "kunde_firma": ev.kunde_firma, "kunde_telefon": "0234 123",
             "produkte": ["Zaubershow", "Hüpfburg"], "status": ev.status, "marke": ev.marke,
             "show_startzeit": "14:00", "show_endzeit": "14:45"}
    r = admin.post(f"/admin/events/{eid}/edit", data=daten, follow_redirects=False)
    assert r.status_code == 303
    ev = reload(Event, eid)
    assert (ev.show_startzeit, ev.show_endzeit) == ("14:00", "14:45")
    html = admin.get(f"/admin/events/{eid}").text
    assert "Uhrzeit der Zaubershow fehlt" not in html
    assert "14:00–14:45 Uhr" in html


def test_formular_lehnt_show_ende_vor_beginn_ab(admin, monkeypatch):
    monkeypatch.setattr(calendar_service, "sync_event_async", lambda eid: None)
    eid = make_event(datum=TAG, produkte="Zaubershow, Hüpfburg")
    ev = reload(Event, eid)
    daten = {"anlass": ev.anlass, "datum": TAG.isoformat(), "startzeit": "11:00",
             "endzeit": "17:00", "kunde_adresse": ev.veranstaltungsort,
             "kunde_firma": ev.kunde_firma, "kunde_telefon": "0234 123",
             "produkte": ["Zaubershow", "Hüpfburg"], "status": ev.status, "marke": ev.marke,
             "show_startzeit": "15:00", "show_endzeit": "14:00"}
    r = admin.post(f"/admin/events/{eid}/edit", data=daten)
    assert "Ende nach dem Beginn" in r.text
    assert reload(Event, eid).show_startzeit is None


def test_nachtragen_findet_fehlenden_show_eintrag(monkeypatch):
    k = _kalender_an(monkeypatch)
    eid = make_event(datum=TAG, produkte="Zaubershow, Hüpfburg",
                     kunde_firma="Nachtrag Show GmbH")
    s = SessionLocal()
    try:
        ev = s.get(Event, eid)
        ev.kalender_event_id, ev.show_startzeit = "haupt-da", "14:00"
        s.commit()
        events, _ = calendar_service.fehlende_eintraege(s)
        assert eid in [e.id for e in events]
        monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
        calendar_service.fehlende_nachtragen(s)
    finally:
        s.close()
    assert reload(Event, eid).show_kalender_event_id
    assert any(a[0] == "insert" and a[1].startswith("(Z)") for a in k.aufrufe)
