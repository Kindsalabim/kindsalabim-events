"""Dienstleister-Formular: Nach einem Validierungsfehler bleiben ALLE Eingaben
erhalten (vorher wurde das Formular leer neu gerendert – alles Getippte war weg)."""
from models import Dienstleister
from factories import make_dienstleister, reload


def _daten(**over):
    d = {"vorname": "Ayse", "nachname": "Yilmaz", "email": "ayse.neu@example.com",
         "telefon": "keine nummer!", "strasse": "Musterweg 3", "plz": "45127",
         "stadt": "Essen", "rolle": "Künstler", "kuenstler_sparte": "Kinderschminke",
         "lieferantenbewertung": "8", "mobilitaet": "ÖPNV", "kleidergroesse": "M",
         "aktiv": "true", "logistiker": "true", "fuehrerschein": "true",
         "gebiet": "Ruhrgebiet", "verfuegbarkeit": "Nur Wochenende",
         "vertragstyp": "Freelancer", "stundensatz_teamer": "25,00",
         "stundensatz_kuenstler": "60,00", "website": "https://ayse.example",
         "notizen": "Über Melissa gekommen", "dsgvo_unterzeichnet": "true"}
    d.update(over)
    return d


def test_neuanlage_behaelt_eingaben_bei_fehler(admin):
    r = admin.post("/admin/dienstleister/new", data=_daten())
    assert r.status_code == 200
    h = r.text
    assert "Bitte eine gültige Telefonnummer" in h          # Fehlermeldung sichtbar
    # ... und alles Getippte steht wieder im Formular
    for wert in ["Ayse", "Yilmaz", "ayse.neu@example.com", "keine nummer!",
                 "Musterweg 3", "45127", "Essen", "Ruhrgebiet", "Nur Wochenende",
                 "Freelancer", "25,00", "60,00", "https://ayse.example",
                 "Über Melissa gekommen"]:
        assert wert in h, f"Eingabe ging verloren: {wert}"
    assert 'value="8" selected' in h or '<option value="8" selected>' in h
    # Formular zeigt weiter auf „neu" (kein Bearbeiten-Ziel, kein Löschen-Knopf)
    assert 'action="/admin/dienstleister/new"' in h
    assert "dl_delete_form" not in h
    assert "Neuer Dienstleister" in h
    # nichts wurde gespeichert
    from database import SessionLocal
    s = SessionLocal()
    try:
        assert s.query(Dienstleister).filter_by(email="ayse.neu@example.com").first() is None
    finally:
        s.close()


def test_neuanlage_behaelt_eingaben_bei_doppelter_email(admin):
    vorhanden = reload(Dienstleister, make_dienstleister())
    r = admin.post("/admin/dienstleister/new",
                   data=_daten(email=vorhanden.email, telefon="0201 12345"))
    assert r.status_code == 200
    assert "E-Mail bereits vorhanden" in r.text
    assert "Musterweg 3" in r.text and "Ayse" in r.text


def test_bearbeiten_behaelt_eingaben_bei_fehler(admin):
    did = make_dienstleister(vorname="Alt", nachname="Wert", stadt="Bochum")
    d = reload(Dienstleister, did)
    r = admin.post(f"/admin/dienstleister/{did}/edit",
                   data=_daten(email=d.email, telefon="0201 12345",
                               stadt="Neustadt", plz="4512"))   # nur die PLZ ist ungültig
    assert r.status_code == 200
    assert "PLZ muss aus genau 5 Ziffern" in r.text
    assert "Neustadt" in r.text and "Bochum" not in r.text   # Eingabe, nicht alter Stand
    # Bearbeiten-Kontext bleibt erhalten (Ziel + Löschen-Knopf)
    assert f'action="/admin/dienstleister/{did}/edit"' in r.text
    assert "dl_delete_form" in r.text
    assert reload(Dienstleister, did).stadt == "Bochum"      # nichts gespeichert


