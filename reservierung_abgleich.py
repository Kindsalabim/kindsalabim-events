"""Findet Reservierungen, zu denen es schon ein gebuchtes Event gibt (und umgekehrt).

Vorfall 16.09.2026 (Funke): Die Buchung wurde als neues Event angelegt statt die
Reservierung umzuwandeln. Die Reservierung blieb liegen, lief ab und stand pink im
Kalender – neben dem echten Event. Abgleich über gleiches Datum + gemeinsames
Kernwort im Kundennamen. Kundennamen sind nicht eindeutig genug für automatisches
Löschen, deshalb nur Hinweis + Klick.
"""
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import Event, Reservierung

# Allerweltswörter, die zwei verschiedene Kunden nicht gleich machen
_STOPPWOERTER = {
    "kita", "kitas", "kindergarten", "kindertagesstaette", "kindertageseinrichtung",
    "familienzentrum", "tageseinrichtung", "stadt", "staedtische", "staedtisches",
    "staedtischer", "gmbh", "mbh", "gruppe", "holding", "verein", "schule",
    "grundschule", "gesamtschule", "evangelische", "evangelischer", "katholische",
    "katholischer", "fuer", "und", "der", "die", "das", "den", "dem",
    "firma", "familie", "kunde", "herr", "frau", "sommerfest", "kinderfest", "fest", "weihnachtsfeier", "event",
}


def _kern_woerter(name: str) -> set:
    t = (name or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    woerter = re.split(r"[^a-z0-9]+", t)
    return {w for w in woerter if len(w) >= 4 and w not in _STOPPWOERTER}


def passt(kunde_a: str, kunde_b: str) -> bool:
    """Mindestens ein gemeinsames Kernwort („Funke Mediengruppe" ~ „FUNKE Medien NRW")."""
    return bool(_kern_woerter(kunde_a) & _kern_woerter(kunde_b))


def passende_reservierungen(db: Session, ev: Event) -> list:
    """Offene Reservierungen am selben Tag mit passendem Kundennamen."""
    if not ev.datum or ev.status == "Abgesagt":
        return []
    kandidaten = db.query(Reservierung).filter(Reservierung.datum == ev.datum).all()
    return [r for r in kandidaten if passt(r.kunde_firma, ev.kunde_firma or ev.anlass)]


def passendes_event(db: Session, r: Reservierung):
    """Gebuchtes Event am selben Tag mit passendem Kundennamen (oder None)."""
    kandidaten = db.query(Event).filter(
        Event.datum == r.datum,
        or_(Event.status == None, Event.status != "Abgesagt"),  # noqa: E711
    ).all()
    for ev in kandidaten:
        if passt(r.kunde_firma, ev.kunde_firma or ev.anlass):
            return ev
    return None
