# -*- coding: utf-8 -*-
"""Platzvergabe bei Verfügbarkeitsanfragen – Regeln für Zusagen und Warteliste.

Mit Aykut abgestimmt (21.08.2026), damit die Mehrarbeit nicht im Büro landet:

1. Ein Einsatz kann nur zugesagt werden, solange für die angefragte Rolle ein Platz
   frei ist. Ist das Team voll, lehnt die App selbst ab (auch fristgerecht).
2. Nach Fristablauf gilt zusätzlich der Vorrang der Pünktlichen: Läuft für dieselbe
   Rolle noch eine fristgerechte Anfrage, kommt die verspätete Zusage auf die
   Warteliste statt den Platz wegzuschnappen.
3. Wird später ein Platz frei (Absage oder Fristablauf), rückt der Älteste von der
   Warteliste automatisch nach und bekommt die Anfrage per Mail erneut.
"""
from datetime import date, datetime, timedelta

from models import ExternerTeamer, Verfuegbarkeitsanfrage

NACHRUECK_FRIST_TAGE = 2   # Frist für eine automatisch reaktivierte Anfrage


def plaetze_frei(db, ev, rolle: str):
    """Wie viele Plätze dieser Rolle sind noch offen? (Bedarf minus Zusagen)

    Rückgabe None = für diese Rolle ist gar kein Bedarf hinterlegt (z. B. reines
    Zaubershow-Event, bei dem trotzdem jemand angefragt wurde). Dann gilt KEIN
    Limit – wer angefragt wurde, darf zusagen; die App weiß es nicht besser."""
    bedarf = (ev.anzahl_teamer if rolle == "Teamer" else ev.anzahl_kuenstler) or 0
    if bedarf <= 0:
        return None
    zusagen = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id,
        Verfuegbarkeitsanfrage.rolle_anfrage == rolle,
        Verfuegbarkeitsanfrage.status == "Ja").count()
    if rolle == "Teamer":   # extern eingetragene Teamer zählen mit
        zusagen += db.query(ExternerTeamer).filter(
            ExternerTeamer.event_id == ev.id).count()
    return max(0, bedarf - zusagen)


def ist_verspaetet(a, heute=None) -> bool:
    """Antwort nach Fristablauf? (Status oder Frist-Datum verraten es)"""
    heute = heute or date.today()
    return a.status == "Abgelaufen" or bool(a.frist_datum and a.frist_datum < heute)


def offene_konkurrenz(db, ev, rolle: str, ausser_id: int, heute=None) -> int:
    """Noch laufende, fristgerechte Anfragen derselben Rolle bei anderen Personen."""
    heute = heute or date.today()
    offene = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id,
        Verfuegbarkeitsanfrage.rolle_anfrage == rolle,
        Verfuegbarkeitsanfrage.status == "Ausstehend",
        Verfuegbarkeitsanfrage.id != ausser_id).all()
    # „fristgerecht" = Frist noch nicht verstrichen (der Cron markiert erst am Folgetag)
    return sum(1 for x in offene if not x.frist_datum or x.frist_datum >= heute)


def zusage_pruefen(db, a, heute=None):
    """Darf diese Zusage angenommen werden?
    Rückgabe: ("ok" | "glueck" | "voll" | "zu_spaet" | "warteliste")."""
    ev = a.event
    if not ev:
        return "ok"
    heute = heute or date.today()
    verspaetet = ist_verspaetet(a, heute)
    frei = plaetze_frei(db, ev, a.rolle_anfrage)
    if frei is not None and frei <= 0:
        return "zu_spaet" if verspaetet else "voll"
    if verspaetet and offene_konkurrenz(db, ev, a.rolle_anfrage, a.id, heute) > 0:
        return "warteliste"
    return "glueck" if verspaetet else "ok"


def auf_warteliste(db, a):
    """Verspätete Zusage parken – Reihenfolge über den Zeitstempel."""
    if not a.warteliste_seit:
        a.warteliste_seit = datetime.now().isoformat(timespec="seconds")
    a.status = "Abgelaufen"      # bleibt für das Büro sichtbar als „nicht besetzt"
    db.commit()


def warteliste_nachruecken(db, ev, rolle: str) -> list:
    """Nach einer Absage/einem Fristablauf: so viele Wartende reaktivieren, wie
    Plätze frei sind (älteste zuerst). Gibt die reaktivierten Anfragen zurück.
    Verschickt die Anfrage-Mail erneut; Mailfehler bremsen das Nachrücken nicht."""
    frei = plaetze_frei(db, ev, rolle)
    if (frei is not None and frei <= 0) or not ev.datum:
        return []
    wartende = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.event_id == ev.id,
        Verfuegbarkeitsanfrage.rolle_anfrage == rolle,
        Verfuegbarkeitsanfrage.warteliste_seit != None,          # noqa: E711
        Verfuegbarkeitsanfrage.status != "Ja",
    ).order_by(Verfuegbarkeitsanfrage.warteliste_seit).limit(frei or 50).all()
    if not wartende:
        return []

    heute = date.today()
    # Neue Frist: 2 Tage, aber nie über den Vortag des Events hinaus
    neue_frist = min(heute + timedelta(days=NACHRUECK_FRIST_TAGE),
                     max(heute, ev.datum - timedelta(days=1)))
    from notifications import notify
    reaktiviert = []
    for a in wartende:
        a.status = "Ausstehend"
        a.frist_datum = neue_frist
        a.frist_verlaengert = False
        a.erinnerung_gesendet = False
        a.warteliste_seit = None
        d = a.dienstleister
        name = f"{d.vorname} {d.nachname}" if d else "Ein Dienstleister"
        notify(db, "warteliste", f"Warteliste: {name} rückt nach",
               f"{name} stand für {ev.anlass or 'das Event'} am "
               f"{ev.datum.strftime('%d.%m.%Y')} auf der Warteliste und wurde automatisch "
               f"erneut angefragt (neue Frist: {neue_frist.strftime('%d.%m.%Y')}).",
               f"/admin/events/{ev.id}", marke=ev.marke)
        reaktiviert.append(a)
    db.commit()

    for a in reaktiviert:
        try:
            from email_service import send_warteliste_nachrueckung
            send_warteliste_nachrueckung(a.dienstleister, ev, a.frist_datum)
        except Exception as e:
            print(f"Nachrück-Mail fehlgeschlagen (Anfrage {a.id}): {e}")
    return reaktiviert
