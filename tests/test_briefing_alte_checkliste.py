"""„Briefing bearbeiten“ bei Checklisten von vor dem 12.11.2026 (cl_ort_gleich leer):
die damals als Veranstaltungsort eingetragene Location steht im Formular unter
„Veranstaltungsort“, nicht unter „Firmendaten“ mit Haken „gleich“ (Aykut 26.11.2026)."""
from factories import make_event, reload
from models import Event
from veranstaltungsort import anschrift


def _alt(**kw):
    return make_event(kunde_firma="Agentur X", cl_firma_name="Toys R Us Essen",
                      cl_strasse="Hauptstr. 1", cl_plz_ort="45127 Essen",
                      cl_eingereicht_am="01.11.2026 10:00", **kw)


def test_formular_zeigt_location_als_veranstaltungsort(admin):
    eid = _alt()
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert 'name="ort_name" value="Toys R Us Essen"' in h
    assert 'name="ort_strasse" value="Hauptstr. 1"' in h
    assert 'name="firma_name" value="Agentur X"' in h
    i = h.index('name="ort_gleich"')
    assert not h[i:h.index(">", i)].rstrip().endswith("checked")


def test_speichern_legt_neues_format_ab_briefing_bleibt_gleich(admin):
    eid = _alt()
    vorher = anschrift(reload(Event, eid))
    admin.post(f"/admin/events/{eid}/checklist/edit", data={
        "firma_name": "Agentur X", "ort_name": "Toys R Us Essen",
        "ort_strasse": "Hauptstr. 1", "ort_plz_ort": "45127 Essen"})
    ev = reload(Event, eid)
    assert ev.cl_ort_gleich is False and ev.cl_ort_name == "Toys R Us Essen"
    assert anschrift(ev) == vorher


def test_neue_checkliste_mit_haken_bleibt_unveraendert(admin):
    eid = make_event(kunde_firma="Kita Sonne", cl_firma_name="Kita Sonne",
                     cl_strasse="Weg 2", cl_plz_ort="45289 Essen", cl_ort_gleich=True)
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert 'name="strasse" value="Weg 2"' in h
    i = h.index('name="ort_gleich"')
    assert h[i:h.index(">", i)].rstrip().endswith("checked")
