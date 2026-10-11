r"""Verbindungs-Monitor: protokolliert jeden Aufruf zwischen den Apps (Aykut 10.10.2026).

Vom 06. bis 09.10.2026 scheiterten alle Versandmeldungen des E-Mail-Assistenten mit
HTTP 500, und niemand merkte es, weil jede App nur ihre eigene Seite kennt. Hier
landet jeder Aufruf mit Ergebnis. Die Seite „Verbindungen" zeigt je Schnittstelle eine
Ampel, und die Glocke meldet eine gestörte Verbindung einmal am Tag.

Welche Schnittstellen es gibt, steht im gemeinsamen Vertrag
C:\Users\aykut\Claude\Austausch\Schnittstellen\SCHNITTSTELLEN.md.
"""
from datetime import datetime, timedelta

AUFBEWAHRUNG_TAGE = 30

# Schlüssel → (Anzeigename, Richtung). Auch Schnittstellen, die noch nie gerufen
# wurden, sollen auf der Seite stehen (graue Ampel), sonst fiele ein Ausfall von
# Anfang an nicht auf.
SCHNITTSTELLEN = {
    "assistent.pruefen":  ("Assistent fragt: darf ich anschreiben?", "ein"),
    "assistent.gesendet": ("Assistent meldet: Erstmail verschickt", "ein"),
    "assistent.antwort":  ("Assistent meldet: Kunde hat geantwortet", "ein"),
    "assistent.angebot":  ("Assistent meldet: Angebot verschickt", "ein"),
    "assistent.sperren":  ("Assistent meldet: bitte keine Mails mehr", "ein"),
    "assistent.ab":       ("Assistent meldet: Auftragsbestätigung verschickt", "ein"),
    "assistent.entwurf":  ("Events-App übergibt Kontakt an den Assistenten", "aus"),
    "social.quickpost":   ("Events-App schickt Eventfoto an die Social-App", "aus"),
}

# Eingehende Aufrufe des Assistenten (für die Middleware in main.py). Der Schlüssel ist
# der letzte Pfadteil: /admin/crm/api/vertrieb/gesendet → assistent.gesendet,
# /admin/crm/api/buchung/ab → assistent.ab.
EINGANG_PRAEFIX = "/admin/crm/api/"

_STATUS_TEXT = {
    401: "Secret falsch oder fehlt. Render-Variablen beider Apps prüfen.",
    404: "Kontakt nicht gefunden.",
    422: "Daten unvollständig oder im falschen Format.",
    500: "Absturz in der Events-App.",
}


def fehlertext(status_code: int) -> str:
    return _STATUS_TEXT.get(status_code, f"HTTP {status_code}")


def protokollieren(schnittstelle: str, ok: bool, status_code: int = None,
                   fehler: str = "", bezug: str = ""):
    """Einen Aufruf festhalten. Eigene DB-Session: Das Protokoll darf weder die
    Transaktion des Aufrufers stören noch selbst einen Fehler werfen."""
    from database import SessionLocal
    from models import Verbindungslog
    richtung = SCHNITTSTELLEN.get(schnittstelle, ("", "ein"))[1]
    db = SessionLocal()
    try:
        jetzt = datetime.now()
        db.add(Verbindungslog(
            erstellt_am=jetzt.isoformat(timespec="seconds"), schnittstelle=schnittstelle,
            richtung=richtung, ok=bool(ok), status_code=status_code,
            fehler=(fehler or "")[:500] or None, bezug=(bezug or "")[:60] or None))
        grenze = (jetzt - timedelta(days=AUFBEWAHRUNG_TAGE)).isoformat(timespec="seconds")
        db.query(Verbindungslog).filter(Verbindungslog.erstellt_am < grenze).delete()
        if not ok:
            _glocke(db, schnittstelle, fehler, jetzt)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[VERBINDUNG] Protokoll für {schnittstelle} fehlgeschlagen: {e}")
    finally:
        db.close()


def _glocke(db, schnittstelle: str, fehler: str, jetzt: datetime):
    """Höchstens eine Meldung je Schnittstelle und Tag, sonst flutet ein Ausfall mit
    vielen Aufrufen die Glocke."""
    from notifications import get_setting, set_setting, notify
    heute = jetzt.date().isoformat()
    schluessel = f"verbindung_glocke:{schnittstelle}"
    if get_setting(db, schluessel, "") == heute:
        return
    set_setting(db, schluessel, heute)
    name = SCHNITTSTELLEN.get(schnittstelle, (schnittstelle, ""))[0]
    notify(db, "verbindung_fehler", "Verbindung zwischen den Apps gestört",
           f"{name}: {fehler or 'Fehler'} Weitere Fehler dieser Verbindung meldet die "
           "Glocke heute nicht mehr, sie stehen auf der Seite Verbindungen.",
           "/admin/verbindungen")


def uebersicht(db) -> list:
    """Je Schnittstelle: letzter Aufruf, letzter Erfolg, Fehler heute, Ampel."""
    from models import Verbindungslog
    heute = datetime.now().date().isoformat()
    zeilen = []
    for schluessel, (name, richtung) in SCHNITTSTELLEN.items():
        q = db.query(Verbindungslog).filter(Verbindungslog.schnittstelle == schluessel)
        letzter = q.order_by(Verbindungslog.id.desc()).first()
        letzter_ok = (q.filter(Verbindungslog.ok.is_(True))
                      .order_by(Verbindungslog.id.desc()).first())
        fehler_heute = (q.filter(Verbindungslog.ok.is_(False),
                                 Verbindungslog.erstellt_am >= heute).count())
        ampel = "grau" if not letzter else ("gruen" if letzter.ok else "rot")
        zeilen.append({"schluessel": schluessel, "name": name, "richtung": richtung,
                       "letzter": letzter, "letzter_ok": letzter_ok,
                       "fehler_heute": fehler_heute, "ampel": ampel})
    return zeilen