def test_kunde_neuanlage_behaelt_eingaben_bei_fehler(admin):
    """Gleiches Muster im CRM: Firma vergessen → alle anderen Angaben bleiben stehen."""
    r = admin.post("/admin/crm/new", data={
        "firma": "", "ansprechpartner": "Frau Muster", "telefon": "0201 999",
        "email": "kontakt@firma.example", "rechnung_email": "rechnung@firma.example",
        "strasse": "Werksallee 5", "plz": "45127", "ort": "Essen",
        "website": "https://firma.example", "branche": "Industrie",
        "marke": "Knallfrosch", "pipeline_status": "gebucht",
        "tags": "Ferienprogramm, wiederkehrend",
        "notizen": "Zahlt immer pünktlich", "kommunikationsstil": "kurze Mails",
        "besonderheiten": "Parkplatz schwierig",
        "bevorzugte_eventarten": "Sommerfeste", "typische_budgets": "800–1200 €",
        "kap_name": "Peter Plan", "kap_telefon": "0151 222", "kap_email": "plan@firma.example"})
    assert r.status_code == 200
    h = r.text
    assert "Firma / Name ist erforderlich" in h
    for wert in ["Frau Muster", "0201 999", "kontakt@firma.example", "rechnung@firma.example",
                 "Werksallee 5", "45127", "Essen", "https://firma.example", "Industrie",
                 "Ferienprogramm, wiederkehrend", "Zahlt immer pünktlich", "kurze Mails",
                 "Parkplatz schwierig", "Sommerfeste", "800–1200 €", "Peter Plan"]:
        assert wert in h, f"Eingabe ging verloren: {wert}"
    # Auswahlfelder behalten ihren Stand, Formular zeigt weiter auf „neu"
    assert '<option value="Knallfrosch" selected>' in h
    assert 'action="/admin/crm/new"' in h and "Neuen Kunden anlegen" in h


def test_kunde_bearbeiten_behaelt_eingaben_bei_fehler(admin):
    from models import Kunde
    from database import SessionLocal
    s = SessionLocal()
    try:
        k = Kunde(firma="Alte Firma GmbH", ort="Bochum")
        s.add(k); s.commit(); kid = k.id
    finally:
        s.close()
    r = admin.post(f"/admin/crm/{kid}/edit",
                   data={"firma": "", "ort": "Neustadt", "ansprechpartner": "Neu Person"})
    assert r.status_code == 200
    assert "Firma / Name ist erforderlich" in r.text
    assert "Neustadt" in r.text and "Neu Person" in r.text
    assert f'action="/admin/crm/{kid}/edit"' in r.text   # Bearbeiten-Kontext bleibt
    assert reload(Kunde, kid).ort == "Bochum"            # nichts gespeichert


def test_event_formular_behaelt_eingaben_bei_fehler(admin):
    """Event-Formular hatte den Echo-Schutz bereits – hier als Regression abgesichert."""
    r = admin.post("/admin/events/new", data={
        "datum": "2026-09-01", "startzeit": "14:00", "endzeit": "18:00",
        "anlass": "Firmenfest Nordwind", "veranstaltungsort": "Markt 1, 45127 Essen",
        "kunde_firma": "Nordwind GmbH", "kunde_kontakt": "Frau Nord",
        "kunde_telefon": "keine nummer!", "produkte": ["Zaubershow"],
        "hinweise": "Bitte Bühne prüfen"})
    assert r.status_code == 200
    assert "Bitte eine gültige Telefonnummer" in r.text
    for wert in ["Firmenfest Nordwind", "Nordwind GmbH", "Frau Nord", "keine nummer!",
                 "Bitte Bühne prüfen"]:
        assert wert in r.text, f"Eingabe ging verloren: {wert}"


def test_gueltige_eingabe_speichert_weiterhin(admin):
    r = admin.post("/admin/dienstleister/new",
                   data=_daten(email="ayse.ok@example.com", telefon="0201 12345"),
                   follow_redirects=False)
    assert r.status_code == 303
    from database import SessionLocal
    s = SessionLocal()
    try:
        neu = s.query(Dienstleister).filter_by(email="ayse.ok@example.com").first()
        assert neu and neu.stadt == "Essen" and neu.lieferantenbewertung == 8
        assert neu.stundensatz_teamer == 25.0 and neu.stundensatz_kuenstler == 60.0
        assert neu.logistiker and neu.fuehrerschein and neu.aktiv
    finally:
        s.close()
