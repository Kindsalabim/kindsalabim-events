# -*- coding: utf-8 -*-
"""Fremdleistungen: geschätzte und tatsächliche Honorare je Einsatz.

Das Problem, das dieses Modul löst: Die Rechnungen der Dienstleister treffen
erst ein, wenn dem Kunden längst geschrieben wurde. Ohne Zwischenlösung stehen
in der Buchhaltung wochenlang zu niedrige Kosten – und die Differenz fällt
niemandem auf.

Der Weg:
1. Bei jeder Zusage entsteht eine Honorarzeile mit einer **Schätzung**.
2. Die Zeile bleibt ein offener Posten, bis die Rechnung da ist; dann wird der
   Ist-Wert eingetragen und die Fremdleistungen der Kundenrechnung ziehen nach.
3. Ein **Lernfaktor** aus den bereits abgerechneten Einsätzen korrigiert den
   systematischen Versatz der Schätzung (siehe `lernfaktor`).

Warum die reine Bestellsumme zu niedrig ist: Die Auto-Bestellung beziffert nur
die Aktionszeit; Auf-/Abbau, Fahrzeit und Nebenkosten stehen dort bewusst ohne
Zahl („nach tatsächlichem Aufwand"). Genau diese Posten schätzt `schaetzung`
zusätzlich mit ab.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func

from models import EventHonorar, Verfuegbarkeitsanfrage

# Zuschläge auf die reine Aktionszeit (mit Aykut abgestimmt, 03.09.2026)
AUFBAU_STUNDEN = 1.0     # Auf- und Abbau, früheres Eintreffen
UMWEG_FAKTOR = 1.3       # Luftlinie → gefahrene Strecke
TEMPO_KMH = 50.0         # Mischung aus Stadt und Landstraße
FAHRZEIT_SATZ = 10.0     # €/Std. Nettofahrzeit (wie in der Bestellung)

# Lernfaktor: erst ab genug abgerechneten Einsätzen und nur in vernünftigen Grenzen
LERN_MINDESTZAHL = 10
LERN_MAX = 1.6
LERN_MIN = 0.8


def fahrzeit_stunden(ev, d):
    """Geschätzte Fahrzeit hin und zurück in Stunden (0.0, wenn unbekannt).
    Luftlinie aus den PLZ-Koordinaten × Umwegfaktor ÷ Durchschnittstempo."""
    try:
        from distance import get_coords_for_address, get_coords_for_dienstleister, haversine
        ziel = get_coords_for_address(ev.veranstaltungsort or "")
        start = get_coords_for_dienstleister(d)
        if not ziel or not start:
            return 0.0
        km = haversine(start[0], start[1], ziel[0], ziel[1]) * UMWEG_FAKTOR
        std = 2 * km / TEMPO_KMH
        return round(std * 4) / 4            # auf Viertelstunden
    except Exception:
        return 0.0


def schaetzung(a, ev, d, faktor: float = 1.0):
    """Erwartete Honorarkosten eines Einsatzes in Euro (None = nicht berechenbar).

    Künstler mit Pauschalbudget: Budget + Nebenkosten-Anteil über den Faktor.
    Sonst: (Aktionszeit + Auf-/Abbau) × Stundensatz + Fahrzeit × Fahrzeitsatz.
    """
    from bestellung import _stunden
    logistik = bool(getattr(a, "als_logistiker", False))
    if a.rolle_anfrage == "Künstler" and a.budget:
        basis = float(a.budget)             # Pauschale inkl. Fahrt (siehe Bestellung)
    else:
        satz = d.stundensatz_kuenstler if a.rolle_anfrage == "Künstler" else d.stundensatz_teamer
        h = _stunden(ev)
        if not satz or not h:
            return None
        basis = (h + AUFBAU_STUNDEN) * satz + fahrzeit_stunden(ev, d) * FAHRZEIT_SATZ
    if logistik:
        # Gesondert beauftragte Transportleistung: Abholung + Rücklieferung
        basis += 2 * FAHRZEIT_SATZ
    return round(basis * faktor, 2)


def lernfaktor(db) -> float:
    """Wie weit lagen die echten Rechnungen über den Schätzungen? (1.0 = wie geschätzt)

    Nur aus Zeilen, bei denen beides bekannt ist. Unter `LERN_MINDESTZAHL`
    Einsätzen bleibt es bei 1.0 – lieber keine Korrektur als eine aus drei
    Zufallswerten. Gedeckelt, damit ein Ausreißer die Schätzung nicht entgleisen
    lässt."""
    rows = db.query(EventHonorar.geschaetzt, EventHonorar.tatsaechlich).filter(
        EventHonorar.tatsaechlich != None,      # noqa: E711
        EventHonorar.geschaetzt != None,        # noqa: E711
        EventHonorar.geschaetzt > 0).all()
    if len(rows) < LERN_MINDESTZAHL:
        return 1.0
    soll = sum(g for g, _ in rows)
    ist = sum(t for _, t in rows)
    if soll <= 0:
        return 1.0
    return round(min(LERN_MAX, max(LERN_MIN, ist / soll)), 3)


def honorar_anlegen(db, a) -> None:
    """Honorarzeile zu einer Zusage anlegen (idempotent). Ohne hinterlegten Satz
    entsteht die Zeile trotzdem – nur ohne Schätzung, damit die erwartete
    Rechnung nicht unter den Tisch fällt."""
    if not a or not a.event_id or not a.dienstleister_id:
        return
    vorhanden = db.query(EventHonorar).filter(
        EventHonorar.event_id == a.event_id,
        EventHonorar.dienstleister_id == a.dienstleister_id).first()
    if vorhanden:
        return
    ev, d = a.event, a.dienstleister
    if not ev or not d:
        return
    db.add(EventHonorar(
        event_id=a.event_id, dienstleister_id=a.dienstleister_id,
        geschaetzt=schaetzung(a, ev, d, lernfaktor(db)),
        erstellt_am=datetime.now().isoformat(timespec="seconds")))


def honorar_entfernen(db, a) -> None:
    """Zeile wieder löschen, wenn jemand doch absagt – aber nur, solange keine
    echte Rechnung erfasst ist (sonst wäre eine bezahlte Leistung weg)."""
    if not a or not a.event_id or not a.dienstleister_id:
        return
    db.query(EventHonorar).filter(
        EventHonorar.event_id == a.event_id,
        EventHonorar.dienstleister_id == a.dienstleister_id,
        EventHonorar.tatsaechlich == None).delete(synchronize_session=False)   # noqa: E711


def summe(db, event_id: int) -> float:
    """Fremdleistungen eines Events: Ist-Werte, wo vorhanden, sonst Schätzungen."""
    rows = db.query(EventHonorar).filter(EventHonorar.event_id == event_id).all()
    return round(sum(h.betrag for h in rows), 2)


def offene_anzahl(db, event_id: int) -> int:
    return db.query(func.count(EventHonorar.id)).filter(
        EventHonorar.event_id == event_id,
        EventHonorar.tatsaechlich == None).scalar() or 0        # noqa: E711


BACKFILL_TAGE = 60


def backfill_offene(db, tage: int = BACKFILL_TAGE) -> int:
    """Honorarzeilen für bereits bestehende Zusagen anlegen.

    Fenster: alle Events ab `tage` Tagen in der Vergangenheit. Nur die Zukunft
    zu nehmen wäre zu eng – gerade bei den zuletzt gelaufenen Events ist die
    Kundenrechnung oft noch offen, und genau dort hilft die Aufschlüsselung.
    Weiter zurück gehen wir bewusst nicht: Dort sind die Honorare längst bezahlt
    und die Zeilen wären nur Karteileichen in der Ausstehend-Liste.
    """
    from models import Event
    zusagen = db.query(Verfuegbarkeitsanfrage).join(
        Event, Event.id == Verfuegbarkeitsanfrage.event_id).filter(
        Verfuegbarkeitsanfrage.status == "Ja",
        Event.datum >= date.today() - timedelta(days=tage)).all()
    n = 0
    for a in zusagen:
        vorher = db.query(EventHonorar).filter(
            EventHonorar.event_id == a.event_id,
            EventHonorar.dienstleister_id == a.dienstleister_id).first()
        if not vorher:
            honorar_anlegen(db, a)
            n += 1
    if n:
        db.commit()
    return n
