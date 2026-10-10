"""Kunden-Checkliste bei Termin-Serien (vorgemerkt 29.09., gebaut 10.10.2026).

Ein mehrtägiger Auftrag besteht aus einzelnen Events mit gemeinsamer serien_id. Bisher
musste je Tag eine Checkliste raus, und der Kunde füllte dasselbe Formular mehrfach aus.
Jetzt: eine Mail, ein Formular, gemeinsame Angaben einmal, Zeiten und notfalls die
Adresse je Tag. Für einen einzelnen Tag ändert sich nichts.
"""
from datetime import date, timedelta

from factories import make_event, reload
from models import Event

START = date.today() + timedelta(days=30)


def _serie(sid, n=3, **kw):
    """n Termintage mit Lücke (Fr, Sa, Mo), wie im echten Buchungsalltag."""
    abstaende = [0, 1, 3, 4, 5][:n]
    return [make_event(datum=START + timedelta(days=d), serien_id=sid,
                       kunde_email="kunde@example.test", kunde_kontakt="Sandra Schero",
                       startzeit="12:00", endzeit="19:00", **kw)
            for d in abstaende]


def test_versand_eine_mail_fuer_alle_tage(admin, mails):
    ids = _serie("serie-versand")
    r = admin.post(f"/admin/events/{ids[1]}/checklist", follow_redirects=False)
    assert r.status_code == 303
    assert len(mails) == 1                                   # eine Mail, nicht drei
    to, betreff, html = mails[0]
    assert "3 Termine" in betreff
    for eid in ids:
        ev = reload(Event, eid)
        assert ev.checklist_token                            # jeder Tag hat einen Link
        assert ev.cl_eingereicht_am is None
        assert ev.datum.strftime("%d.%m.%Y") in html         # alle Termine in der Mail
    assert "Hallo Frau Schero," in html


def test_formular_zeigt_alle_tage(admin, client):
    ids = _serie("serie-form")
    admin.post(f"/admin/events/{ids[0]}/checklist", follow_redirects=False)
    tok = reload(Event, ids[2]).checklist_token              # Link eines späteren Tages
    h = client.get(f"/checklist/{tok}").text
    assert "3 Termine" in h and "einmal für alle Termine" in h
    for eid in ids:
        assert f'name="aufbau_von_{eid}"' in h
        assert f'name="andere_adresse_{eid}"' in h
    assert "Unsere Aktion: 12:00 bis 19:00 Uhr" in h


def test_antworten_landen_auf_allen_tagen(admin, client):
    ids = _serie("serie-speichern")
    admin.post(f"/admin/events/{ids[0]}/checklist", follow_redirects=False)
    tok = reload(Event, ids[0]).checklist_token
    daten = {"ansprechpartner_name": "Erika Muster", "ansprechpartner_mobil": "0170 1",
             "firma_name": "Messe Essen", "strasse": "Norbertstr. 2", "plz_ort": "45131 Essen",
             "verpflegung": "Ja", "teamkleidung": "Ja", "parkplatz": "Tor 3",
             "anlieferung_vortag": "Ja", "anlieferung_von": "16:00", "anlieferung_bis": "18:00",
             "abholung_folgetag": "Ja", "abholung_von": "08:00", "abholung_bis": "10:00"}
    for i, eid in enumerate(ids):
        daten[f"aufbau_von_{eid}"] = f"0{8 + i}:00"
        daten[f"abbau_bis_{eid}"] = "20:00"
    # Am letzten Tag eine andere Adresse
    daten[f"andere_adresse_{ids[2]}"] = "Ja"
    daten[f"strasse_{ids[2]}"] = "Gruga-Allee 1"
    daten[f"plz_ort_{ids[2]}"] = "45131 Essen"
    r = client.post(f"/checklist/{tok}", data=daten)
    assert r.status_code == 200 and "Vielen Dank" in r.text

    tage = [reload(Event, eid) for eid in ids]
    for i, ev in enumerate(tage):
        assert ev.cl_eingereicht_am                          # alle Tage abgeschlossen
        assert ev.cl_ansprechpartner_name == "Erika Muster"  # gemeinsame Angaben überall
        assert ev.cl_parkplatz == "Tor 3"
        assert ev.cl_aufbau_von == f"0{8 + i}:00"            # Zeiten je Tag
    assert tage[0].cl_strasse == tage[1].cl_strasse == "Norbertstr. 2"
    assert tage[2].cl_strasse == "Gruga-Allee 1"             # abweichende Adresse
    # Vortag-Anlieferung nur am ersten, Folgetag-Abholung nur am letzten Tag
    assert tage[0].cl_anlieferung_vortag and not tage[1].cl_anlieferung_vortag
    assert tage[2].cl_abholung_folgetag and not tage[0].cl_abholung_folgetag


def test_ohne_haekchen_bleibt_die_gemeinsame_adresse(admin, client):
    ids = _serie("serie-adresse", n=2)
    admin.post(f"/admin/events/{ids[0]}/checklist", follow_redirects=False)
    tok = reload(Event, ids[0]).checklist_token
    client.post(f"/checklist/{tok}", data={
        "ansprechpartner_name": "X", "verpflegung": "Ja", "teamkleidung": "Ja",
        "strasse": "Hauptstr. 1", f"strasse_{ids[1]}": "Ignoriert 9"})   # kein Häkchen
    assert reload(Event, ids[1]).cl_strasse == "Hauptstr. 1"


def test_link_gilt_bis_30_tage_nach_dem_letzten_tag(client):
    """Der Link hängt am ersten Tag, die Serie läuft aber länger."""
    alt = date.today() - timedelta(days=35)
    ids = [make_event(datum=alt, serien_id="serie-ablauf", checklist_token="tok-ablauf-serie"),
           make_event(datum=date.today() - timedelta(days=2), serien_id="serie-ablauf")]
    assert client.get("/checklist/tok-ablauf-serie").status_code == 200
    assert ids


def test_einzelner_tag_bleibt_wie_bisher(admin, client, mails):
    eid = make_event(datum=START, kunde_email="k@example.test", checklist_token="tok-einzeln")
    admin.post(f"/admin/events/{eid}/checklist", follow_redirects=False)
    assert "3 Termine" not in mails[-1][1] and "Uhrzeit" in mails[-1][2]
    h = client.get("/checklist/tok-einzeln").text
    assert 'name="aufbau_von"' in h and "einmal für alle Termine" not in h
