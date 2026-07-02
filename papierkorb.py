"""Papierkorb / Notfall-Sicherung.

Beim Löschen von Events/Dienstleistern/Kunden wird der Datensatz inkl. seiner
verknüpften Zeilen als JSON-Snapshot in der Tabelle GeloeschtesObjekt abgelegt,
BEVOR er hart gelöscht wird. Die bestehende Lösch-Logik bleibt unverändert –
es kommt nur ein Sicherungs-Schritt davor. So entstehen keine "Geist-Datensätze"
in den übrigen Listen, aber ein Fehlklick ist nicht mehr unwiederbringlich.

Phase 2 (`restore`): aus einem Snapshot lässt sich der Datensatz inkl. Verknüpfungen
wiederherstellen – mit neuer ID (kein ID-Konflikt), Kind-Verweise werden umgehängt.
"""
import json
from datetime import datetime, date, time
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import Date as SA_Date, DateTime as SA_DateTime, Time as SA_Time

from models import (GeloeschtesObjekt, Event, Dienstleister, Kunde, KundeTag,
                    Verfuegbarkeitsanfrage, EventDatei, Bastelvorschlag,
                    DienstleisterSperrzeit, KundeAktivitaet, KundeWiedervorlage,
                    ExternerTeamer)


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
        # Externe Teamer werden mit dem Event kaskadiert gelöscht → mitsichern,
        # sonst gehen sie bei Löschen+Wiederherstellen verloren. (Review M13)
        "externe_teamer": [_row(e) for e in db.query(ExternerTeamer).filter(
            ExternerTeamer.event_id == ev.id).all()],
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


# ── Wiederherstellen (Phase 2) ───────────────────────────────────────────────────

def _coerce(model_cls, data: dict) -> dict:
    """Snapshot-dict → Konstruktor-kwargs: `id` raus, ISO-Strings → date/time zurück,
    unbekannte Keys (z. B. aus älteren Snapshots) ignoriert."""
    cols = {a.key: a.columns[0].type for a in sa_inspect(model_cls).column_attrs}
    out = {}
    for key, val in data.items():
        if key == "id" or key not in cols:
            continue
        if isinstance(val, str) and val:
            t = cols[key]
            try:
                if isinstance(t, SA_DateTime):
                    val = datetime.fromisoformat(val)
                elif isinstance(t, SA_Date):
                    val = date.fromisoformat(val)
                elif isinstance(t, SA_Time):
                    val = time.fromisoformat(val)
            except ValueError:
                pass
        out[key] = val
    return out


def _restore_event(db, daten):
    kw = _coerce(Event, daten["event"])
    kw["kalender_event_id"] = None  # alter Kalendereintrag ist gelöscht → neu synchronisieren
    # Verweise auf zwischenzeitlich gelöschte Kunden/Dienstleister lösen, sonst bricht
    # der komplette Restore am FK-Constraint ab (Postgres). Die Spalten sind nullable. (Review M14)
    if kw.get("kunde_id") and not db.query(Kunde).filter(Kunde.id == kw["kunde_id"]).first():
        kw["kunde_id"] = None
    for fk in ("teamleiter_id", "logistiker_id"):
        if kw.get(fk) and not db.query(Dienstleister).filter(Dienstleister.id == kw[fk]).first():
            kw[fk] = None
    ev = Event(**kw)
    db.add(ev); db.flush()
    for a in daten.get("anfragen", []):
        # Anfrage nur zurück, wenn der Dienstleister noch existiert (sonst FK-Bruch)
        if not db.query(Dienstleister).filter(Dienstleister.id == a.get("dienstleister_id")).first():
            continue
        akw = _coerce(Verfuegbarkeitsanfrage, a); akw["event_id"] = ev.id
        db.add(Verfuegbarkeitsanfrage(**akw))
    for d in daten.get("dateien", []):
        dkw = _coerce(EventDatei, d); dkw["event_id"] = ev.id
        db.add(EventDatei(**dkw))
    for b in daten.get("bastelvorschlaege", []):
        bkw = _coerce(Bastelvorschlag, b); bkw["event_id"] = ev.id
        db.add(Bastelvorschlag(**bkw))
    for e in daten.get("externe_teamer", []):
        ekw = _coerce(ExternerTeamer, e); ekw["event_id"] = ev.id
        db.add(ExternerTeamer(**ekw))
    db.flush()
    return None, ev.id


def _restore_dienstleister(db, daten):
    kw = _coerce(Dienstleister, daten["dienstleister"])
    email = kw.get("email")
    if email and db.query(Dienstleister).filter(Dienstleister.email == email).first():
        return f"Ein Dienstleister mit der E-Mail {email} existiert bereits – nicht wiederhergestellt.", None
    dl = Dienstleister(**kw)
    db.add(dl); db.flush()
    for s in daten.get("sperrzeiten", []):
        skw = _coerce(DienstleisterSperrzeit, s); skw["dienstleister_id"] = dl.id
        db.add(DienstleisterSperrzeit(**skw))
    for a in daten.get("anfragen", []):
        # Anfrage nur zurück, wenn das Event noch existiert
        if not db.query(Event).filter(Event.id == a.get("event_id")).first():
            continue
        akw = _coerce(Verfuegbarkeitsanfrage, a); akw["dienstleister_id"] = dl.id
        db.add(Verfuegbarkeitsanfrage(**akw))
    db.flush()
    return None, None


def _restore_kunde(db, daten):
    kw = _coerce(Kunde, daten["kunde"])
    k = Kunde(**kw)
    db.add(k); db.flush()
    for a in daten.get("aktivitaeten", []):
        akw = _coerce(KundeAktivitaet, a); akw["kunde_id"] = k.id
        db.add(KundeAktivitaet(**akw))
    for w in daten.get("wiedervorlagen", []):
        wkw = _coerce(KundeWiedervorlage, w); wkw["kunde_id"] = k.id
        db.add(KundeWiedervorlage(**wkw))
    for tagname in daten.get("tags", []):
        tag = db.query(KundeTag).filter(KundeTag.name == tagname).first()
        if not tag:
            tag = KundeTag(name=tagname); db.add(tag); db.flush()
        k.tags.append(tag)
    db.flush()
    return None, None


def restore(db, eintrag):
    """Stellt den Datensatz aus einem Snapshot wieder her (neue ID, Kind-Verweise umgehängt).
    Rückgabe: (fehler_oder_None, sync_event_id_oder_None). Der Aufrufer committet."""
    daten = json.loads(eintrag.daten_json)
    if eintrag.typ == "event":
        return _restore_event(db, daten)
    if eintrag.typ == "dienstleister":
        return _restore_dienstleister(db, daten)
    if eintrag.typ == "kunde":
        return _restore_kunde(db, daten)
    return "Unbekannter Typ – nicht wiederherstellbar.", None
