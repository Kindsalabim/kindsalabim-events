"""Weitere Ansprechpartner: Plus-Zeilen im Event-Formular → JSON am Event →
Anzeige im Briefing (PDF + Mail) und auf der Event-Seite."""
import io
import json

import email_service
from briefing_pdf import build_briefing_pdf
from choices import weitere_ap_liste
from factories import make_event, reload, briefing_event_ns, briefing_dl_ns
from models import Event, Kunde


def _form(**over):
    data = {"anlass": "Sommerfest", "datum": "2026-09-01", "startzeit": "14:00", "endzeit": "18:00",
            "veranstaltungsort": "Markt 1, 45127 Essen", "ort_abweichend": "true",
            "kunde_firma": "Multi AG",
            "produkte": ["Zaubershow"], "marke": "Kindsalabim", "status": "Gebucht"}
    data.update(over)
    return data


def test_create_speichert_weitere_ansprechpartner(admin):
    r = admin.post("/admin/events/new", data={**_form(),
        "wap_name": ["Anna Alt", "Bernd Berg", "  "],
        "wap_telefon": ["0151 111", "", "0152 222"]}, follow_redirects=False)
    assert r.status_code == 303
    eid = int(r.headers["location"].rstrip("/").split("/")[-1])
    aps = weitere_ap_liste(reload(Event, eid))
    assert [a["name"] for a in aps] == ["Anna Alt", "Bernd Berg"]   # leere Zeile übersprungen
    assert aps[0]["telefon"] == "0151 111"
    # Event-Seite zeigt sie, Edit-Formular hat sie vorbefüllt
    h = admin.get(f"/admin/events/{eid}").text
    assert "Anna Alt" in h and "Bernd Berg" in h
    h2 = admin.get(f"/admin/events/{eid}/edit").text
    assert 'name="wap_name" value="Anna Alt"' in h2


def test_briefing_pdf_und_mail_zeigen_weitere(mails):
    import pypdf
    ev = briefing_event_ns(weitere_ansprechpartner=json.dumps(
        [{"name": "Carla Chef", "telefon": "0160 333"}]))
    team = [briefing_dl_ns()]
    pdf = build_briefing_pdf(ev, team, [])
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Carla Chef" in txt and "0160 333" in txt
    email_service.send_briefing(team, ev, "https://x")
    assert "Carla Chef" in mails[-1][2]


def test_formular_hat_plus_knopf(admin):
    h = admin.get("/admin/events/new").text
    assert "weitere Ansprechpartner hinzufügen" in h


def test_kaputtes_json_stoert_nicht():
    ev = briefing_event_ns(weitere_ansprechpartner="kein json {")
    assert weitere_ap_liste(ev) == []


def test_event_formular_bietet_crm_kontakte_als_vorschlaege(admin):
    # Kunde mit weiteren Ansprechpartnern → landet im Autofill-JSON des Event-Formulars,
    # aus dem die Klick-Vorschläge gebaut werden
    admin.post("/admin/crm/new", data={
        "firma": "Vorschlag GmbH",
        "kap_name": ["Vera Vorschlag"], "kap_telefon": ["0170 555"], "kap_email": [""],
    }, follow_redirects=False)
    h = admin.get("/admin/events/new").text
    assert "Vera Vorschlag" in h                 # steckt im kunden-daten-JSON ("weitere")
    assert 'id="ap-vorschlaege"' in h            # Chips-Container vorhanden


def test_crm_kunde_speichert_weitere_ansprechpartner(admin):
    r = admin.post("/admin/crm/new", data={
        "firma": "Planungs AG", "ansprechpartner": "Hr. Haupt",
        "kap_name": ["Petra Plan", ""], "kap_telefon": ["0170 444", ""],
        "kap_email": ["petra@plan.de", ""]}, follow_redirects=False)
    assert r.status_code == 303
    kid = int(r.headers["location"].rstrip("/").split("/")[-1])
    aps = weitere_ap_liste(reload(Kunde, kid))
    assert aps == [{"name": "Petra Plan", "telefon": "0170 444", "email": "petra@plan.de"}]
    # Profil zeigt sie, Edit-Formular hat sie vorbefüllt
    h = admin.get(f"/admin/crm/{kid}").text
    assert "Weitere Ansprechpartner" in h and "Petra Plan" in h
    h2 = admin.get(f"/admin/crm/{kid}/edit").text
    assert 'name="kap_name" value="Petra Plan"' in h2
    assert "weitere Ansprechpartner hinzufügen" in h2
