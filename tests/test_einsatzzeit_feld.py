"""Anfrage-Formular: die Uhrzeit-Felder „Gesonderte Aktionszeit“ sind zu, bis das
Häkchen gesetzt wird (21.11.2026 – vorher überstimmte die Klasse „flex“ das hidden)."""
from factories import make_event


def test_aktionszeit_felder_starten_versteckt(admin):
    eid = make_event(produkte="Bastelaktion")
    html = admin.get(f"/admin/events/{eid}").text
    zeilen = [z for z in html.split("\n") if "<div data-einsatzzeit" in z]
    assert zeilen, "Aktionszeit-Zeile fehlt"
    for z in zeilen:
        assert "display:none" in z and " hidden" not in z
