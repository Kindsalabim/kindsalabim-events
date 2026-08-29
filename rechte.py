# -*- coding: utf-8 -*-
"""Zugriffsrollen der Admin-Zugänge.

Zwei Stufen (mit Aykut abgestimmt, 26.08.2026):

- **inhaber** – Vollzugriff (Standard; alle bestehenden Zugänge bleiben das).
- **buero** – Disposition für eine Bürokraft: Events, Reservierungen, Anfragen,
  Briefings, Checklisten, Kunden, Bastel-Recherche und Angebote. Gesperrt sind
  Buchhaltung, Stundensätze/Konditionen der Dienstleister, das Löschen von
  Datensätzen samt Papierkorb sowie die Verwaltung der Admin-Zugänge.

Das Künstler-Budget an der Anfrage bleibt bewusst sichtbar – ohne das lässt sich
keine Künstler-Anfrage verschicken, und genau das ist Aufgabe der Disposition.
"""
from fastapi import Depends, HTTPException
from sqlalchemy import func

from auth import get_admin_user
from database import get_db
from models import Admin

INHABER = "inhaber"
BUERO = "buero"
ROLLEN = [(INHABER, "Inhaber (Vollzugriff)"),
          (BUERO, "Büro / Disposition (ohne Buchhaltung, Konditionen, Löschen)")]

GESPERRT_TEXT = ("Dieser Bereich ist für Büro-Zugänge gesperrt. "
                 "Bitte wende dich an die Geschäftsführung.")


def normalisieren(wert) -> str:
    return BUERO if wert == BUERO else INHABER


def admin_rolle(db, user) -> str:
    """Rolle des eingeloggten Admins (unbekannt = Vollzugriff, wie bisher)."""
    email = ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()
    if not email:
        return INHABER
    a = db.query(Admin).filter(func.lower(Admin.email) == email).first()
    return normalisieren(a.rolle if a else None)


def ist_buero(db, user) -> bool:
    return admin_rolle(db, user) == BUERO


def nur_inhaber(user=Depends(get_admin_user), db=Depends(get_db)):
    """FastAPI-Dependency für gesperrte Bereiche (Buchhaltung, Zugänge, Papierkorb,
    Löschen). Büro-Zugänge bekommen eine verständliche 403-Seite."""
    if ist_buero(db, user):
        raise HTTPException(403, GESPERRT_TEXT)
    return user
