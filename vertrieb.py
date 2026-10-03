"""Vertrieb: Sperrliste, Not-Aus und Protokoll.

Kaltakquise ist in Deutschland heikel (§ 7 UWG). Aykut geht das Risiko bewusst ein,
aber mit Schutz (04.10.2026). Der Unterschied zur Akquise von Hand: Eine Maschine
vergisst nicht, weiß aber auch nicht von selbst, wen sie nie wieder anschreiben darf.
Deshalb gilt:

- Es gibt GENAU EINE Stelle, die das entscheidet: `darf_kontaktieren()`.
- Kein Sprachmodell entscheidet über eine Sperre, es schreibt nur Entwürfe.
- Gesperrt wird auf vier Ebenen, nicht nur per E-Mail-Adresse: Dieselbe Firma meldet
  sich sonst über eine andere Adresse wieder als frischer Lead.
- Kommt Anwaltspost, stoppt der Not-Aus den gesamten automatischen Versand, bis Aykut
  ihn von Hand wieder freigibt.
"""
import re
import unicodedata
from datetime import datetime

NOTAUS_KEY = "vertrieb_versand_gestoppt"
EBENEN = ("adresse", "domain", "unternehmen", "person")
GRUENDE = [("widerspruch", "Widerspruch des Empfängers"),
           ("abmahnung", "Abmahnung / Anwaltsschreiben"),
           ("unterlassung", "Unterlassungsvertrag"),
           ("eigene", "Eigene Entscheidung")]

_RECHTSFORM = re.compile(
    r"\b(gmbh|mbh|ggmbh|ug|haftungsbeschr\w*|co\s?kg|kg|ohg|gbr|ag|e\s?v|ev|"
    r"gemeinn\w*|und\s?co)\b")


def normalisieren(wert: str) -> str:
    """Kleinschreibung, Umlaute vereinheitlicht, Rechtsform und Satzzeichen raus.
    Damit greift die Sperre auch bei „Muster GmbH" vs. „muster-gmbh"."""
    t = unicodedata.normalize("NFKD", (wert or "").lower().strip())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("ß", "ss")
    t = re.sub(r"[^a-z0-9@. ]+", " ", t)
    t = _RECHTSFORM.sub(" ", t)
    return " ".join(t.split())


def domain_von(email: str) -> str:
    teil = (email or "").strip().lower().rsplit("@", 1)
    return teil[1] if len(teil) == 2 else ""


def _sperren(db):
    from models import VertriebSperre
    return db.query(VertriebSperre).all()


def versand_gestoppt(db) -> bool:
    """Not-Aus: Nach Anwaltspost steht der automatische Versand still."""
    from notifications import get_setting
    return get_setting(db, NOTAUS_KEY, "") == "1"


def versand_stoppen(db, stoppen: bool = True):
    from notifications import set_setting
    set_setting(db, NOTAUS_KEY, "1" if stoppen else "0")
    db.commit()


def darf_kontaktieren(db, email: str = "", firma: str = "", person: str = "") -> tuple:
    """Die einzige Stelle, an der entschieden wird. Rückgabe (darf, grund).

    `grund` ist leer, wenn alles frei ist, sonst ein Satz für die Oberfläche.
    Jeder Versandweg MUSS hier durch – es gibt keinen zweiten."""
    if versand_gestoppt(db):
        return False, "Der Vertriebsversand ist gestoppt (Not-Aus nach Anwaltspost)."
    email_n = normalisieren(email)
    domain = domain_von(email)
    firma_n, person_n = normalisieren(firma), normalisieren(person)
    for s in _sperren(db):
        wert = s.wert or ""
        if not wert:
            continue
        if s.ebene == "adresse" and email_n and wert == email_n:
            return False, f"Diese Adresse ist gesperrt ({s.grund or 'Sperre'})."
        if s.ebene == "domain" and domain and (domain == wert or domain.endswith("." + wert)):
            return False, f"Die Domain {wert} ist gesperrt ({s.grund or 'Sperre'})."
        if s.ebene == "unternehmen" and firma_n and (wert in firma_n or firma_n in wert):
            return False, f"Dieses Unternehmen ist gesperrt ({s.grund or 'Sperre'})."
        if s.ebene == "person" and person_n and (wert in person_n or person_n in wert):
            return False, f"Diese Person ist gesperrt ({s.grund or 'Sperre'})."
    return True, ""


def sperren(db, ebene: str, wert: str, grund: str = "widerspruch", notiz: str = ""):
    """Sperre eintragen. Doppelte Einträge werden still übersprungen."""
    from models import VertriebSperre
    if ebene not in EBENEN or not (wert or "").strip():
        return None
    norm = normalisieren(wert) if ebene != "domain" else (wert or "").strip().lower().lstrip("@")
    vorhanden = db.query(VertriebSperre).filter(VertriebSperre.ebene == ebene,
                                                VertriebSperre.wert == norm).first()
    if vorhanden:
        return vorhanden
    s = VertriebSperre(ebene=ebene, wert=norm, anzeige=wert.strip(), grund=grund,
                       notiz=notiz or None,
                       erstellt_am=datetime.now().isoformat(timespec="seconds"))
    db.add(s)
    db.commit()
    return s


def sperren_fuer_kunde(db, kunde, grund: str = "widerspruch", notiz: str = ""):
    """Ein „Bitte nie wieder" gilt für Adresse, Domain und Unternehmen zugleich."""
    eingetragen = []
    if kunde.email:
        eingetragen.append(sperren(db, "adresse", kunde.email, grund, notiz))
        d = domain_von(kunde.email)
        if d and not any(d.endswith(frei) for frei in
                         ("gmail.com", "gmx.de", "web.de", "t-online.de", "outlook.com",
                          "hotmail.com", "yahoo.de", "icloud.com")):
            eingetragen.append(sperren(db, "domain", d, grund, notiz))
    if kunde.firma:
        eingetragen.append(sperren(db, "unternehmen", kunde.firma, grund, notiz))
    return [e for e in eingetragen if e]


def protokollieren(db, kunde, weg: str, betreff: str = "", empfaenger: str = ""):
    """Jede Ansprache festhalten: im Streitfall der Nachweis."""
    from models import VertriebKontaktLog
    eintrag = VertriebKontaktLog(
        kunde_id=getattr(kunde, "id", None),
        empfaenger=empfaenger or getattr(kunde, "email", "") or "",
        weg=weg, betreff=betreff or None,
        quelle=getattr(kunde, "quelle", None),
        erstellt_am=datetime.now().isoformat(timespec="seconds"))
    db.add(eintrag)
    db.commit()
    return eintrag
