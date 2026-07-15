"""Stammkunden: Briefing-Daten vom letzten Event desselben Kunden übernehmen
(Vorbefüllung des Formulars – gespeichert wird erst beim Absenden)."""
from datetime import date

from factories import make_event, reload
from models import Event
from database import SessionLocal


def _mit_briefing(eid, **cl):
    """Briefing-Daten an ein Event hängen (cl_eingereicht_am = „hat Daten")."""
    s = SessionLocal()
    try:
        ev = s.get(Event, eid)
        ev.cl_eingereicht_am = "01.05.2026 10:00"
        for k, v in cl.items():
            setattr(ev, k, v)
        s.commit()
    finally:
        s.close()


def test_button_erscheint_mit_quell_event(admin):
    alt = make_event(kunde_firma="Kita Sonne", anlass="Sommerfest", datum=date(2026, 5, 12))
    _mit_briefing(alt, cl_parkplatz="Hof hinten")
    neu = make_event(kunde_firma="Kita Sonne", anlass="Herbstfest", datum=date(2026, 9, 1))
    h = admin.get(f"/admin/events/{neu}/checklist/edit").text
    assert "Briefing vom letzten Event übernehmen" in h
    assert "Sommerfest" in h and "12.05.2026" in h
    assert f"/admin/events/{neu}/checklist/edit?uebernehmen=1" in h


def test_kein_button_ohne_vorgaenger(admin):
    eid = make_event(kunde_firma="Ganz Neue GmbH", anlass="Erstes Fest")
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert "Briefing vom letzten Event übernehmen" not in h


def test_kein_button_bei_anderem_kunden(admin):
    alt = make_event(kunde_firma="Kunde A", anlass="A-Fest", datum=date(2026, 5, 1))
    _mit_briefing(alt, cl_parkplatz="Hof A")
    neu = make_event(kunde_firma="Kunde B", anlass="B-Fest", datum=date(2026, 6, 1))
    h = admin.get(f"/admin/events/{neu}/checklist/edit").text
    assert "Briefing vom letzten Event übernehmen" not in h


def test_uebernehmen_befuellt_formular(admin):
    alt = make_event(kunde_firma="Kita Mond", anlass="Fest 1", datum=date(2026, 5, 12))
    _mit_briefing(alt, cl_ansprechpartner_name="Frau Klar", cl_ansprechpartner_mobil="0177 9",
                  cl_strasse="Hauptstr. 5", cl_plz_ort="45127 Essen",
                  cl_parkplatz="Hof hinten", cl_weitere_details="Treffpunkt Haupteingang")
    neu = make_event(kunde_firma="Kita Mond", anlass="Fest 2", datum=date(2026, 9, 1))
    h = admin.get(f"/admin/events/{neu}/checklist/edit?uebernehmen=1").text
    assert "Frau Klar" in h and "0177 9" in h
    assert "Hauptstr. 5" in h and "45127 Essen" in h
    assert "Hof hinten" in h and "Treffpunkt Haupteingang" in h
    assert "Werte übernommen aus" in h


def test_uebernehmen_speichert_noch_nichts(admin):
    alt = make_event(kunde_firma="Kita Stern", anlass="Fest 1", datum=date(2026, 5, 12))
    _mit_briefing(alt, cl_parkplatz="Hof hinten")
    neu = make_event(kunde_firma="Kita Stern", anlass="Fest 2", datum=date(2026, 9, 1))
    admin.get(f"/admin/events/{neu}/checklist/edit?uebernehmen=1")
    # Nur Vorbefüllung im Formular – das Event bleibt unangetastet
    ev = reload(Event, neu)
    assert ev.cl_parkplatz is None
    assert ev.cl_eingereicht_am is None


def test_uebernommene_werte_lassen_sich_speichern(admin):
    alt = make_event(kunde_firma="Kita Welle", anlass="Fest 1", datum=date(2026, 5, 12))
    _mit_briefing(alt, cl_parkplatz="Hof hinten")
    neu = make_event(kunde_firma="Kita Welle", anlass="Fest 2", datum=date(2026, 9, 1))
    admin.post(f"/admin/events/{neu}/checklist/edit",
               data={"ansprechpartner_name": "Frau Klar", "parkplatz": "Hof hinten",
                     "weitere_details": "Treffpunkt Haupteingang"},
               follow_redirects=False)
    ev = reload(Event, neu)
    assert ev.cl_parkplatz == "Hof hinten"
    assert ev.cl_weitere_details == "Treffpunkt Haupteingang"


def test_juengstes_vorgaenger_event_gewinnt(admin):
    alt1 = make_event(kunde_firma="Kita Alt", anlass="Altes Fest", datum=date(2025, 5, 1))
    _mit_briefing(alt1, cl_parkplatz="Alter Hof")
    alt2 = make_event(kunde_firma="Kita Alt", anlass="Neueres Fest", datum=date(2026, 5, 1))
    _mit_briefing(alt2, cl_parkplatz="Neuer Hof")
    neu = make_event(kunde_firma="Kita Alt", anlass="Fest 3", datum=date(2026, 9, 1))
    h = admin.get(f"/admin/events/{neu}/checklist/edit?uebernehmen=1").text
    assert "Neuer Hof" in h and "Alter Hof" not in h
