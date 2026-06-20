"""Papierkorb / Notfall-Sicherung (Phase 1: sichern + Download).

Beim Löschen von Events/Dienstleistern/Kunden wird der Datensatz inkl. seiner
verknüpften Zeilen als JSON-Snapshot in der Tabelle GeloeschtesObjekt abgelegt,
BEVOR er hart gelöscht wird. Die bestehende Lösch-Logik bleibt unverändert –
es kommt nur ein Sicherungs-Schritt davor. So entstehen keine "Geist-Datensätze"
in den übrigen Listen, aber ein Fehlklick ist nicht mehr unwiederbringlich.

Der Snapshot wird mit demselben db.commit() persistiert wie das Löschen selbst
(der Aufrufer committet) – beide gehen also gemeinsam durch oder gar nicht.
"""
import json
from datetime import datetime, date, time
from sqlalchemy import inspect as sa_inspect

from models import (GeloeschtesObjekt, Verfuegbarkeitsanfrage, EventDatei,
                    Bastelvorschlag, DienstleisterSperrzeit,
                    KundeAktivitaet, KundeWiedervorlage)


def _row(obj) -> dict:
    """Spalten eines ORM-Objekts als JSON-sicheres dict (Datum/Zeit → ISO-String)."""
    out = {}
    for col in sa_inspect(obj).mapper.column_attrs:
        val = getattr(obj, col.key)
        if isinstance(val, (date, datetime, time)):
            val = val.isoformat()
        out[col.key] = val
    return out


def _snapshot_event(db, ev) -> dict:
    return {
        "event": _row(ev),
        "anfragen": [_row(a) for a in db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.event_id == ev.id).all()],
        "dateien": [_row(d) for d in db.query(EventDatei).filter(
            EventDatei.event_id == ev.id).all()],
        "bastelvorschlaege": [_row(b) for b in db.query(Bastelvorschlag).filter(
            Bastelvorschlag.event_id == ev.id).all()],
    }


def _snapshot_dienstleister(db, d) -> dict:
    return {
        "dienstleister": _row(d),
        "sperrzeiten": [_row(s) for s in db.query(DienstleisterSperrzeit).filter(
            DienstleisterSperrzeit.dienstleister_id == d.id).all()],
        "anfragen": [_row(a) for a in db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.dienstleister_id == d.id).all()],
    }


def _snapshot_kunde(db, k) -> dict:
    return {
        "kunde": _row(k),
        "aktivitaeten": [_row(a) for a in db.query(KundeAktivitaet).filter(
            KundeAktivitaet.kunde_id == k.id).all()],
        "wiedervorlagen": [_row(w) for w in db.query(KundeWiedervorlage).filter(
            KundeWiedervorlage.kunde_id == k.id).all()],
        "tags": [t.name for t in k.tags],
    }


def _archiviere(db, typ, obj_id, bezeichnung, daten, admin_email):
    db.add(GeloeschtesObjekt(
        typ=typ, objekt_id=obj_id, bezeichnung=(bezeichnung or "")[:300],
        daten_json=json.dumps(daten, ensure_ascii=False),
        geloescht_am=datetime.utcnow().isoformat(),
        geloescht_von=admin_email or "",
    ))


# ── Öffentliche Helfer (in den Lösch-Routen aufgerufen, vor db.delete) ───────────

def archive_event(db, ev, admin_email):
    d = ev.datum.strftime("%d.%m.%Y") if ev.datum else "?"
    bez = f"{ev.anlass or 'Event'} – {ev.kunde_firma or ''} ({d})".strip()
    _archiviere(db, "event", ev.id, bez, _snapshot_event(db, ev), admin_email)


def archive_dienstleister(db, dl, admin_email):
    bez = f"{dl.vorname or ''} {dl.nachname or ''}".strip() or dl.email or "Dienstleister"
    _archiviere(db, "dienstleister", dl.id, bez, _snapshot_dienstleister(db, dl), admin_email)


def archive_kunde(db, k, admin_email):
    _archiviere(db, "kunde", k.id, k.firma or "Kunde", _snapshot_kunde(db, k), admin_email)
