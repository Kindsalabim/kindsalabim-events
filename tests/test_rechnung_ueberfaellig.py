"""Überfällige Rechnungen: Zahlungsziel 14 Werktage; unbezahlt danach → einmalige
Glocken-/Mail-Benachrichtigung (Cron) + Badge in der Buchhaltung."""
from datetime import date

from choices import werktage_spaeter, rechnung_faellig_am, rechnung_ueberfaellig
from models import Rechnung, Benachrichtigung
from routes.cron import _run_ueberfaellige_rechnungen


def test_werktage_ueberspringen_wochenenden():
    # Mo 06.07.2026 + 14 Werktage = Fr 24.07.2026 (2 Wochenenden übersprungen)
    assert werktage_spaeter(date(2026, 7, 6), 14) == date(2026, 7, 24)


def test_faelligkeit_und_ueberfaellig_logik():
    r = Rechnung(datum=date(2026, 7, 6), bezahlt=False)
    assert rechnung_faellig_am(r) == date(2026, 7, 24)
    assert not rechnung_ueberfaellig(r, heute=date(2026, 7, 24))   # am Fälligkeitstag noch ok
    assert rechnung_ueberfaellig(r, heute=date(2026, 7, 25))
    r.bezahlt = True
    assert not rechnung_ueberfaellig(r, heute=date(2026, 8, 1))
    assert rechnung_faellig_am(Rechnung(datum=None)) is None


def test_cron_meldet_einmalig_und_setzt_flag(db):
    db.add(Rechnung(datum=date(2026, 1, 5), kunde="Säumig GmbH", rgnr="RE-UEB-1",
                    brutto=1190.0, bezahlt=False))
    db.add(Rechnung(datum=date(2026, 1, 5), kunde="Pünktlich AG", rgnr="RE-UEB-2",
                    brutto=500.0, bezahlt=True))
    db.commit()
    assert _run_ueberfaellige_rechnungen(db) >= 1
    r = db.query(Rechnung).filter(Rechnung.rgnr == "RE-UEB-1").one()
    db.refresh(r)
    assert r.ueberfaellig_erinnert is True
    meldungen = db.query(Benachrichtigung).filter(
        Benachrichtigung.titel.contains("RE-UEB-1")).count()
    assert meldungen == 1
    # Bezahlte Rechnung löst nichts aus
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.titel.contains("RE-UEB-2")).count() == 0
    # Zweiter Lauf: keine Wiederholung für dieselbe Rechnung
    _run_ueberfaellige_rechnungen(db)
    assert db.query(Benachrichtigung).filter(
        Benachrichtigung.titel.contains("RE-UEB-1")).count() == 1


def test_badge_in_buchhaltung(admin, db):
    db.add(Rechnung(datum=date(2026, 1, 7), kunde="Badge Test GmbH", rgnr="RE-UEB-3",
                    brutto=100.0, bezahlt=False))
    db.commit()
    h = admin.get("/admin/buchhaltung?jahr=2026").text
    assert "überfällig" in h
