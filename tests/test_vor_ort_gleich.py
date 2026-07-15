"""Event-Formular: Häkchen „Gleich wie Kontaktperson der Firma" spiegelt den
Buchungskontakt in die Vor-Ort-Felder (spart Copy&Paste)."""
from factories import make_event


def test_neues_event_zeigt_haekchen_ungesetzt(admin):
    h = admin.get("/admin/events/new").text
    assert 'id="vor_ort_gleich"' in h
    assert "Gleich wie Kontaktperson der Firma" in h
    # Ohne Event gibt es nichts zu spiegeln → Häkchen aus
    block = h[h.index('id="vor_ort_gleich"'):h.index('id="vor_ort_gleich"') + 200]
    assert "checked" not in block


def test_haekchen_vorbelegt_wenn_werte_identisch(admin):
    eid = make_event(kunde_kontakt="Frau Klar", kunde_telefon="0201 123",
                     vor_ort_name="Frau Klar", vor_ort_telefon="0201 123")
    h = admin.get(f"/admin/events/{eid}/edit").text
    block = h[h.index('id="vor_ort_gleich"'):h.index('id="vor_ort_gleich"') + 200]
    assert "checked" in block


def test_haekchen_aus_wenn_werte_abweichen(admin):
    eid = make_event(kunde_kontakt="Frau Klar", kunde_telefon="0201 123",
                     vor_ort_name="Herr Anders", vor_ort_telefon="0177 999")
    h = admin.get(f"/admin/events/{eid}/edit").text
    block = h[h.index('id="vor_ort_gleich"'):h.index('id="vor_ort_gleich"') + 200]
    assert "checked" not in block


def test_gespiegelte_werte_werden_gespeichert(admin):
    # Die Felder sind nur readOnly (nicht disabled) → Werte kommen beim Speichern mit
    eid = make_event()
    data = {"anlass": "Fest", "datum": "2026-08-01", "startzeit": "14:00", "endzeit": "18:00",
            "veranstaltungsort": "Markt 1, 45127 Essen", "kunde_firma": "K",
            "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht",
            "kunde_kontakt": "Frau Klar", "kunde_telefon": "0201 123",
            "vor_ort_name": "Frau Klar", "vor_ort_telefon": "0201 123"}
    r = admin.post(f"/admin/events/{eid}/edit", data=data, follow_redirects=False)
    assert r.status_code == 303
    from models import Event
    from factories import reload
    ev = reload(Event, eid)
    assert ev.vor_ort_name == "Frau Klar" and ev.vor_ort_telefon == "0201 123"
