"""Gemeinsame Auswahllisten & Formatierungs-Helfer für Formulare/Templates."""
import re

# Uhrzeiten 07:00–24:00 in 15-Minuten-Schritten (für Dropdowns)
ZEITEN = [f"{h:02d}:{m:02d}" for h in range(7, 24) for m in (0, 15, 30, 45)] + ["24:00"]


def plz_ort(ort: str) -> str:
    """Nur PLZ + Ort aus einer Adresse (Straße/Hausnummer entfernt) – für die Anfrage-
    Ansicht, in der Dienstleister den Kunden noch nicht vollständig sehen sollen."""
    if not ort:
        return ""
    m = re.search(r"\d{5}.*", ort)
    if m:
        return m.group(0).strip().rstrip(",").strip()
    # Fallback ohne PLZ: letztes Segment (vermutlich der Ort)
    return ort.split(",")[-1].strip()


def de_date(d) -> str:
    """Datum als TT.MM.JJJJ; akzeptiert date-Objekt oder None."""
    return d.strftime("%d.%m.%Y") if d else ""


_MONATE_KURZ = ["JAN", "FEB", "MÄR", "APR", "MAI", "JUN",
                "JUL", "AUG", "SEP", "OKT", "NOV", "DEZ"]


def de_month(d) -> str:
    """Deutsches Monatskürzel (z. B. MAI) aus einem date-Objekt."""
    return _MONATE_KURZ[d.month - 1] if d else ""


def de_euro(value) -> str:
    """Zahl als deutsches Euro-Format: 1.234,56 – oder '–' bei None."""
    if value is None:
        return "–"
    # Python {:,.2f} → "1,234.56" → Trennzeichen tauschen → "1.234,56"
    s = f"{float(value):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
