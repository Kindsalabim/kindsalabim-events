# -*- coding: utf-8 -*-
"""Persönliche Marken-Ansicht je Admin (Kindsalabim / Knallfrosch / beide).

Hintergrund: Knallfrosch ist eine GbR mit einem Geschäftspartner, Kindsalabim ist
Aykuts Einzelunternehmen. Jeder Admin stellt für sich ein, welche Marke(n) er sehen
und zu welchen er Meldungen bekommen will – das ist bewusst eine ANSICHTS-Einstellung
(keine Rechtevergabe, die Vertrauensbasis ist vorhanden).

Der Filter wirkt auf: Dashboard (Events, Kalender, Zahlen), Reservierungen,
Buchhaltung, Glocke und den Mailversand an Admins.
"""
from sqlalchemy import func, or_

from models import Admin

BEIDE = "beide"
MARKEN = ("Kindsalabim", "Knallfrosch")


def normalisieren(wert) -> str:
    """Beliebige Eingabe → gültiger Filterwert ("beide" als sicherer Default)."""
    return wert if wert in MARKEN else BEIDE


def admin_marke(db, user) -> str:
    """Marken-Filter des eingeloggten Admins. Unbekannt/nicht gesetzt = beide."""
    email = ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()
    if not email:
        return BEIDE
    a = db.query(Admin).filter(func.lower(Admin.email) == email).first()
    return normalisieren(a.marken_filter if a else None)


def passt(marke, filter_wert: str) -> bool:
    """Ist ein Datensatz für diesen Filter sichtbar? Ohne Marke = markenneutral."""
    return filter_wert == BEIDE or not marke or marke == filter_wert


def query_filter(query, spalte, filter_wert: str, neutral_sichtbar: bool = True):
    """Marken-Filter auf eine Query anwenden.
    neutral_sichtbar=True: Datensätze ohne Marke bleiben sichtbar (z. B. allgemeine
    Benachrichtigungen); False: nur exakte Treffer (z. B. Rechnungen)."""
    if filter_wert == BEIDE:
        return query
    if neutral_sichtbar:
        return query.filter(or_(spalte == None, spalte == filter_wert))  # noqa: E711
    return query.filter(spalte == filter_wert)


def admins_fuer_marke(db, marke):
    """Aktive Admins, die zu dieser Marke Meldungen bekommen wollen (E-Mail-Versand)."""
    admins = db.query(Admin).filter(Admin.aktiv == True).all()   # noqa: E712
    return [a for a in admins if passt(marke, normalisieren(a.marken_filter))]
