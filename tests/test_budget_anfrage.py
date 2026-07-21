"""Künstler-Budget bei der Anfrage: speichern, in der Mail zeigen, optional lassen."""
from database import SessionLocal
from models import Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister


def _budget(eid, did):
    s = SessionLocal()
    try:
        a = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=eid, dienstleister_id=did).first()
        return a.budget if a else None
    finally:
        s.close()


def test_anfrage_speichert_budget_und_mailzeile(admin, mails):
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1)
    did = make_dienstleister(rolle="Künstler", kuenstler_sparte="Kinderschminke")
    r = admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler", "budget": "296"},
        follow_redirects=False)
    assert r.status_code == 303
    assert abs((_budget(eid, did) or 0) - 296.0) < 0.01
    assert "296,00 € pauschal (inkl. Fahrtkosten)" in mails[-1][2]


def test_budget_komma_eingabe(admin, mails):
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1)
    did = make_dienstleister(rolle="Künstler")
    admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler", "budget": "296,50"},
        follow_redirects=False)
    assert abs((_budget(eid, did) or 0) - 296.5) < 0.01


def test_ohne_budget_keine_mailzeile(admin, mails):
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1)
    did = make_dienstleister(rolle="Künstler")
    admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler"}, follow_redirects=False)
    assert _budget(eid, did) is None
    assert "pauschal (inkl. Fahrtkosten)" not in mails[-1][2]


def test_direkt_eintrag_speichert_budget(admin):
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1)
    did = make_dienstleister(rolle="Künstler")
    admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler", "budget": "296", "direkt": "1"},
        follow_redirects=False)
    assert abs((_budget(eid, did) or 0) - 296.0) < 0.01


def test_kuenstler_formular_zeigt_budgetfeld_und_hinweis(admin):
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1)
    make_dienstleister(rolle="Künstler")
    h = admin.get(f"/admin/events/{eid}").text
    assert 'name="budget"' in h
    assert "pauschal (inkl. Fahrtkosten)" in h
    assert "Keine Auftragsbestätigung hochgeladen" in h   # ohne AB → manueller Hinweis
