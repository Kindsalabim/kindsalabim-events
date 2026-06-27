"""Kleine Helfer, um Testdaten anzulegen (eigene Session, geben die ID zurück)."""
import itertools
from datetime import date
from types import SimpleNamespace

from database import SessionLocal
from models import Event, Dienstleister, Verfuegbarkeitsanfrage, ExternerTeamer
from auth import create_token

_seq = itertools.count(1)


def make_dienstleister(**kw):
    n = next(_seq)
    s = SessionLocal()
    try:
        d = Dienstleister(
            vorname=kw.pop("vorname", "Vor"), nachname=kw.pop("nachname", f"Nach{n}"),
            email=kw.pop("email", f"dl{n}@example.com"),
            telefon=kw.pop("telefon", "0201 12345"), rolle=kw.pop("rolle", "Teamer"), **kw)
        s.add(d); s.commit()
        return d.id
    finally:
        s.close()


def make_event(**kw):
    n = next(_seq)
    s = SessionLocal()
    try:
        ev = Event(
            anlass=kw.pop("anlass", "Sommerfest"), datum=kw.pop("datum", date(2026, 8, 1)),
            startzeit=kw.pop("startzeit", "14:00"), endzeit=kw.pop("endzeit", "18:00"),
            veranstaltungsort=kw.pop("veranstaltungsort", "Markt 1, 45127 Essen"),
            kunde_firma=kw.pop("kunde_firma", f"Kunde {n}"),
            produkte=kw.pop("produkte", "Zaubershow"), marke=kw.pop("marke", "Kindsalabim"),
            status=kw.pop("status", "Gebucht"), **kw)
        s.add(ev); s.commit()
        return ev.id
    finally:
        s.close()


def make_anfrage(event_id, dienstleister_id, status="Ja", rolle="Teamer", **kw):
    s = SessionLocal()
    try:
        a = Verfuegbarkeitsanfrage(event_id=event_id, dienstleister_id=dienstleister_id,
                                   rolle_anfrage=rolle, status=status, **kw)
        s.add(a); s.commit()
        return a.id
    finally:
        s.close()


def reload(model, id_):
    """Objekt frisch aus einer neuen Session laden (sieht Commits aus Route-Sessions).
    Skalarfelder sind nach dem Schließen nutzbar; für Relationen eine eigene Session öffnen."""
    s = SessionLocal()
    try:
        obj = s.get(model, id_)
        if obj is not None:
            s.refresh(obj)
            s.expunge(obj)
        return obj
    finally:
        s.close()


def briefing_event_ns(**over):
    """Event-artiges SimpleNamespace mit ALLEN Feldern, die send_briefing / build_briefing_pdf
    lesen – zentral, damit neue Feld-Zugriffe nur hier ergänzt werden müssen."""
    base = dict(
        marke="Kindsalabim", anlass="Fest", kunde_firma="Kunde", datum=date(2026, 8, 1),
        startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
        produkte="Zaubershow", kunde_kontakt="", kunde_telefon="", hinweise="", teamleiter_id=None,
        cl_aufbau_von="", cl_aufbau_bis="", cl_abbau_von="", cl_abbau_bis="",
        cl_aufbauort="", cl_parkplatz="", cl_teamkleidung="", cl_verpflegung="",
        cl_weitere_details="", cl_firma_name="", cl_strasse="", cl_plz_ort="",
        cl_ansprechpartner_name="", cl_ansprechpartner_mobil="",
        ankunft_modus="auto", ankunft_text="", treffpunkt="",
    )
    base.update(over)
    return SimpleNamespace(**base)


def briefing_dl_ns(**over):
    base = dict(id=1, vorname="Max", nachname="Muster", telefon="0151", email="dl@example.com")
    base.update(over)
    return SimpleNamespace(**base)


def portal_login(client, dienstleister_id):
    client.cookies.set("portal_token",
                       create_token({"sub": str(dienstleister_id), "role": "dienstleister"}, expires_minutes=60))
    return client
