"""AB hochladen → „Neues Event“ vorausgefüllt (Aykut 26.11.2026). Die Test-PDFs bilden
den Lexoffice-Aufbau der echten ABs nach (Zeilen wie PyMuPDF sie liest)."""
import fitz

from ab_vorfuellen import auslesen
from choices import PRODUKT_SPARTE
from routes.admin import PRODUKTE_LIST

KOPF = ["Knallfrosch | Malca & Akmanoglu GbR", "Charlottenweg 55", "45289 Essen", "Auftragsbestätigung",
        "Wir danken für Ihr Vertrauen und bestätigen folgende Leistungen:"]
ABSENDER = ["Knallfrosch | Malca & Akmanoglu GbR , Charlottenweg 55, 45289", "Essen"]


def _pdf(zeilen):
    # Die Standardschrift kann keinen Gedankenstrich (wird „·“) → in den Testzeilen „-“;
    # echte Lexoffice-ABs mit „–“ sind beim Bau gegen vier echte ABs geprüft.
    zeilen = [z.replace("–", "-") for z in zeilen]
    doc = fitz.open()
    seite = doc.new_page(height=60 + 14 * len(zeilen))
    for i, z in enumerate(zeilen):
        seite.insert_text((40, 40 + 14 * i), z, fontsize=9)
    return doc.tobytes()


AB_MEHRTAGIG = _pdf(KOPF + [
    "Kinderbetreuung, Management Konferenz, 13. - 14.11.2026",
    "13.11.2026, 13:45 - 18:00 Uhr / Maritim Hotel Köln",
    "14.11.2026, 08:15 - 13:00 Uhr / Maritim Hotel Köln",
    "Auftragsnr.:", "Kundennr.:", "Datum:", "AB0473", "10001", "29.09.2026",
    "Pos.", "Bezeichnung",
    "1", "Spieleland U3", "Bällebad, Kriechtunnel", "2", "Stück", "175,00", "350,00",
    "2", "Kinderschminken", "inkl. 1 Kinderschminkerin", "10", "Stunde", "92,50", "925,00",
    "3", "Spieleangebote / Kongress", "XXL-Jenga", "2", "Stück", "159,00", "318,00",
    "4", "2 x 3 Knallfrosch - Teamer / Tagessatz (6 Stunden)", "Zu Pos.: 1-4", "6", "Tagessatz",
    "227,50", "1.365,00",
    "5", "Fahrtkostenpauschale", "15€ p.P", "4", "Stück", "15,00", "60,00",
] + ABSENDER + ["inspiria event service GmbH", "Weimarer Straße 4/10", "1180 Wien", "Seite 1/2"])


def _ohne_zahlen(tage):
    return [{k: t[k] for k in ("datum", "start", "ende")} for t in tage]


def _lesen(pdf):
    return auslesen(pdf, PRODUKTE_LIST, set(PRODUKT_SPARTE))


def test_liest_alle_felder():
    r = _lesen(AB_MEHRTAGIG)
    assert r["marke"] == "Knallfrosch" and r["ab_nummer"] == "AB0473"
    assert r["kunde_firma"] == "inspiria event service GmbH"
    assert r["kunde_adresse"] == "Weimarer Straße 4/10, 1180 Wien"
    assert _ohne_zahlen(r["tage"]) == [{"datum": "2026-11-13", "start": "13:45", "ende": "18:00"},
                         {"datum": "2026-11-14", "start": "08:15", "ende": "13:00"}]
    assert r["produkte"] == ["U3 Spieleland", "Kinderschminken"]
    assert r["anzahl_teamer"] == 3          # „2 x 3 … Teamer“ = 3 pro Tag
    assert r["anzahl_kuenstler"] == 1       # Kinderschminken
    assert any("Spieleangebote / Kongress" in h for h in r["hinweise"])


def test_kurzformen_datum_und_uhrzeit():
    r = _lesen(_pdf(KOPF + ["Kinderanimation, Fertighauswelt, 26./27.09.26, je 12-17 Uhr",
                            "Auftragsnr.:", "Datum:", "AB0467", "23.07.2026", "Pos."]))
    assert [t["datum"] for t in r["tage"]] == ["2026-09-26", "2026-09-27"]
    assert r["tage"][0]["start"] == "12:00" and r["tage"][0]["ende"] == "17:00"


def test_monatsname_ohne_jahr_und_teamer_ohne_zahl():
    r = _lesen(_pdf(KOPF + ["Kinderanimation Nikolausshopping 2026", "05.Dezember von 13-17 Uhr",
                            "06.Dezember von 12-17 Uhr", "Pos.",
                            "1", "Kindsalabim - Teamer Tagessatz (4 Stunden)", "1", "Tagessatz",
                            "150,00", "150,00", "Auftragsnr.:", "Datum:", "AB0642", "12.11.2026"]))
    assert _ohne_zahlen(r["tage"]) == [{"datum": "2026-12-05", "start": "13:00", "ende": "17:00"},
                         {"datum": "2026-12-06", "start": "12:00", "ende": "17:00"}]
    assert r["anzahl_teamer"] == 1


def test_upload_fuellt_formular(admin):
    r = admin.post("/admin/events/new/aus-ab",
                   files={"ab": ("AB0473.pdf", AB_MEHRTAGIG, "application/pdf")})
    h = r.text
    assert r.status_code == 200
    assert 'value="inspiria event service GmbH"' in h
    assert 'value="Weimarer Straße 4/10, 1180 Wien"' in h
    assert 'name="datum" required value="2026-11-13"' in h
    assert 'name="extra_datum" value="2026-11-14"' in h
    assert "Vorausgefüllt aus AB0473" in h
    from database import SessionLocal
    from models import Event
    s = SessionLocal()
    assert not s.query(Event).filter(Event.kunde_firma == "inspiria event service GmbH").count()
    s.close()


