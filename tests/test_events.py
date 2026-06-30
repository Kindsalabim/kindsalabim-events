"""Event-Formular: Validierung, Pflichtfeld-Entschärfung, None-Vorbelegung, Material-Info."""
import re

from models import Event
from factories import make_event, reload


def _form(**over):
    data = {"anlass": "Sommerfest", "datum": "2026-08-01", "startzeit": "14:00", "endzeit": "18:00",
            "veranstaltungsort": "Markt 1, 45127 Essen", "kunde_firma": "Kunde X",
            "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht"}
    data.update(over)
    return data


def test_create_minimal(admin):
    r = admin.post("/admin/events/new", data=_form(), follow_redirects=False)
    assert r.status_code == 303
    eid = int(r.headers["location"].rstrip("/").split("/")[-1])
    assert reload(Event, eid) is not None


def test_create_without_produkte_rejected(admin):
    r = admin.post("/admin/events/new", data=_form(produkte=[]), follow_redirects=False)
    assert r.status_code == 200 and "mindestens eine Aktion" in r.text


def test_zaubershow_without_produkte_ok(admin):
    r = admin.post("/admin/events/new",
                   data=_form(produkte=[], zaubershow_event="true", kunde_firma=""),
                   follow_redirects=False)
    assert r.status_code == 303


def test_zaubershow_abschluss_nur_rechnung():
    """Reines Zaubershow-Event: Abschluss allein über die Rechnung – KEIN Eventbericht nötig."""
    from routes.admin import auto_status
    from database import SessionLocal
    eid = make_event(zaubershow_event=True, produkte="Zaubershow")
    s = SessionLocal()
    ev = s.get(Event, eid)
    assert auto_status(ev, s) != "Abgeschlossen"      # ohne Rechnung noch offen
    ev.rechnung_gestellt = True; s.commit()
    assert auto_status(ev, s) == "Abgeschlossen"      # Rechnung reicht, ohne bericht_eingereicht_am
    assert ev.bericht_eingereicht_am is None
    s.close()


def test_zaubershow_detail_zeigt_bericht_nicht_noetig(admin):
    eid = make_event(zaubershow_event=True, produkte="Zaubershow")
    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "Abschluss erfolgt allein über die Rechnung" in r.text


def test_normales_event_braucht_bericht_und_rechnung():
    """Gegenprobe: Nicht-Zaubershow-Event schließt erst mit Bericht UND Rechnung."""
    from routes.admin import auto_status
    from database import SessionLocal
    eid = make_event(status="Briefing gesendet", rechnung_gestellt=True)
    s = SessionLocal()
    ev = s.get(Event, eid)
    assert auto_status(ev, s) != "Abgeschlossen"      # nur Rechnung reicht hier nicht
    s.close()


def test_abgesagt_saves_minimal(admin):
    eid = make_event()
    r = admin.post(f"/admin/events/{eid}/edit",
                   data=_form(status="Abgesagt", produkte=[], kunde_firma="", endzeit=""),
                   follow_redirects=False)
    assert r.status_code == 303
    assert reload(Event, eid).status == "Abgesagt"


def test_empty_fields_not_rendered_as_none(admin):
    eid = make_event(kunde_telefon=None, kunde_email=None, kunde_kontakt=None)
    h = admin.get(f"/admin/events/{eid}/edit").text
    assert 'value="None"' not in h and ">None<" not in h


def test_optional_fields_not_required(admin):
    eid = make_event()
    h = admin.get(f"/admin/events/{eid}/edit").text
    for feld in ["endzeit", "veranstaltungsort", "kunde_firma"]:
        tag = re.search(r'name="' + feld + r'"[^>]*>', h).group(0)
        assert "required" not in tag, feld


def test_material_info_preset_then_sonstige(admin):
    eid = make_event(material_mitnahme=True)
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(material_mitnahme="true", material_info_choice="Viel – nur mit Transporter"),
               follow_redirects=False)
    assert reload(Event, eid).material_info == "Viel – nur mit Transporter"
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(material_mitnahme="true", material_info_choice="Sonstige", material_info_text="2 Kisten"),
               follow_redirects=False)
    assert reload(Event, eid).material_info == "2 Kisten"


def test_edit_recompute_zaubershow_schliesst_ab(admin):
    """DMT-Fall: Status wird beim Bearbeiten neu berechnet – nachträgliches Setzen von
    „Zaubershow-Event" schließt bei bereits gestellter Rechnung das Event ab."""
    eid = make_event(status="Briefing gesendet", rechnung_gestellt=True, produkte="Zaubershow")
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(status="Briefing gesendet", zaubershow_event="true"),
               follow_redirects=False)
    assert reload(Event, eid).status == "Abgeschlossen"


def test_edit_recompute_ohne_rechnung_bleibt_offen(admin):
    """Gegenprobe: ohne Rechnung schließt das Zaubershow-Event NICHT (kein Über-Schließen)."""
    eid = make_event(status="Briefing gesendet", produkte="Zaubershow")
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(status="Briefing gesendet", zaubershow_event="true"),
               follow_redirects=False)
    assert reload(Event, eid).status == "Briefing gesendet"


def test_edit_manueller_status_wird_respektiert(admin):
    """Wird der Status im Formular bewusst geändert, bleibt die manuelle Wahl erhalten
    (keine automatische Neuberechnung, die sie überschreiben würde)."""
    eid = make_event(status="Gebucht")
    admin.post(f"/admin/events/{eid}/edit",
               data=_form(status="Planung fertig"),
               follow_redirects=False)
    assert reload(Event, eid).status == "Planung fertig"
