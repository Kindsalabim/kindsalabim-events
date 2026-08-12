"""Checklisten-Sektion: dezenter „erneut senden"-Link in den beiden „bereits gesendet"-Zuständen
(gesendet/wartet + Kunde hat ausgefüllt). Nur bei vorhandener Kunden-Mail und nicht gesperrt.
Außerdem: (Erneut) senden öffnet die Checkliste wieder – Vorab-Angaben bleiben erhalten
und stehen im Kundenformular vorbefüllt (Vervollständigen statt Überschreiben)."""
from datetime import date, timedelta

from factories import make_event, reload
from models import Event

BALD = date.today() + timedelta(days=20)


def test_resend_link_im_wartezustand(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com", checklist_token="tok-warte")
    r = admin.get(f"/admin/events/{eid}")
    assert r.status_code == 200
    assert "erneut senden" in r.text


def test_resend_link_nach_kundeneingang(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com",
                     checklist_token="tok-fertig", cl_eingereicht_am="30.06.2026")
    r = admin.get(f"/admin/events/{eid}")
    assert "erneut senden" in r.text


def test_kein_resend_ohne_kundenmail(admin):
    eid = make_event(datum=BALD, kunde_email=None, checklist_token="tok-noemail")
    r = admin.get(f"/admin/events/{eid}")
    assert "Link ansehen" in r.text          # Wartezustand wird angezeigt
    assert "erneut senden" not in r.text      # aber kein Resend ohne Mail


def test_erneut_senden_oeffnet_checkliste_mit_vorbefuellung(admin, client):
    # Büro trägt vorab Infos ein („selbst ausgefüllt") → erneut senden → Kunde sieht
    # ein VORBEFÜLLTES Formular (sachliche Felder) statt der Danke-Seite. Interne
    # Team-Notizen („Weitere Details") sieht der Kunde NIE und kann sie nicht löschen.
    eid = make_event(datum=BALD, kunde_email="k@example.com", checklist_token="tok-reopen",
                     cl_eingereicht_am="11.08.2026 09:00 (selbst ausgefüllt)",
                     cl_ansprechpartner_name="Vorab Name", cl_parkplatz="P2 am Werkstor",
                     cl_weitere_details="INTERN: Dame ist nervös, bitte pünktlich sein",
                     cl_verpflegung="Ja", cl_aufbauort="Outdoor, Überdacht")
    r = admin.post(f"/admin/events/{eid}/checklist", follow_redirects=False)
    assert r.status_code == 303
    ev = reload(Event, eid)
    assert ev.cl_eingereicht_am is None                            # wieder offen
    assert "INTERN" in ev.cl_weitere_details                      # nichts verloren

    h = client.get("/checklist/tok-reopen").text
    assert "Vielen Dank" not in h                                  # Formular, keine Danke-Seite
    assert 'value="Vorab Name"' in h                               # sachliche Felder vorbefüllt
    assert "P2 am Werkstor" in h
    assert "nervös" not in h                                       # interne Notiz NIE sichtbar

    # Kunde korrigiert den Namen und schreibt eine eigene Ergänzung
    r2 = client.post("/checklist/tok-reopen", data={
        "ansprechpartner_name": "Kunde Korrigiert", "verpflegung": "Ja", "teamkleidung": "Nein",
        "weitere_details": "Bitte am Nebeneingang klingeln"})
    assert r2.status_code == 200
    ev = reload(Event, eid)
    assert ev.cl_ansprechpartner_name == "Kunde Korrigiert"
    # Interne Notiz bleibt, Kunden-Ergänzung wird angehängt
    assert "INTERN: Dame ist nervös" in ev.cl_weitere_details
    assert "Bitte am Nebeneingang klingeln" in ev.cl_weitere_details
    assert ev.cl_eingereicht_am and "selbst ausgefüllt" not in ev.cl_eingereicht_am


def test_kunde_ohne_ergaenzung_loescht_interne_notiz_nicht(admin, client):
    eid = make_event(datum=BALD, kunde_email="k@example.com", checklist_token="tok-leer",
                     cl_weitere_details="INTERN: Notiz bleibt")
    r = client.post("/checklist/tok-leer", data={
        "ansprechpartner_name": "Kunde X", "verpflegung": "Nein", "teamkleidung": "Ja",
        "weitere_details": ""})
    assert r.status_code == 200
    assert reload(Event, eid).cl_weitere_details == "INTERN: Notiz bleibt"


def test_kein_resend_bei_gesperrtem_event(admin):
    eid = make_event(datum=BALD, kunde_email="kunde@example.com",
                     checklist_token="tok-zu", status="Abgeschlossen")
    r = admin.get(f"/admin/events/{eid}")
    assert "erneut senden" not in r.text