def test_kaputte_datei_meldet_sich(admin):
    r = admin.post("/admin/events/new/aus-ab", files={"ab": ("x.pdf", b"kein pdf", "application/pdf")})
    assert "ließ sich nicht auslesen" in r.text


def test_formular_hat_upload_nur_beim_anlegen(admin):
    assert 'action="/admin/events/new/aus-ab"' in admin.get("/admin/events/new").text


def test_glitzertattoos_braucht_einen_teamer():
    # Aykut 26.11.2026: Glitzertattoos macht ein Teamer, kein Künstler
    r = _lesen(_pdf(KOPF + ["Kinderanimation, 26.09.2026, 12-17 Uhr", "Pos.",
                            "1", "Kinderschminken", "inkl. 1 Kinderschminkerin", "10", "Stunde", "92,50", "925,00",
                            "2", "Glitzertattoos", "inkl. 1 Tattoo-Künstlerin", "10", "Stunde", "82,50", "825,00"]))
    assert r["anzahl_teamer"] == 1 and r["anzahl_kuenstler"] == 1


def test_anlass_ist_das_zweite_stueck():
    # Aykut 26.11.2026: „Kinderanimation, Weihnachtsfeier, 12.12.2026, 16:30 Uhr“
    r = _lesen(_pdf(KOPF + ["Kinderanimation, Weihnachtsfeier, 12.12.2026, 16:30 Uhr", "Pos."]))
    assert r["anlass"] == "Weihnachtsfeier"
    r = _lesen(_pdf(KOPF + ["Kinderanimation Nikolausshopping 2026", "05.Dezember von 13-17 Uhr", "Pos."]))
    assert r["anlass"] == "Kinderanimation Nikolausshopping 2026"


AB_ZWEI_TAGE = _pdf(KOPF + [
    "Kinderanimation, Weihnachtsmarkt", "12.12.2026 von 12-17 Uhr", "13.12.2026 von 11-16 Uhr",
    "Auftragsnr.:", "Datum:", "AB0700", "01.11.2026", "Pos.",
    "12.12.2026",
    "1", "Zaubershow", "60 Minuten", "1", "Stück", "350,00", "350,00",
    "2", "Glitzertattoos", "inkl. Material", "5", "Stunde", "75,00", "375,00",
    "3", "Bastelaktion", "Material", "1", "Stück", "100,00", "100,00",
    "4", "1 Kindsalabim-Teamer / Tagessatz", "zu Pos.: 3", "1", "Stück", "150,00", "150,00",
    "13.12.2026",
    "5", "Glitzertattoos", "inkl. Material", "5", "Stunde", "75,00", "375,00",
    "6", "Spieleland", "Material", "1", "Stück", "150,00", "150,00",
    "7", "1 Kindsalabim-Teamer / Tagessatz", "zu Pos.: 6", "1", "Stück", "150,00", "150,00",
    "8", "Bastelaktion", "Material", "1", "Stück", "100,00", "100,00",
    "9", "1 Kindsalabim-Teamer / Tagessatz", "zu Pos.: 8", "1", "Stück", "150,00", "150,00",
])


def test_teamer_und_kuenstler_je_tag():
    # Aykut 26.11.2026: Tag 1 = Zaubershow, Glitzer, Bastel+Teamer → 2 Teamer, 1 Künstler;
    # Tag 2 = Glitzer, Spieleland+Teamer, Bastel+Teamer → 3 Teamer, 0 Künstler
    r = _lesen(AB_ZWEI_TAGE)
    assert [(t["datum"], t["teamer"], t["kuenstler"]) for t in r["tage"]] == [
        ("2026-12-12", 2, 1), ("2026-12-13", 3, 0)]
    assert r["anzahl_teamer"] == 2 and r["anzahl_kuenstler"] == 1


def test_anlegen_uebernimmt_zahlen_je_tag(admin):
    h = admin.post("/admin/events/new/aus-ab",
                   files={"ab": ("AB0700.pdf", AB_ZWEI_TAGE, "application/pdf")}).text
    assert 'name="extra_teamer" min="0" value="3"' in h
    r = admin.post("/admin/events/new", data={
        "anlass": "Weihnachtsmarkt", "datum": "2026-12-12", "startzeit": "12:00", "endzeit": "17:00",
        "kunde_firma": "Tag-Test GmbH", "kunde_adresse": "Markt 1, 45127 Essen",
        "produkte": ["Zaubershow", "Glitzertattoos"], "marke": "Kindsalabim", "status": "Gebucht",
        "anzahl_teamer": "2", "anzahl_kuenstler": "1",
        "extra_datum": ["2026-12-13", "2026-12-14"], "extra_startzeit": ["11:00", ""],
        "extra_endzeit": ["16:00", ""], "extra_teamer": ["3", ""], "extra_kuenstler": ["0", ""]},
        follow_redirects=False)
    assert r.status_code == 303
    from database import SessionLocal
    from models import Event
    s = SessionLocal()
    evs = s.query(Event).filter(Event.kunde_firma == "Tag-Test GmbH").order_by(Event.datum).all()
    assert [(e.anzahl_teamer, e.anzahl_kuenstler) for e in evs] == [(2, 1), (3, 0), (2, 1)]
    s.close()
