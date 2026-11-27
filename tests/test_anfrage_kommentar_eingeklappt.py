"""Kommentar einer Anfrage steht in der Team-Übersicht eingeklappt unter dem Namen
(Aykut 26.11.2026: sonst wird die Übersicht lang)."""
from factories import make_event, make_dienstleister, make_anfrage


def test_kommentar_eingeklappt(admin):
    eid = make_event()
    make_anfrage(eid, make_dienstleister(), status="Ausstehend", notiz="Bitte Zelt mitbringen")
    h = admin.get(f"/admin/events/{eid}").text
    assert '<details class="anf-kommentar"><summary>Kommentar</summary>' in h
    assert "Bitte Zelt mitbringen" in h
