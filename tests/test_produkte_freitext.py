"""Airbrush-Tattoos als Künstler-Aktion + Freitextfeld für ausgefallene Buchungen."""
from choices import PRODUKT_SPARTE, benoetigte_sparten
from models import Event
from factories import reload
from routes.admin import PRODUKTE_LIST, _mit_freitext
import ankunft


def _form(**over):
    data = {"anlass": "Sommerfest", "datum": "2026-08-01", "startzeit": "14:00", "endzeit": "18:00",
            "veranstaltungsort": "Markt 1, 45127 Essen", "kunde_firma": "Kunde X",
            "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht"}
    data.update(over)
    return data


def test_airbrush_ueberall_verdrahtet(admin):
    assert "Airbrush-Tattoos" in PRODUKTE_LIST
    # Sparte wie Kinderschminken → Nachbesetzungs-Vorschlag filtert richtig
    assert PRODUKT_SPARTE["Airbrush-Tattoos"] == {"Kinderschminke", "Schminke + Ballon"}
    assert benoetigte_sparten("Airbrush-Tattoos") == {"Kinderschminke", "Schminke + Ballon"}
    # Reine Künstler-Buchung → Eigenverantwortung; im Mix 30 Min Vorlauf
    assert ankunft.auto_vorlauf("Airbrush-Tattoos") is None
    assert ankunft.auto_vorlauf("Airbrush-Tattoos, Bastelaktion") == 45
    assert "Airbrush-Tattoos" in admin.get("/admin/events/new").text


def test_mit_freitext_haengt_an_und_dedupliziert():
    assert _mit_freitext(["Zaubershow"], "") == ["Zaubershow"]
    assert _mit_freitext([], "Riesenseifenblasen-Show") == ["Riesenseifenblasen-Show"]
    assert _mit_freitext(["Zaubershow"], " Ponyreiten , Zaubershow ,, Kettcar-Parcours ") == [
        "Zaubershow", "Ponyreiten", "Kettcar-Parcours"]


def test_event_nur_mit_freitext_aktion(admin):
    # Keine Checkbox angehakt, nur Freitext → erfüllt die „mind. eine Aktion"-Pflicht
    r = admin.post("/admin/events/new",
                   data=_form(produkte=[], produkte_freitext="Riesenseifenblasen-Show"),
                   follow_redirects=False)
    assert r.status_code == 303
    eid = int(r.headers["location"].rstrip("/").split("/")[-1])
    assert reload(Event, eid).produkte == "Riesenseifenblasen-Show"


def test_freitext_ergaenzt_checkboxen_und_bleibt_beim_bearbeiten(admin):
    r = admin.post("/admin/events/new",
                   data=_form(produkte=["Zaubershow"], produkte_freitext="Ponyreiten"),
                   follow_redirects=False)
    eid = int(r.headers["location"].rstrip("/").split("/")[-1])
    assert reload(Event, eid).produkte == "Zaubershow, Ponyreiten"
    # Beim Bearbeiten erscheint die Freitext-Aktion als „übernommen"-Checkbox
    h = admin.get(f"/admin/events/{eid}/edit").text
    assert "Ponyreiten" in h and "übernommen" in h
