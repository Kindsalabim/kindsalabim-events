"""Event kopieren (Stammkunden buchen dieselbe Aktion wieder): GET /events/{id}/kopieren
zeigt das Neues-Event-Formular mit allen Stammdaten vorbefüllt – Datum leer, Status
„Gebucht", Absenden legt ein normales neues Event an (nichts wird verknüpft)."""
from factories import make_event


def test_kopieren_vorbefuellt_stammdaten(admin):
    eid = make_event(anlass="Sommerfest", kunde_firma="Stammkunde GmbH",
                     veranstaltungsort="Werksgelände 5, 45889 Gelsenkirchen",
                     kunde_kontakt="Hr. Treu", hinweise="Parken hinter Halle 3",
                     anzahl_teamer=3, status="Abgeschlossen")
    h = admin.get(f"/admin/events/{eid}/kopieren").text
    assert 'action="/admin/events/new"' in h           # legt ein NEUES Event an
    assert "Stammkunde GmbH" in h
    assert "Werksgelände 5, 45889 Gelsenkirchen" in h
    assert "Parken hinter Halle 3" in h
    assert 'name="datum" required value=""' in h       # Datum bewusst leer
    assert '<option value="Gebucht" selected>' in h    # Status startet neu, nicht „Abgeschlossen"


def test_kopieren_unbekanntes_event_404(admin):
    assert admin.get("/admin/events/999999/kopieren").status_code == 404


def test_kopieren_button_auf_event_seite(admin):
    eid = make_event()
    h = admin.get(f"/admin/events/{eid}").text
    assert f'href="/admin/events/{eid}/kopieren"' in h
