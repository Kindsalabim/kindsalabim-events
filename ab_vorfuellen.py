"""Auftragsbestätigung (Lexoffice-PDF) auslesen → „Neues Event“ vorausfüllen
(Aykut 26.11.2026). Nur die Textebene, keine KI: kostet nichts und rät nicht.

Liest: Marke (Briefkopf), Firma + Firmenadresse (Empfänger-Block), Termintage mit
Uhrzeit (Einleitungstext), gebuchte Aktionen (Positionstitel), Anzahl Teamer
(Teamer-Position) und Künstler (je gebuchter Künstler-Aktion einer). Was sich nicht
sicher zuordnen lässt, bleibt leer oder wird als Hinweis gemeldet.
"""
import re
from datetime import date

from ab_budget import _ALIAS, _norm

_MONATE = {m: i for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
     "september", "oktober", "november", "dezember"], start=1)}
_EINHEIT = re.compile(r"^(?:Stunden?|Std\.?|Stück|Stk\.?|Tagess?atz|Tage?|Pauschale|Einheit"
                      r"|Pers\.?|Personen?|[Mm]in\.?|Minuten?)$")
_BETRAG = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
_MENGE = re.compile(r"^\d+(?:,\d+)?$")
_NEBENPOSTEN = ("teamer", "fahrtkosten", "agenturverg", "ausstattung")


def _zeilen(pdf_bytes: bytes) -> list:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return [z.strip() for seite in doc for z in seite.get_text().splitlines()]


def _jahr4(j: str) -> int:
    j = int(j)
    return j + 2000 if j < 100 else j


def _datum(t, m, j):
    try:
        return date(j, m, t)
    except ValueError:
        return None


def _zeit(h, m) -> str:
    return f"{int(h):02d}:{(m or '00')}"


_ZEIT_RE = re.compile(r"(?<![\d.])(\d{1,2})(?::(\d{2}))?\s*(?:Uhr)?\s*(?:–|-|bis)\s*"
                      r"(\d{1,2})(?::(\d{2}))?(?![\d.])(\s*Uhr)?")


def _zeitspanne(text: str):
    """Erste Uhrzeit-Spanne („13:45 – 18:00“, „12-17 Uhr“, „13:00 Uhr bis 18:00“)."""
    for m in _ZEIT_RE.finditer(text):
        if not (m.group(2) or m.group(4) or m.group(5)):
            continue                      # weder Doppelpunkt noch „Uhr“ → keine Uhrzeit
        if int(m.group(1)) > 24 or int(m.group(3)) > 24:
            continue
        return _zeit(m.group(1), m.group(2)), _zeit(m.group(3), m.group(4))
    return None


def _tage_in_zeile(zeile: str, ab_datum) -> list:
    """Alle Termintage einer Zeile: 14.11.2026 · 26./27.09.26 · 13. – 14.11.2026 ·
    05.Dezember (Jahr aus dem AB-Datum, nächstes kommendes)."""
    out = []
    for m in re.finditer(r"(\d{1,2})\.\s*(?:(/)|–|-)\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})", zeile):
        a, b, mon, j = int(m.group(1)), int(m.group(3)), int(m.group(4)), _jahr4(m.group(5))
        tage = [a, b] if m.group(2) else list(range(a, b + 1))
        out += [_datum(t, mon, j) for t in tage]
    rest = re.sub(r"(\d{1,2})\.\s*(?:/|–|-)\s*(?=\d{1,2}\.\d{1,2}\.\d{2,4})", " ", zeile)
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)", rest):
        out.append(_datum(int(m.group(1)), int(m.group(2)), _jahr4(m.group(3))))
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\.\s*([A-Za-zäÄ]+)(?:\s+(\d{4}))?", zeile):
        mon = _MONATE.get(m.group(2).lower())
        if not mon:
            continue
        j = int(m.group(3)) if m.group(3) else (ab_datum.year if ab_datum else date.today().year)
        d = _datum(int(m.group(1)), mon, j)
        if d and not m.group(3) and ab_datum and d < ab_datum:
            d = _datum(int(m.group(1)), mon, j + 1)
        out.append(d)
    return [d for d in out if d]


