"""Auftragsbestätigung (Lexoffice-PDF) auslesen → Künstler-Budget vorschlagen.

Budget-Regel (Aykut, 07/2026): Netto-Positionssumme der gebuchten Aktion × 80 %
(20 % Vermittlungsprovision). Fahrtkosten fließen NICHT ein. Es wird nur die
Textebene des PDFs gelesen – kein OCR, keine KI. Format = Lexoffice (stabil).
"""
import io
import math
import re

BUDGET_ANTEIL = 0.80   # Künstler erhält 80 % der Netto-Position (20 % Provision)


def auf_10(betrag) -> int:
    """Kaufmännisch auf den nächsten 10er runden (296 → 300, 294 → 290, 295 → 300)."""
    return int(math.floor(betrag / 10 + 0.5) * 10)

# Betragszeile in der AB: <Menge> <Einheit> <Einzel> <Gesamt>. Die Trennungen im
# Lexoffice-PDF sind unzuverlässig (mal Leerzeichen, mal zusammengeklebt), darum \s* –
# auch zwischen Einzel und Gesamt („155,00930,00"): das Komma mit genau 2 Nachkomma-
# stellen macht die Trennung trotzdem eindeutig.
_EINHEIT = (r"(?:Stunden?|Std\.?|Stück|Stk\.?|Tagess?atz|Tage?|Pauschale|Einheit"
            r"|Pers\.?|Personen?|[Mm]in\.?|Minuten?)")
_BETRAG = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_POS_RE = re.compile(
    rf"(?P<menge>\d+(?:,\d+)?)\s*{_EINHEIT}\s*(?P<einzel>{_BETRAG})\s*(?P<gesamt>{_BETRAG})")


def _eur(s: str) -> float:
    """Deutsches Format „1.234,56" → 1234.56."""
    return float(s.replace(".", "").replace(",", "."))


# Lexoffice nennt manche Aktionen anders als das Event-Formular (Abgleich mit den
# echten ABs 2025). Nur echte Fremdnamen – reine Schreibvarianten wie
# „Knusper-Häuschen" oder „Zaubershow & Ballonmodellage" fängt schon _norm() ab.
_ALIAS = {
    "Prickeln": ("Prickelaktion",),
    "U3 Spieleland": ("Spieleland U3", "Spiele U3", "U3 Spiele"),
}


def _norm(s: str) -> str:
    """Nur Kleinbuchstaben/Ziffern/Umlaute übrig lassen – macht das Matching
    unempfindlich gegen AB-Schreibweisen („Knusper-Häuschen", „&" statt „+")
    und gegen Trennstriche aus PDF-Zeilenumbrüchen („ge-stalten")."""
    return re.sub(r"[^a-z0-9äöüß]", "", s.lower())


def _text(pdf_bytes: bytes) -> str:
    import pypdf
    r = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() or "" for p in r.pages)


def positionen(pdf_bytes: bytes):
    """Alle Positionen als (text_davor, gesamt_netto). Der Text VOR dem Betrag enthält
    den Positionsnamen – daran wird die gebuchte Aktion zugeordnet."""
    text = _text(pdf_bytes)
    out, letzte = [], 0
    for m in _POS_RE.finditer(text):
        out.append((text[letzte:m.start()], _eur(m.group("gesamt"))))
        letzte = m.end()
    return out


def budget_vorschlaege(pdf_bytes, aktionen):
    """Zu jeder gebuchten Aktion die passende AB-Position finden und Budget (×80 %)
    berechnen. Rückgabe: [{'aktion','netto','budget'}], je (Aktion, Betrag) einmal.
    Robust: bei Parse-Fehlern eine leere Liste (dann greift die manuelle Eingabe)."""
    try:
        pos = positionen(pdf_bytes)
    except Exception:
        return []
    seen, out = set(), []
    for segment, gesamt in pos:
        seg = _norm(segment)
        for aktion in aktionen:
            begriffe = (aktion, *_ALIAS.get(aktion, ()))
            if aktion and any(_norm(b) in seg for b in begriffe):
                key = (aktion, gesamt)
                if key not in seen:
                    seen.add(key)
                    out.append({"aktion": aktion, "netto": gesamt,
                                "budget": auf_10(gesamt * BUDGET_ANTEIL)})
                break
    return out
