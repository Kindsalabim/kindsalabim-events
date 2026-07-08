"""„Rechnung gestellt" gilt für die ganze Serie (eine Buchung = eine Rechnung):
Ein Klick markiert alle Termintage; auto_status schließt danach jeden Tag ab,
sobald DESSEN Bedingungen erfüllt sind (Zaubershow sofort, sonst weiter mit Bericht)."""
import secrets
from datetime import date, timedelta

from models import Event
from factories import make_event, reload


def _serie(n, **kw):
    sid = secrets.token_hex(8)
    return sid, [make_event(serien_id=sid, **kw) for _ in range(n)]


def test_rechnung_propagiert_auf_ganze_serie(admin):
    sid, ids = _serie(3)
    admin.post(f"/admin/events/{ids[0]}/rechnung-gestellt",
               data={"gestellt": "1"}, follow_redirects=False)
    for eid in ids:
        assert reload(Event, eid).rechnung_gestellt is True   # alle drei markiert


def test_zaubershow_serie_schliesst_mit_einem_klick(admin):
    # Reine Zaubershow-Serie: Rechnung reicht zum Abschluss – ein Klick schließt alle Tage
    sid, ids = _serie(4, zaubershow_event=True, status="Gebucht")
    admin.post(f"/admin/events/{ids[0]}/rechnung-gestellt",
               data={"gestellt": "1"}, follow_redirects=False)
    for eid in ids:
        assert reload(Event, eid).status == "Abgeschlossen"


def test_normale_serie_bleibt_offen_ohne_bericht(admin):
    # Kein Zaubershow: Rechnung wird zwar auf alle gesetzt, aber ohne Bericht bleibt offen
    sid, ids = _serie(2, status="Briefing gesendet")
    admin.post(f"/admin/events/{ids[0]}/rechnung-gestellt",
               data={"gestellt": "1"}, follow_redirects=False)
    for eid in ids:
        ev = reload(Event, eid)
        assert ev.rechnung_gestellt is True                   # Rechnung überall markiert
        assert ev.status != "Abgeschlossen"                   # aber ohne Bericht nicht zu


def test_einzelevent_unveraendert(admin):
    eid = make_event(zaubershow_event=True, status="Gebucht")
    admin.post(f"/admin/events/{eid}/rechnung-gestellt",
               data={"gestellt": "1"}, follow_redirects=False)
    assert reload(Event, eid).status == "Abgeschlossen"


def test_zaubershow_haekchen_propagiert_auf_serie(admin):
    # Ein Tag als Zaubershow markieren + „auf alle Tage übernehmen" → alle Tage Zaubershow
    sid, ids = _serie(3, status="Gebucht")
    data = {"anlass": "Zaubershow", "datum": (date.today() + timedelta(days=5)).isoformat(),
            "startzeit": "14:00", "marke": "Kindsalabim", "status": "Gebucht",
            "zaubershow_event": "true", "serie_propagieren": "1"}
    admin.post(f"/admin/events/{ids[0]}/edit", data=data, follow_redirects=False)
    for eid in ids:
        assert reload(Event, eid).zaubershow_event is True

    # Danach: ein Klick „Rechnung gestellt" schließt die ganze Zaubershow-Serie ab
    admin.post(f"/admin/events/{ids[0]}/rechnung-gestellt",
               data={"gestellt": "1"}, follow_redirects=False)
    for eid in ids:
        assert reload(Event, eid).status == "Abgeschlossen"
