"""Mehrtägige Reservierungen: Serie anlegen, Serien-Umwandeln, Kopieren-Vorbefüllung."""
from datetime import date

from models import Reservierung, Event
from database import SessionLocal


def _neu(admin, firma, **over):
    data = {
        "datum": "2026-09-10", "kunde_firma": firma, "kunde_kontakt": "Hr. Serie",
        "startzeit": "09:00", "endzeit": "12:00", "art": "WORKSHOP",
        "anlass": "Ferienprogramm", "veranstaltungsort": "45127 Essen",
        "frist": "2026-09-01", "marke": "Kindsalabim",
    }
    data.update(over)
    return admin.post("/admin/reservierungen/new", data=data, follow_redirects=False)


def _res_von(firma):
    s = SessionLocal()
    try:
        return s.query(Reservierung).filter_by(kunde_firma=firma).order_by(Reservierung.datum).all()
    finally:
        s.close()


def test_serie_anlegen_mit_eigenen_und_geerbten_zeiten(admin):
    r = _neu(admin, "Serie Anlegen GmbH",
             extra_datum=["2026-09-11", "2026-09-12"],
             extra_startzeit=["14:00", ""], extra_endzeit=["17:00", ""])
    assert r.status_code == 303
    res = _res_von("Serie Anlegen GmbH")
    assert len(res) == 3
    assert res[0].serien_id and all(x.serien_id == res[0].serien_id for x in res)
    # Tag 2 mit eigener Uhrzeit, Tag 3 erbt die Zeiten des Haupttags
    assert (res[1].startzeit, res[1].endzeit) == ("14:00", "17:00")
    assert (res[2].startzeit, res[2].endzeit) == ("09:00", "12:00")
    # Frist & Kundendaten gelten für alle Tage
    assert all(x.frist == date(2026, 9, 1) for x in res)
    assert all(x.kunde_kontakt == "Hr. Serie" and x.art == "WORKSHOP" for x in res)


def test_einzel_reservierung_bekommt_keine_serien_id(admin):
    _neu(admin, "Einzel Ohne Serie GmbH")
    res = _res_von("Einzel Ohne Serie GmbH")
    assert len(res) == 1 and res[0].serien_id is None


def test_ungueltiges_extra_datum_legt_nichts_an(admin):
    r = _neu(admin, "Serie Kaputt GmbH", extra_datum=["kein-datum"])
    assert r.status_code == 303 and "error=datum" in r.headers["location"]
    assert _res_von("Serie Kaputt GmbH") == []


def test_liste_zeigt_serien_chip_und_kopieren_link(admin):
    _neu(admin, "Serie Chip GmbH", extra_datum=["2026-09-11"], extra_startzeit=[""], extra_endzeit=[""])
    h = admin.get("/admin/reservierungen").text
    assert "🔗 Serie · 2 Termine" in h
    assert "?kopie=" in h and ">Kopieren</a>" in h


def test_kopie_param_befuellt_formular_vor(admin):
    _neu(admin, "Kopiervorlage GmbH", kunde_email="kopie@example.com", notiz="Angebot 1234")
    rid = _res_von("Kopiervorlage GmbH")[0].id
    h = admin.get(f"/admin/reservierungen?kopie={rid}").text
    assert 'value="Kopiervorlage GmbH"' in h
    assert 'value="kopie@example.com"' in h
    assert "Angebot 1234" in h
    assert "Daten aus der Reservierung" in h  # Hinweisbalken, Formular offen
    # Termin-Datum bleibt bewusst leer (wie beim Event-Kopieren)
    assert 'name="datum" required class' in h and 'name="datum" value=' not in h


def test_serie_umwandeln_erzeugt_termin_serie(admin):
    _neu(admin, "Serie Umwandeln GmbH",
         extra_datum=["2026-09-11"], extra_startzeit=["14:00"], extra_endzeit=["17:00"])
    res = _res_von("Serie Umwandeln GmbH")
    # Umwandeln vom ZWEITEN Tag aus geklickt → Redirect aufs Event dieses Tags
    r = admin.post(f"/admin/reservierungen/{res[1].id}/umwandeln", follow_redirects=False)
    assert r.status_code == 303 and "/edit" in r.headers["location"]
    assert _res_von("Serie Umwandeln GmbH") == []  # alle Reservierungen weg
    s = SessionLocal()
    try:
        evs = s.query(Event).filter_by(kunde_firma="Serie Umwandeln GmbH").order_by(Event.datum).all()
        assert len(evs) == 2
        assert evs[0].serien_id and evs[0].serien_id == evs[1].serien_id
        assert all(e.status == "Gebucht" for e in evs)
        assert (evs[1].startzeit, evs[1].endzeit) == ("14:00", "17:00")
        assert r.headers["location"] == f"/admin/events/{evs[1].id}/edit"
    finally:
        s.close()


def test_einzel_umwandeln_bleibt_ohne_serien_id(admin):
    _neu(admin, "Einzel Umwandeln GmbH")
    rid = _res_von("Einzel Umwandeln GmbH")[0].id
    r = admin.post(f"/admin/reservierungen/{rid}/umwandeln", follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    try:
        ev = s.query(Event).filter_by(kunde_firma="Einzel Umwandeln GmbH").first()
        assert ev is not None and ev.serien_id is None and ev.status == "Gebucht"
    finally:
        s.close()
