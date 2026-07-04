"""Gemeinsame Auswahllisten & Formatierungs-Helfer für Formulare/Templates."""
import re

# Uhrzeiten 07:00–24:00 in 15-Minuten-Schritten (für Dropdowns)
ZEITEN = [f"{h:02d}:{m:02d}" for h in range(7, 24) for m in (0, 15, 30, 45)] + ["24:00"]

# Rechnungsanschrift je Marke – EINE Quelle für Portal, Briefing-Mail und Briefing-PDF.
RECHNUNGS_ANSCHRIFT = {
    "Knallfrosch": {
        "zeilen": ["Malca & Akmanoglu GbR", "Knallfrosch Kinderevents",
                   "Charlottenweg 55", "45289 Essen"],
        "mail": "personal@knallfrosch-kinderevents.de",
    },
    "Kindsalabim": {
        "zeilen": ["Aykut Malca", "Kindsalabim Kinderevents",
                   "Charlottenweg 55", "45289 Essen"],
        "mail": "info@kindsalabim.de",
    },
}


def rechnung_anschrift(marke: str) -> dict:
    return RECHNUNGS_ANSCHRIFT.get(marke or "", RECHNUNGS_ANSCHRIFT["Kindsalabim"])


# Künstler-Sparte (Dienstleister-Profil) → Anzeige-Label im Briefing.
# "Sonstiges" bekommt bewusst kein Label (sagt dem Team nichts).
SPARTE_BRIEFING = {
    "Kinderschminke":    "Kinderschminken",
    "Ballonkünstler":    "Ballonmodellage",
    "Schminke + Ballon": "Kinderschminken + Ballonmodellage",
    "Showact":           "Showact",
    "Walkact":           "Walkact",
}


def sparte_label(dienstleister) -> str:
    """Briefing-Zusatz wie „(Ballonmodellage)" aus der Profil-Sparte; '' wenn keine."""
    s = SPARTE_BRIEFING.get(getattr(dienstleister, "kuenstler_sparte", None) or "")
    return f"({s})" if s else ""


# Standard-Regeln für Seite 2 des Briefings – übernommen aus der bewährten
# „Briefing 2.0"-Vorlage (Stand 07/2026, laut Aykut weiterhin gültig). Editierbar
# unter /admin/einstellungen; "## " beginnt eine neue Box, {MARKE} wird durch den
# Markennamen ersetzt.
BRIEFING_REGELN_DEFAULT = """## Grundlegende Regelungen
Bitte nicht einzeln zum Ansprechpartner gehen/anrufen. Nur die Teamleitung kontaktiert den Kunden.
Rauchverbot im Aktionsbereich und in unmittelbarer Nähe!
Zum Abschluss der Aktion bitte beim Ansprechpartner verabschieden. (Teamleitung)
Bitte kurzes Feedback per WhatsApp nach Abschluss der Aktion. (Teamleitung)
Möglichst 2-3 Fotos von der Aktion für Social Media machen. (Teamleitung)
Evtl. anfallende Parkgebühren können uns in Rechnung gestellt werden. (Beleg mitschicken)
Für die Versteuerung des Einkommens sind Auftragnehmer selbst verantwortlich.
Der Auftragnehmer verpflichtet sich, keinem Dritten Auskunft über das Honorar zu geben.
Als selbstständiger Dienstleister solltest du über eine gewerbliche Haftpflichtversicherung oder eine entsprechend erweiterte Haftpflicht verfügen.
## Instaff / Externe Agentur
Stundenzettel unterschreibt die Teamleitung.
Wir treten vor dem Kunden als „{MARKE}“ auf. In Anwesenheit des Kunden bitte keine Drittagentur erwähnen.
## Künstler (Kinderschminken, Ballonmodellage o.ä.)
Eigenwerbung ist nicht gestattet! Bei Rückfragen bitte auf {MARKE} verweisen.
Bei Ausfall sorgt der Künstler selbst für Ersatz!
Bitte Trinkgeldkasse o.ä. nicht ohne vorherige Absprache aufstellen."""

_MARKE_NAME = {"Knallfrosch": "Knallfrosch Kinderevents", "Kindsalabim": "Kindsalabim"}


def regeln_abschnitte(text: str, marke: str = "") -> list:
    """Regeln-Freitext → [(box_titel, [punkte])]. Zeilen mit „## " beginnen eine neue
    Box; führende Nummerierungen/Spiegelstriche werden entfernt (der Pfeil übernimmt);
    {MARKE} wird durch den Markennamen ersetzt. Text ohne „## " → eine Box."""
    text = (text or "").replace("{MARKE}", _MARKE_NAME.get(marke or "", marke or "…"))
    abschnitte, titel, punkte = [], "Grundlegende Regelungen", []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("## "):
            if punkte:
                abschnitte.append((titel, punkte))
            titel, punkte = ln[3:].strip() or "Regeln", []
            continue
        punkte.append(re.sub(r"^(\d+[.)]|[-•*])\s*", "", ln))
    if punkte:
        abschnitte.append((titel, punkte))
    return abschnitte


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
