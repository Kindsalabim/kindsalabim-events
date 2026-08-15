# -*- coding: utf-8 -*-
"""Scheinselbstständigkeits-Scoring nach dem ScoringSystem V7 von Dr. Grunewald.

Quelle: ScoringSystemV7.xlsx (Unterlagen Dr. Grunewald, Stand 03/2025).
Logik der Excel: je Kriterium eine Ausprägung 0–3 („trifft nicht zu" … „trifft
voll zu"), Score = Gewichtung × Ausprägung, GesamtScore = Summe. Kritische
Schwelle laut Excel: 130 Punkte (darunter „Go", ab 130 „NoGo").

⚠️ Zwei Zellen sind in der Original-Excel verrutscht (B10 zeigt „NoGo(-)",
B14 zeigt „ScoringSystem"). Die beiden Kriterien wurden aus den übrigen in der
Datei vorhandenen Texten plausibel rekonstruiert und sind unten markiert –
bei Gelegenheit mit Dr. Grunewald bzw. der Original-Excel in Excel abgleichen.
"""
import json

# (key, Bezeichnung, Gewichtung) – Reihenfolge und Gewichte wie in der Excel
KRITERIEN = [
    ("weisung",        "Weisungsgebundenheit", 20),
    ("eingliederung",  "Eingliederung in die Betriebsorganisation", 20),
    ("persoenlich",    "Persönliche Leistungserbringungspflicht", 20),
    ("auftreten",      "Kein unternehmerisches Auftreten (Website, XING etc.)", 15),
    ("identisch",      "Tätigkeit identisch mit festangestellten Mitarbeitern", 15),  # rekonstruiert (Excel-Zelle verrutscht)
    ("ort",            "Vorgabe des Orts der Tätigkeit / keine Remote-Tätigkeit", 15),
    ("stundensatz",    "Stundensatz kleiner 40 €", 15),
    ("kapital",        "Kein eigenes Kapital (Home-Office, PKW etc.)", 15),
    ("zeiterfassung",  "In ein Zeiterfassungssystem eingebunden", 10),  # rekonstruiert (Excel-Zelle verrutscht)
    ("arbeitsmittel",  "Keine eigenen Arbeitsmittel", 10),
    ("arbeitsplatz",   "Fester Arbeitsplatz beim Auftraggeber/Kunden", 5),
    ("verguenstigung", "Mitarbeiter-Vergünstigungen", 5),
    ("haftung",        "Keine persönliche Haftung", 5),
    ("briefpapier",    "Kein eigenes Briefpapier / keine Visitenkarten", 5),
    ("meetings",       "Obligatorische Meetings", 5),
    ("honorar",        "Vorgegebenes Honorar", 1),
    ("email",          "Keine eigene E-Mail-Adresse", 1),
    ("fortbildung",    "Keine Fortbildungen auf eigene Kosten", 1),
    ("zertifikat",     "Keine Zertifizierungen auf eigene Kosten", 1),
    ("dauer",          "Dauer der Tätigkeit über 1 Jahr", 1),
]

AUSPRAEGUNGEN = ["0 – trifft nicht zu", "1 – trifft wenig zu",
                 "2 – trifft überwiegend zu", "3 – trifft voll zu"]

KRITISCH = 130                                   # NoGo-Schwelle laut Excel („KritischerScore")
WARN = 100                                       # eigene Warnzone (nicht aus der Excel)
MAX_SCORE = 3 * sum(g for _, _, g in KRITERIEN)  # 555


def parse_werte(scoring_json) -> dict:
    """JSON-Spalte → {key: 0-3}; unbekannte Keys/Werte werden ignoriert."""
    try:
        roh = json.loads(scoring_json or "{}")
    except (ValueError, TypeError):
        return {}
    keys = {k for k, _, _ in KRITERIEN}
    werte = {}
    for k, v in (roh.items() if isinstance(roh, dict) else []):
        if k in keys:
            try:
                werte[k] = min(3, max(0, int(v)))
            except (ValueError, TypeError):
                pass
    return werte


def gesamt_score(werte: dict) -> int:
    return sum(g * werte.get(k, 0) for k, _, g in KRITERIEN)


def ampel(score: int) -> str:
    """'gruen' | 'gelb' | 'rot' – rot = NoGo-Schwelle der Excel erreicht."""
    if score >= KRITISCH:
        return "rot"
    if score >= WARN:
        return "gelb"
    return "gruen"
