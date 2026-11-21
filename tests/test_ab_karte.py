"""Auftragsbestätigung als eigene Karte zwischen Briefing und Abschluss (Aykut 21.11.2026):
es gibt immer nur EINE – ohne Datei ein Hochladen-Link, mit Datei nur Mülleimer
(zum Aktualisieren löschen + neu hochladen), kein „Weitere hochladen“."""
from database import SessionLocal
from models import EventDatei
from factories import make_event


def _ab_karte(html):
    start = html.index("<!-- Auftragsbestätigung: es gibt immer nur EINE")
    return html[start:html.index("<!-- Abschluss -->", start)]


def test_ohne_ab_zeigt_hochladen(admin):
    eid = make_event(produkte="Bastelaktion")
    html = admin.get(f"/admin/events/{eid}").text
    karte = _ab_karte(html)
    assert "Auftragsbestätigung hochladen" in karte
    # Reihenfolge: Briefing → AB-Karte → Abschluss
    assert html.index('id="wf-briefing"') < html.index("<!-- Auftragsbestätigung: es gibt") < html.index('id="wf-abschluss"')


def test_mit_ab_nur_muelleimer(admin):
    # produkte ohne Künstler-Aktion → kein AB-Budget-Parsing (das würde die Datei laden)
    eid = make_event(produkte="Bastelaktion")
    s = SessionLocal()
    s.add(EventDatei(event_id=eid, r2_key=f"test/ab-{eid}.pdf", filename="AB_Test.pdf",
                     typ="auftragsbestaetigung", uploaded_at="2026-11-21T10:00:00"))
    s.commit(); s.close()
    karte = _ab_karte(admin.get(f"/admin/events/{eid}").text)
    assert "AB_Test.pdf" in karte
    assert "Auftragsbestätigung löschen" in karte
    assert 'type="file"' not in karte and "Weitere hochladen" not in karte
