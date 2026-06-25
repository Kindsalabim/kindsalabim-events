"""Eventbericht: 'Wie gelaufen' Mehrfachauswahl, Foto-Feld (Galerie/Mehrfach)."""
import re

from models import Event
from factories import make_event, make_dienstleister, reload, portal_login


def _event_mit_teamleiter():
    did = make_dienstleister()
    eid = make_event(status="Briefing gesendet", teamleiter_id=did)
    return eid, did


def test_verlauf_mehrfachauswahl_speichern_und_laden(client):
    eid, did = _event_mit_teamleiter()
    portal_login(client, did)
    r = client.post(f"/portal/bericht/{eid}", data={
        "kinder": "20–50",
        "verlauf": ["Alles reibungslos", "Kleinere Herausforderungen gemeistert"],
        "verlauf_text": "lief super", "feedback": "Begeistert"}, follow_redirects=False)
    assert r.status_code == 303
    assert reload(Event, eid).bericht_verlauf == \
        "Alles reibungslos, Kleinere Herausforderungen gemeistert\n\nlief super"
    # Wiederöffnen: beide Optionen vorausgewählt
    h = client.get(f"/portal/bericht/{eid}").text
    for opt in ["Alles reibungslos", "Kleinere Herausforderungen gemeistert"]:
        assert re.search(r'value="' + re.escape(opt) + r'"[^>]*checked', h), opt
    assert not re.search(r'value="Schwierige Bedingungen"[^>]*checked', h)


def test_verlauf_inputs_sind_checkboxen_und_foto_feld(client):
    eid, did = _event_mit_teamleiter()
    portal_login(client, did)
    h = client.get(f"/portal/bericht/{eid}").text
    typen = re.findall(r'<input type="(\w+)" name="verlauf"', h)
    assert typen and all(t == "checkbox" for t in typen)
    foto = re.search(r'<input type="file"[^>]*>', h).group(0)
    assert "capture" not in foto and "multiple" in foto


def test_mehrere_fotos_upload(client, uploads):
    eid, did = _event_mit_teamleiter()
    portal_login(client, did)
    files = [("file", ("a.jpg", b"x", "image/jpeg")), ("file", ("b.jpg", b"y", "image/jpeg"))]
    r = client.post(f"/portal/events/{eid}/fotos", files=files, follow_redirects=False)
    assert r.status_code == 303 and len(uploads) == 2
