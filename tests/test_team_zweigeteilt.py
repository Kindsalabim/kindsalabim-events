"""Team-Bereich zweigeteilt (Aykut 24.11.2026): Teamer links, Künstler je gebuchter
Aktion rechts, Absagen eingeklappt; Künstler-Anfragen merken sich ihre Aktion."""
from types import SimpleNamespace

from choices import kuenstler_gruppen, kuenstler_aktionen, nach_status
from database import SessionLocal
from models import Verfuegbarkeitsanfrage
from factories import make_event, make_dienstleister, make_anfrage


def _a(status="Ausstehend", rolle="Künstler", aktion=None, sparte=""):
    return SimpleNamespace(status=status, rolle_anfrage=rolle, aktion=aktion,
                           dienstleister=SimpleNamespace(kuenstler_sparte=sparte))


def test_kuenstler_aktionen_in_buchungsreihenfolge():
    assert kuenstler_aktionen("Glitzertattoos, Kinderschminken, Ballonmodellage") == \
        ["Kinderschminken", "Ballonmodellage"]


def test_zuordnung_gespeichert_profil_und_unklar():
    schminke = _a(sparte="Kinderschminke")
    ballon = _a(sparte="Ballonkünstler")
    beides = _a(sparte="Kinderschminke, Ballonkünstler")
    beides_gespeichert = _a(sparte="Kinderschminke, Ballonkünstler", aktion="Ballonmodellage")
    teamer = _a(rolle="Teamer")
    gr = dict(kuenstler_gruppen("Kinderschminken, Ballonmodellage",
                                [schminke, ballon, beides, beides_gespeichert, teamer]))
    assert gr["Kinderschminken"] == [schminke]
    assert gr["Ballonmodellage"] == [ballon, beides_gespeichert]
    assert gr["ohne Zuordnung"] == [beides]          # die App rät nicht


def test_nur_eine_kuenstler_aktion_nimmt_alle():
    a = _a(sparte="Showact")
    assert kuenstler_gruppen("Kinderschminken", [a]) == [("Kinderschminken", [a])]


def test_ohne_kuenstler_aktion_eine_gruppe():
    a = _a(sparte="Kinderschminke")
    assert kuenstler_gruppen("Bastelaktion", [a]) == [(None, [a])]


def test_status_reihenfolge_absagen_zuletzt():
    ja, offen, nein = _a("Ja"), _a("Ausstehend"), _a("Nein")
    assert nach_status([nein, offen, ja]) == [ja, offen, nein]


def test_anfrage_speichert_aktion(admin):
    eid = make_event(produkte="Kinderschminken, Ballonmodellage")
    did = make_dienstleister()
    r = admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler", "direkt": "1",
        "aktion": "Ballonmodellage"}, follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    a = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=eid, dienstleister_id=did).first()
    assert a.aktion == "Ballonmodellage"
    s.close()


def test_anfrage_unbekannte_aktion_wird_nicht_gespeichert(admin):
    eid = make_event(produkte="Kinderschminken, Ballonmodellage")
    did = make_dienstleister()
    admin.post(f"/admin/events/{eid}/anfragen", data={
        "dienstleister_ids": [str(did)], "rolle": "Künstler", "direkt": "1", "aktion": "Quatsch"})
    s = SessionLocal()
    a = s.query(Verfuegbarkeitsanfrage).filter_by(event_id=eid, dienstleister_id=did).first()
    assert a.aktion is None
    s.close()


def test_seite_zeigt_haelften_aktionen_und_eingeklappte_absagen(admin):
    eid = make_event(produkte="Kinderschminken, Ballonmodellage", anzahl_teamer=1, anzahl_kuenstler=2)
    make_anfrage(eid, make_dienstleister(), status="Nein", rolle="Teamer")
    make_anfrage(eid, make_dienstleister(), status="Nein", rolle="Teamer")
    html = admin.get(f"/admin/events/{eid}").text
    assert "+ Teamer anfragen" in html
    assert "+ Künstler für Kinderschminken anfragen" in html
    assert "+ Künstler für Ballonmodellage anfragen" in html
    assert "2 Absagen anzeigen" in html
    assert "Verfügbarkeitsanfragen senden" not in html
