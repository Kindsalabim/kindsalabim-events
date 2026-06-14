"""Demo-Daten für die Test-/Demo-Umgebung (nur aktiv bei DEMO_MODE).

Befüllt eine frische DB mit fiktiven, aber realistischen Beispieldaten, damit
Tester jedes Feature einmal sehen: Events (beide Marken, mit/ohne Material,
verschiedene Status inkl. Abgesagt), Dienstleister (mit/ohne Führerschein,
Logistiker, alle Künstler-Sparten), offene & beantwortete Anfragen,
Reservierungen, Buchhaltung. Idempotent: `seed_demo_data(reset=True)` setzt
alles auf den Ausgangsstand zurück.
"""
from datetime import date, datetime, timedelta

from database import SessionLocal
from models import (Event, Dienstleister, Verfuegbarkeitsanfrage, Reservierung,
                    Rechnung, Admin, Kunde, KundeAktivitaet, KundeWiedervorlage,
                    EventDatei, DienstleisterSperrzeit)
from auth import hash_password

DEMO_ADMIN_EMAIL = "demo@kindsalabim.de"
DEMO_ADMIN_PW    = "demo1234"
DEMO_TEAMER_EMAIL = "max.teamer@demo.de"   # Ein-Klick-Portal-Login zielt auf diesen DL


def _today():
    return date.today()


def _wipe(db):
    """Leert alle inhaltlichen Tabellen (SQLite in der Demo → keine FK-Probleme)."""
    for model in (Verfuegbarkeitsanfrage, EventDatei, DienstleisterSperrzeit,
                  Reservierung, Rechnung, KundeAktivitaet, KundeWiedervorlage,
                  Event, Dienstleister, Kunde, Admin):
        db.query(model).delete()
    db.commit()