def _positionen(zeilen: list, tage=()) -> list:
    """[(titel, menge, tag)] in Reihenfolge. Eine Position beginnt mit ihrer laufenden
    Nummer, gefolgt vom Titel (keine Zahl, keine Einheit). `tag` ist der Termintag,
    unter dessen Überschrift („06.12.2026“) die Position steht, sonst None (= alle Tage)."""
    tage = set(tage)
    # Erst ab dem Tabellenkopf suchen – die Einleitung nennt die Tage auch schon
    out, nr, i, tag = [], 1, (zeilen.index("Pos.") if "Pos." in zeilen else 0), None
    while i < len(zeilen) - 1:
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", zeilen[i])
        if m:
            d = _datum(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d in tage:
                tag = d
        if zeilen[i] == str(nr) and zeilen[i + 1] and not _MENGE.match(zeilen[i + 1]) \
                and not _EINHEIT.match(zeilen[i + 1]) and not _BETRAG.match(zeilen[i + 1]):
            titel, menge = zeilen[i + 1], None
            for k in range(i + 2, min(i + 40, len(zeilen) - 1)):
                if _MENGE.match(zeilen[k]) and _EINHEIT.match(zeilen[k + 1]):
                    menge = float(zeilen[k].replace(",", "."))
                    break
            out.append((titel, menge, tag))
            nr += 1
        i += 1
    return out


def _teamer(titel: str, menge):
    """Teamer pro Tag aus „2 x 3 Knallfrosch - Teamer“ (→ 3), „3 Kindsalabim-Teamer“
    (→ 3), sonst die Menge („Kindsalabim - Teamer Tagessatz“, 1 Tagessatz → 1)."""
    vorn = titel[:titel.lower().index("teamer")]
    m = re.search(r"(\d+)\s*x\s*(\d+)", vorn)
    if m:
        return int(m.group(2))
    m = re.match(r"\s*(\d+)\b", vorn)
    if m:
        return int(m.group(1))
    return int(menge) if menge else None


def _aktion(titel: str, produkte: list):
    """Gebuchte Aktion zum Positionstitel; die längste passende Bezeichnung gewinnt
    („Mini Mitmachzirkus“ vor „Mitmachzirkus“, „Spieleland U3“ → „U3 Spieleland“)."""
    t = _norm(titel)
    kandidaten = sorted(((b, p) for p in produkte for b in (p, *_ALIAS.get(p, ()))),
                        key=lambda x: -len(_norm(x[0])))
    for begriff, produkt in kandidaten:
        if _norm(begriff) and _norm(begriff) in t:
            return produkt
    return None


def auslesen(pdf_bytes: bytes, produkte: list, kuenstler_aktionen: set) -> dict:
    """Ergebnis fürs Formular. Felder, die nicht sicher gelesen wurden, fehlen."""
    z = _zeilen(pdf_bytes)
    text = "\n".join(z)
    erg = {"hinweise": []}
    erg["marke"] = "Knallfrosch" if "knallfrosch" in text[:300].lower() else "Kindsalabim"
    m = re.search(r"\b(AB\d{3,})\b", text)
    if m:
        erg["ab_nummer"] = m.group(1)

    # AB-Datum (für Termine ohne Jahr): erstes Datum nach der Zeile „Datum:“
    ab_datum = None
    if "Datum:" in z:
        for w in z[z.index("Datum:"):z.index("Datum:") + 8]:
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", w):
                ab_datum = _datum(int(w[:2]), int(w[3:5]), int(w[6:]))
                break

    # Empfänger: die Zeilen nach der Absenderzeile „…, Charlottenweg 55, 45289 (Essen)“
    for i, w in enumerate(z):
        if "Charlottenweg 55," in w:
            j = i + 1 if w.rstrip().endswith("Essen") else i + 2
            block = []
            for w2 in z[j:j + 6]:
                block.append(w2)
                if re.match(r"^\d{4,5}\s+\S", w2):
                    break
            if len(block) >= 3 and re.match(r"^\d{4,5}\s+\S", block[-1]):
                erg["kunde_firma"] = block[0]
                erg["kunde_adresse"] = f"{block[-2]}, {block[-1]}"
            break

    # Einleitung: zwischen „Wir danken …“ und dem Kopf (Auftragsnr./Pos.)
    tage = []
    if any(w.startswith("Wir danken") for w in z):
        s = next(i for i, w in enumerate(z) if w.startswith("Wir danken")) + 1
        ende = next((i for i in range(s, len(z)) if z[i] in ("Auftragsnr.:", "Pos.")), len(z))
        einl = z[s:ende]
        if einl:
            # „Kinderanimation, Weihnachtsfeier, 12.12.2026“: Anlass = zweites Stück
            # (Aykut 26.11.2026); ohne Komma oder mit Datum dort die ganze erste Zeile.
            teile = [t.strip() for t in einl[0].split(",")]
            zweites = teile[1] if len(teile) > 1 else ""
            erg["anlass"] = zweites if zweites and not re.search(r"\d", zweites) else teile[0]
        global_zeit = _zeitspanne(" ".join(einl))
        eigene = {}                       # Tag → Uhrzeit aus seiner eigenen Zeile
        for zeile in einl:
            spanne = _zeitspanne(zeile)
            for d in _tage_in_zeile(zeile, ab_datum):
                if d not in [t[0] for t in tage]:
                    tage.append((d, None))
                if spanne and d not in eigene:
                    eigene[d] = spanne
        tage = [(d, eigene.get(d) or global_zeit) for d, _ in tage]
    tage.sort(key=lambda t: t[0])
    if tage:
        erg["tage"] = [{"datum": d.isoformat(), "start": s[0] if s else "", "ende": s[1] if s else ""}
                       for d, s in tage]
    else:
        erg["hinweise"].append("Termin nicht gefunden – bitte Datum und Uhrzeit eintragen.")

    # Positionen → Aktionen, Teamer, Künstler. Gezählt wird je Termintag (Positionen unter
    # der Tages-Überschrift; ohne Überschrift gelten sie für alle Tage) – Aykut 26.11.2026.
    # Teamer = Summe der Teamer-Positionen des Tages + 1 je Glitzertattoos (macht ein
    # Teamer, kein Künstler); Künstler = 1 je Künstler-Aktion des Tages.
    aktionen, unbekannt = [], []
    teamer, kuenstler = {}, {}            # Tag (oder None) → Anzahl
    for titel, menge, tag in _positionen(z, [d for d, _ in tage]):
        klein = titel.lower()
        if "teamer" in klein:
            teamer[tag] = teamer.get(tag, 0) + (_teamer(titel, menge) or 0)
            continue
        if any(w in klein for w in _NEBENPOSTEN):
            continue
        p = _aktion(titel, produkte)
        if not p:
            unbekannt.append(titel)
            continue
        if p not in aktionen:
            aktionen.append(p)
        if p == "Glitzertattoos":
            teamer[tag] = teamer.get(tag, 0) + 1
        if p in kuenstler_aktionen:
            kuenstler[tag] = kuenstler.get(tag, 0) + 1
    erg["produkte"] = aktionen

    def je_tag(zaehler, d):
        return zaehler.get(None, 0) + zaehler.get(d, 0)
    if tage:
        for t, (d, _) in zip(erg["tage"], tage):
            t["teamer"], t["kuenstler"] = je_tag(teamer, d), je_tag(kuenstler, d)
        erg["anzahl_teamer"] = erg["tage"][0]["teamer"]
        erg["anzahl_kuenstler"] = erg["tage"][0]["kuenstler"]
    else:
        erg["anzahl_teamer"] = sum(teamer.values())
        erg["anzahl_kuenstler"] = sum(kuenstler.values())
    if unbekannt:
        erg["hinweise"].append("Nicht zugeordnet (bitte selbst ankreuzen): " + "; ".join(unbekannt))
    return erg
