"""Event-Formular: Kundendaten (Adresse/Kontakt/Telefon/Mail) stehen als JSON bereit,
damit die Auswahl eines bekannten Kunden die Felder automatisch füllt (Client-seitig).
Getestet wird die Datenlieferung ans Formular – das Ausfüllen selbst macht JS."""
import json
import re

from database import SessionLocal
from models import Kunde


def _kunde(**kw):
    s = SessionLocal()
    try:
        k = Kunde(**kw)
        s.add(k); s.commit()
        return k.id
    finally:
        s.close()


def _kunden_daten(html):
    m = re.search(r'<script type="application/json" id="kunden-daten">\s*(.*?)\s*</script>',
                  html, re.S)
    assert m, "kunden-daten JSON-Block fehlt im Formular"
    return json.loads(m.group(1))


def test_neues_event_liefert_kundendaten(admin):
    _kunde(firma="Sparkasse Schwelm-Sprockhövel", ansprechpartner="Frau Klar",
           telefon="02336 123", email="info@sparkasse.de",
           strasse="Hauptstr. 5", plz="58332", ort="Schwelm")
    daten = _kunden_daten(admin.get("/admin/events/new").text)
    treffer = [k for k in daten if k["firma"] == "Sparkasse Schwelm-Sprockhövel"]
    assert treffer, "Kunde nicht in den Autofill-Daten"
    k = treffer[0]
    assert k["kontakt"] == "Frau Klar"
    assert k["telefon"] == "02336 123"
    assert k["email"] == "info@sparkasse.de"
    assert k["strasse"] == "Hauptstr. 5" and k["plz"] == "58332" and k["ort"] == "Schwelm"


def test_hinweis_und_skript_vorhanden(admin):
    _kunde(firma="Autofill Test GmbH")
    h = admin.get("/admin/events/new").text
    assert "werden automatisch übernommen" in h
    assert 'id="kunden-daten"' in h


def test_umlaute_und_anfuehrungszeichen_sauber_escaped(admin):
    # |tojson muss Sonderzeichen im Firmennamen sauber escapen, sonst bricht das JSON
    _kunde(firma='Kita "Sonnenschein" & Co. Größer')
    daten = _kunden_daten(admin.get("/admin/events/new").text)   # wirft, wenn JSON kaputt
    assert any(k["firma"] == 'Kita "Sonnenschein" & Co. Größer' for k in daten)