def seed_demo_data(reset: bool = False):
    """Seedt die Demo-Daten. Bei reset=True wird vorher alles geleert."""
    db = SessionLocal()
    try:
        if reset:
            _wipe(db)
        elif db.query(Event).count() > 0:
            return  # bereits befüllt – nichts tun

        t = _today()

        # ── Admin (Login: demo@kindsalabim.de / demo1234) ──
        db.add(Admin(email=DEMO_ADMIN_EMAIL, name="Demo Admin",
                     password_hash=hash_password(DEMO_ADMIN_PW), aktiv=True,
                     erstellt_am=datetime.now().isoformat(timespec="seconds")))

        # ── Dienstleister ──
        dls = [
            Dienstleister(vorname="Max", nachname="Mustermann", email=DEMO_TEAMER_EMAIL,
                          telefon="0201 1234567", strasse="Kettwiger Str. 5, 45127 Essen",
                          stadt="Essen", rolle="Teamer", erfahrungspunkte=40, qualitaet=4,
                          mobilitaet="Auto", fuehrerschein=True, logistiker=True, aktiv=True,
                          dsgvo_unterzeichnet=True, gebiet="Ruhrgebiet", vertragstyp="Freelancer",
                          stundensatz_teamer=18.0, onboarding_abgeschlossen=True),
            Dienstleister(vorname="Lisa", nachname="Klein", email="lisa.klein@demo.de",
                          telefon="0231 2345678", strasse="Markt 3, 44137 Dortmund",
                          stadt="Dortmund", rolle="Teamer", erfahrungspunkte=12, qualitaet=3,
                          mobilitaet="ÖPNV", fuehrerschein=False, logistiker=False, aktiv=True,
                          dsgvo_unterzeichnet=False, gebiet="Ruhrgebiet"),
            Dienstleister(vorname="Sara", nachname="Schmidt", email="sara.schmidt@demo.de",
                          telefon="0221 3456789", strasse="Hohe Str. 10, 50667 Köln",
                          stadt="Köln", rolle="Künstler", kuenstler_sparte="Kinderschminke",
                          erfahrungspunkte=55, qualitaet=5, mobilitaet="Auto", fuehrerschein=True,
                          aktiv=True, dsgvo_unterzeichnet=True, gebiet="Rheinland",
                          stundensatz_kuenstler=35.0),
            Dienstleister(vorname="Ben", nachname="Bauer", email="ben.bauer@demo.de",
                          telefon="0211 4567890", strasse="Königsallee 1, 40212 Düsseldorf",
                          stadt="Düsseldorf", rolle="Künstler", kuenstler_sparte="Ballonkünstler",
                          erfahrungspunkte=30, qualitaet=4, mobilitaet="Auto", fuehrerschein=True,
                          aktiv=True, dsgvo_unterzeichnet=True, gebiet="Rheinland"),
            Dienstleister(vorname="Cora", nachname="Conrad", email="cora.conrad@demo.de",
                          telefon="0201 5678901", strasse="Rüttenscheider Str. 2, 45130 Essen",
                          stadt="Essen", rolle="Künstler", kuenstler_sparte="Schminke + Ballon",
                          erfahrungspunkte=48, qualitaet=5, mobilitaet="Beides", fuehrerschein=True,
                          logistiker=True, aktiv=True, dsgvo_unterzeichnet=True, gebiet="Ruhrgebiet"),
            Dienstleister(vorname="Stefan", nachname="Stein", email="stefan.stein@demo.de",
                          telefon="069 6789012", strasse="Zeil 20, 60313 Frankfurt",
                          stadt="Frankfurt", rolle="Künstler", kuenstler_sparte="Sonstiges",
                          erfahrungspunkte=8, qualitaet=3, mobilitaet="Auto", fuehrerschein=True,
                          aktiv=True, dsgvo_unterzeichnet=False, gebiet="Hessen",
                          notizen="Stelzenläufer – selten gebucht"),
        ]
        for d in dls:
            db.add(d)
        db.flush()  # IDs verfügbar
        max_dl, lisa, sara, ben, cora, stefan = dls

        # ── Events ──
        ev1 = Event(anlass="Sommerfest", datum=t + timedelta(days=10),
                    startzeit="10:00", endzeit="16:00",
                    veranstaltungsort="Burgplatz 1, 45127 Essen",
                    kunde_firma="Stadtwerke Essen", kunde_kontakt="Frau Wagner",
                    kunde_telefon="0201 1110000", kunde_email="wagner@demo.de",
                    produkte="Kinderschminken, Ballonmodellage", anzahl_teamer=2,
                    anzahl_kuenstler=1, material_mitnahme=True, material_bestellt=False,
                    status="Dienstleister angefragt", marke="Kindsalabim",
                    checklist_token="demo-checklist-token", hinweise="Bitte pünktlich aufbauen.")
        ev2 = Event(anlass="Firmenfeier", datum=t + timedelta(days=20),
                    startzeit="14:00", endzeit="18:00",
                    veranstaltungsort="Rheinpark 5, 40210 Düsseldorf",
                    kunde_firma="Knallfrosch Stammkunde GmbH", kunde_kontakt="Herr Becker",
                    kunde_telefon="0211 2220000", kunde_email="becker@demo.de",
                    produkte="Zaubershow", anzahl_teamer=1, anzahl_kuenstler=1,
                    material_mitnahme=False, status="Planung fertig", marke="Knallfrosch",
                    cl_eingereicht_am=datetime.now().strftime("%d.%m.%Y %H:%M"),
                    cl_ansprechpartner_name="Herr Becker", cl_aufbauort="Indoor",
                    cl_verpflegung="Ja", cl_teamkleidung="Ja")
        ev3 = Event(anlass="Kindergeburtstag", datum=t + timedelta(days=3),
                    startzeit="15:00", endzeit="18:00",
                    veranstaltungsort="Lindenweg 7, 50667 Köln",
                    kunde_firma="Familie Hoffmann", kunde_kontakt="Frau Hoffmann",
                    kunde_telefon="0221 3330000", kunde_email="hoffmann@demo.de",
                    produkte="Kinderschminken", anzahl_teamer=1, anzahl_kuenstler=1,
                    material_mitnahme=False, status="Briefing gesendet", marke="Kindsalabim")
        ev4 = Event(anlass="Stadtfest", datum=t - timedelta(days=14),
                    startzeit="11:00", endzeit="17:00",
                    veranstaltungsort="Marktplatz, 44137 Dortmund",
                    kunde_firma="Stadt Dortmund", kunde_kontakt="Herr Schulz",
                    kunde_telefon="0231 4440000", kunde_email="schulz@demo.de",
                    produkte="Ballonmodellage, Kinderschminken", anzahl_teamer=2,
                    anzahl_kuenstler=2, material_mitnahme=True, material_bestellt=True,
                    status="Abgeschlossen", marke="Kindsalabim", rechnung_gestellt=True,
                    bericht_eingereicht_am=(t - timedelta(days=13)).strftime("%d.%m.%Y"),
                    bericht_anzahl_kinder=80, bericht_verlauf="Alles reibungslos, tolle Stimmung.")
        ev5 = Event(anlass="Vereinsfest", datum=t + timedelta(days=30),
                    startzeit="12:00", endzeit="16:00",
                    veranstaltungsort="Sportplatz, 60311 Frankfurt",
                    kunde_firma="TV Frankfurt e.V.", kunde_kontakt="Herr Wolf",
                    kunde_telefon="069 5550000", kunde_email="wolf@demo.de",
                    produkte="Zaubershow", anzahl_teamer=1, anzahl_kuenstler=1,
                    material_mitnahme=False, status="Abgesagt", marke="Knallfrosch")
        for e in (ev1, ev2, ev3, ev4, ev5):
            db.add(e)
        db.flush()
        ev3.teamleiter_id = max_dl.id  # Teamleiter-Beispiel

        # ── Verfügbarkeitsanfragen (Mix aus Zusage / offen) ──
        jetzt = datetime.now().isoformat(timespec="seconds")
        anfragen = [
            # Event 1: Max zugesagt, Lisa offen, Sara (Künstlerin) zugesagt, Ben offen
            Verfuegbarkeitsanfrage(event_id=ev1.id, dienstleister_id=max_dl.id, rolle_anfrage="Teamer",
                                   status="Ja", erstellt_am=jetzt, frist_datum=t + timedelta(days=5)),
            Verfuegbarkeitsanfrage(event_id=ev1.id, dienstleister_id=lisa.id, rolle_anfrage="Teamer",
                                   status="Ausstehend", erstellt_am=jetzt, frist_datum=t + timedelta(days=5)),
            Verfuegbarkeitsanfrage(event_id=ev1.id, dienstleister_id=sara.id, rolle_anfrage="Künstler",
                                   status="Ja", erstellt_am=jetzt, frist_datum=t + timedelta(days=5)),
            Verfuegbarkeitsanfrage(event_id=ev1.id, dienstleister_id=ben.id, rolle_anfrage="Künstler",
                                   status="Ausstehend", erstellt_am=jetzt, frist_datum=t + timedelta(days=5)),
            # Event 2 (Knallfrosch): offene Anfrage an Max -> im Portal beantwortbar
            Verfuegbarkeitsanfrage(event_id=ev2.id, dienstleister_id=max_dl.id, rolle_anfrage="Teamer",
                                   status="Ausstehend", erstellt_am=jetzt, frist_datum=t + timedelta(days=8)),
            Verfuegbarkeitsanfrage(event_id=ev2.id, dienstleister_id=ben.id, rolle_anfrage="Künstler",
                                   status="Ja", erstellt_am=jetzt, frist_datum=t + timedelta(days=8)),
            # Event 3: Max ist Teamleiter (zugesagt)
            Verfuegbarkeitsanfrage(event_id=ev3.id, dienstleister_id=max_dl.id, rolle_anfrage="Teamer",
                                   status="Ja", erstellt_am=jetzt, frist_datum=t),
            Verfuegbarkeitsanfrage(event_id=ev3.id, dienstleister_id=sara.id, rolle_anfrage="Künstler",
                                   status="Ja", erstellt_am=jetzt, frist_datum=t),
        ]
        for a in anfragen:
            db.add(a)

        # ── Reservierungen (eine aktiv, eine mit abgelaufener Frist) ──
        db.add(Reservierung(datum=t + timedelta(days=25), anlass="Schulfest",
                            veranstaltungsort="50667 Köln", kunde_firma="Grundschule Nord",
                            kunde_kontakt="Frau Meier", kunde_telefon="0221 6660000",
                            marke="Kindsalabim", frist=t + timedelta(days=5),
                            notiz="Angebot 1.200 € verschickt", erstellt_am=jetzt))
        db.add(Reservierung(datum=t + timedelta(days=40), anlass="Jubiläum",
                            veranstaltungsort="60311 Frankfurt", kunde_firma="Turnverein 1900",
                            kunde_kontakt="Herr Krause", marke="Knallfrosch",
                            frist=t - timedelta(days=2), notiz="Noch keine Rückmeldung",
                            erstellt_am=jetzt))

        # ── Buchhaltung ──
        db.add(Rechnung(datum=t - timedelta(days=10), kunde="Stadt Dortmund", rgnr="RE-2026-001",
                        brutto=1450.0, bezahlt=True, steuer_erledigt=True,
                        personalkosten=600.0, materialkosten=120.0))
        db.add(Rechnung(datum=t - timedelta(days=3), kunde="Stadtwerke Essen", rgnr="RE-2026-002",
                        brutto=980.0, bezahlt=False, personalkosten=400.0, materialkosten=80.0))
        db.add(Rechnung(datum=t - timedelta(days=1), kunde="Knallfrosch Stammkunde GmbH",
                        rgnr="RE-2026-003", brutto=2100.0, bezahlt=True, steuer_erledigt=False,
                        personalkosten=900.0, materialkosten=200.0))

        db.commit()

        # CRM-Kundenprofile aus den Events erzeugen (wie im normalen Startlauf)
        try:
            from main import migrate_kunden
            migrate_kunden()
        except Exception as e:
            print(f"Demo: migrate_kunden übersprungen ({e})")
    finally:
        db.close()
