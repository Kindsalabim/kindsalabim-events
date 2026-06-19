"""Leichte Plausibilitätschecks für Formulareingaben (DE-Formate).

Reine Backstop-Validierung serverseitig – die Formulare prüfen dieselben Regeln
client-seitig per HTML5-Attributen. Alle Checks sind additiv: leere optionale
Felder sind immer erlaubt.
"""
import re
from datetime import date

_PHONE_RE = re.compile(r"^[0-9 /().+\-]{6,}$")
_PLZ_RE = re.compile(r"^\d{5}$")
_PLZ_IN_TEXT_RE = re.compile(r"\d{5}")


def valid_phone(s: str) -> bool:
    """Leer (optional) oder plausible Telefonnummer: Ziffern + übliche Trennzeichen."""
    s = (s or "").strip()
    return not s or bool(_PHONE_RE.match(s))


def valid_plz(s: str) -> bool:
    """Leer (optional) oder genau 5 Ziffern (deutsche PLZ)."""
    s = (s or "").strip()
    return not s or bool(_PLZ_RE.match(s))


def has_plz(s: str) -> bool:
    """Enthält der Text irgendwo eine 5-stellige PLZ?"""
    return bool(_PLZ_IN_TEXT_RE.search(s or ""))


def parse_decimal(s: str):
    """Deutsches Dezimalformat → float. Gibt (ok, wert) zurück; wert=None bei leer."""
    s = (s or "").strip()
    if not s:
        return True, None
    try:
        return True, float(s.replace(",", "."))
    except ValueError:
        return False, None


def validate_event_form(datum: str, startzeit: str, endzeit: str,
                        telefon: str, ort: str, produkte=None):
    """Prüft das Event-Formular. Gibt (datum_als_date|None, fehler|None) zurück."""
    try:
        datum_d = date.fromisoformat(datum)
    except ValueError:
        return None, "Bitte ein gültiges Datum wählen."
    # Zeiten sind Dropdowns im Format HH:MM (null-gepolstert) → lexikalischer Vergleich = chronologisch
    if startzeit and endzeit and endzeit <= startzeit:
        return None, "Die Endzeit muss nach der Startzeit liegen."
    if not valid_phone(telefon):
        return None, "Bitte eine gültige Telefonnummer eingeben (nur Ziffern und + ( ) / -)."
    if not has_plz(ort):
        return None, "Bitte den Veranstaltungsort mit 5-stelliger PLZ angeben (z. B. 45127 Essen)."
    if produkte is not None and not produkte:
        return None, "Bitte mindestens eine Aktion auswählen (oder 'Kein Material' für reine Betreuung)."
    return datum_d, None


def validate_dienstleister_form(telefon: str, plz: str,
                                stundensatz_teamer: str, stundensatz_kuenstler: str,
                                portal_passwort: str = ""):
    """Prüft das Dienstleister-Formular. Gibt fehler|None zurück."""
    if not valid_phone(telefon):
        return "Bitte eine gültige Telefonnummer eingeben (nur Ziffern und + ( ) / -)."
    if not valid_plz(plz):
        return "Die PLZ muss aus genau 5 Ziffern bestehen."
    ok_t, _ = parse_decimal(stundensatz_teamer)
    ok_k, _ = parse_decimal(stundensatz_kuenstler)
    if not (ok_t and ok_k):
        return "Bitte gültige Stundensätze eingeben (z. B. 25,00)."
    if portal_passwort and len(portal_passwort) < 8:
        return "Das Portal-Passwort muss mindestens 8 Zeichen lang sein."
    return None
