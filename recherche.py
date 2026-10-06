"""Vertriebs-Recherche über die Claude-API mit Websuche.

Statt einer vierten App (ein Dienst mehr auf Render, eine Datenbank mehr, eine
Oberfläche mehr) läuft die Recherche hier im bestehenden Dienst: Das Websuche-Werkzeug
der Claude-API sucht serverseitig, wir bekommen Treffer samt Quelle zurück und legen
daraus Akquise-Kontakte an (Aykut 05.10.2026).

Zwei Regeln, die alles andere tragen:
- **Ohne Quelllink kein Kontakt.** Ein Sprachmodell erfindet plausible Firmen und
  Adressen; eine erfundene Zeile im Anschreiben wäre der teuerste Fehler.
- **Nur Funktionspostfächer** (info@, event@, marketing@). Personennamen ja, zur Anrede,
  aber keine personenbezogenen Adressen.

Modellwahl bewusst zweigeteilt (Aykuts Entscheidung): Die Fleißarbeit erledigt das
günstigere Sonnet, für die Einordnung lässt sich Opus einstellen.
"""
import json
import re
from datetime import datetime

import httpx

from config import get_config

MODELL_RECHERCHE = "claude-sonnet-5-5"     # Suchen und Daten herausziehen
MODELL_EINORDNUNG = "claude-opus-5-5"      # nur wenn ausdrücklich gewünscht

# Nachschub: Sinkt die Zahl der noch nicht angeschriebenen Kontakte unter diese Grenze,
# startet der Dauerauftrag von selbst. Ohne hinterlegten Dauerauftrag passiert nichts.
NACHSCHUB_GRENZE = 20
DAUERAUFTRAG_KEY = "recherche_dauerauftrag"

# Preise je 1 Mio. Token (Stand 10/2026). Nur zur Kostenanzeige; die Gebühren für die
# Websuche selbst kommen zusätzlich und stehen nicht in der Antwort.
PREISE = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

SYSTEM = """Du recherchierst Vertriebskontakte für Kindsalabim Kinderevents (Essen,
Einzugsgebiet Ruhrgebiet und Rheinland). Gesucht sind Organisationen, die Kinderprogramm
buchen oder auf Veranstaltungen anbieten müssen: Veranstalter von Stadt- und Familienfesten,
Freizeiteinrichtungen, und vor allem Firmen, die mit einem Stand auf solchen Festen stehen
(Wohnungsgesellschaften, Stadtwerke und Versorger, Sparkassen, Verkehrsbetriebe, Medienhäuser,
Krankenkassen) oder selbst Familienfeste für ihre Mitarbeitenden ausrichten.

Harte Regeln:
- Jede Zeile braucht einen echten Quelllink, auf dem die Angaben stehen. Ohne Quelle keine Zeile.
- Erfinde nichts. Kein Name, keine Adresse, keine Telefonnummer, die du nicht belegen kannst.
  Lieber zehn belegte Zeilen als fünfzig geratene.
- Nur Funktionspostfächer (info@, kontakt@, event@, marketing@). Keine personenbezogenen
  Mailadressen. Den Namen einer zuständigen Person darfst du nennen, er dient der Anrede.
- Nicht aufnehmen: Anwaltskanzleien, Krankenhäuser und Kliniken, Pflegedienste, Parteien und
  politische Gremien, Privatpersonen.
- Große Arbeitgeber sind ausdrücklich erwünscht, wenn sie ein eigenes Familienfest, ein
  Ferienprogramm oder ein Kinderbetreuungsangebot für Mitarbeiterkinder haben. Dann ist der
  Anlass dieses eigene Fest, nicht ein Stadtfest.

Antworte ausschließlich mit JSON nach diesem Schema, ohne weiteren Text:
{"kontakte": [{"organisation": "...", "art": "Veranstalter|Aussteller|Firma",
"ort": "...", "email": "...", "ansprechpartner": "", "quelle": "https://...",
"anlass": "...", "ansprachemonat": 1-12, "branche": "...", "beleg": "geprüft|snippet",
"warum": "ein Satz"}]}"""


def _kosten_cent(modell: str, usage: dict) -> float:
    ein, aus = PREISE.get(modell, PREISE[MODELL_RECHERCHE])
    i = usage.get("input_tokens") or 0
    o = usage.get("output_tokens") or 0
    return round((i / 1_000_000 * ein + o / 1_000_000 * aus) * 100, 2)


def _suchen_gezaehlt(usage: dict) -> int:
    return (usage.get("server_tool_use") or {}).get("web_search_requests") or 0


def _json_aus_text(text: str) -> dict:
    """Das Modell antwortet mit JSON, manchmal in einem Codeblock."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, ende = text.find("{"), text.rfind("}")
        if start >= 0 and ende > start:
            try:
                return json.loads(text[start:ende + 1])
            except ValueError:
                pass
    return {"kontakte": []}


def suchen(auftrag: str, modell: str = MODELL_RECHERCHE, max_suchen: int = 12) -> dict:
    """Einen Rechercheauftrag ausführen. Rückgabe: kontakte, suchen, kosten_cent, meldung."""
    key = get_config().get("anthropic_api_key")
    if not key:
        return {"kontakte": [], "suchen": 0, "kosten_cent": 0.0,
                "meldung": "Kein Anthropic-Schlüssel hinterlegt (ANTHROPIC_API_KEY)."}
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": modell, "max_tokens": 16000, "system": SYSTEM,
                  "tools": [{"type": "web_search_20260209", "name": "web_search",
                             "max_uses": max_suchen}],
                  "messages": [{"role": "user", "content": auftrag}]},
            timeout=600,   # Websuche über mehrere Seiten braucht Minuten
        )
        r.raise_for_status()
        daten_roh = r.json()
    except Exception as e:
        return {"kontakte": [], "suchen": 0, "kosten_cent": 0.0,
                "meldung": f"Recherche fehlgeschlagen: {str(e)[:200]}"}

    text = "".join(b.get("text", "") for b in daten_roh.get("content", [])
                   if b.get("type") == "text")
    usage = daten_roh.get("usage") or {}
    daten = _json_aus_text(text)
    return {"kontakte": daten.get("kontakte") or [],
            "suchen": _suchen_gezaehlt(usage),
            "kosten_cent": _kosten_cent(modell, usage),
            "meldung": ""}


def uebernehmen(db, treffer: list, auftrag_id: int = None) -> tuple:
    """Treffer als Akquise-Kontakte anlegen. Rückgabe (neu, verworfen).

    Verworfen wird, was keine Quelle hat, gesperrt ist oder die Organisation schon kennt.
    Die Sperrliste greift also schon beim Anlegen, nicht erst beim Versand."""
    import vertrieb
    from sqlalchemy import func
    from models import Kunde
    neu = verworfen = 0
    for t in treffer:
        firma = (t.get("organisation") or "").strip()
        quelle = (t.get("quelle") or "").strip()
        mail = (t.get("email") or "").strip()
        if not firma or not quelle.startswith("http"):
            verworfen += 1
            continue
        if mail and "@" not in mail:
            mail = ""
        darf, _grund = vertrieb.darf_kontaktieren(db, email=mail, firma=firma)
        if not darf:
            verworfen += 1
            continue
        if db.query(Kunde).filter(func.lower(Kunde.firma) == firma.lower()).first():
            verworfen += 1
            continue
        monat = t.get("ansprachemonat")
        db.add(Kunde(
            firma=firma, email=mail or None, ort=(t.get("ort") or "").strip() or None,
            ansprechpartner=(t.get("ansprechpartner") or "").strip() or None,
            herkunft="akquise", pipeline_status="lead",
            akquise_art=(t.get("art") or "").strip() or None,
            quelle=quelle, anlass=(t.get("anlass") or "").strip() or None,
            ansprachemonat=monat if isinstance(monat, int) and 1 <= monat <= 12 else None,
            branche=(t.get("branche") or "").strip() or None,
            quelle_beleg=(t.get("beleg") or "").strip().lower() or None,
            notizen=(t.get("warum") or "").strip() or None,
            recherche_id=auftrag_id,
            erstellt_am=datetime.now().isoformat(timespec="seconds")))
        neu += 1
    db.commit()
    return neu, verworfen


def offene_leads(db) -> int:
    """Recherchierte Kontakte, die noch nicht angeschrieben sind."""
    from models import Kunde
    return (db.query(Kunde).filter(Kunde.herkunft == "akquise",
                                   Kunde.pipeline_status == "lead").count())


def auftrag_anlegen(db, auftrag: str, modell: str = MODELL_RECHERCHE,
                    automatisch: bool = False):
    from models import Rechercheauftrag
    a = Rechercheauftrag(auftrag=auftrag.strip(), modell=modell, status="offen",
                         automatisch=automatisch,
                         erstellt_am=datetime.now().isoformat(timespec="seconds"))
    db.add(a)
    db.commit()
    return a


def nachschub_pruefen(db):
    """Vom Cron aufgerufen: liegt der Vorrat unter der Grenze, einen Lauf anlegen.

    Ein zweiter Lauf wird nicht angelegt, solange noch einer offen ist oder läuft,
    sonst stapeln sich bei einem Fehler die Aufträge und damit die Kosten."""
    from models import Rechercheauftrag
    from notifications import get_setting
    dauerauftrag = (get_setting(db, DAUERAUFTRAG_KEY, "") or "").strip()
    if not dauerauftrag:
        return None
    if offene_leads(db) >= NACHSCHUB_GRENZE:
        return None
    laeuft = (db.query(Rechercheauftrag)
              .filter(Rechercheauftrag.status.in_(("offen", "laeuft"))).first())
    if laeuft:
        return None
    return auftrag_anlegen(db, dauerauftrag, MODELL_RECHERCHE, automatisch=True)


def auftrag_ausfuehren(auftrag_id: int):
    """Hintergrund-Lauf: sucht, übernimmt, schreibt Ergebnis und Kosten an den Auftrag."""
    from database import SessionLocal
    from models import Rechercheauftrag
    db = SessionLocal()
    try:
        a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == auftrag_id).first()
        if not a or a.status not in ("offen", "fehler"):
            return
        a.status = "laeuft"
        db.commit()
        ergebnis = suchen(a.auftrag, a.modell or MODELL_RECHERCHE)
        neu, verworfen = uebernehmen(db, ergebnis["kontakte"], a.id)
        a.anzahl, a.verworfen = neu, verworfen
        a.suchen, a.kosten_cent = ergebnis["suchen"], ergebnis["kosten_cent"]
        a.meldung = ergebnis["meldung"] or None
        a.status = "fehler" if ergebnis["meldung"] else "fertig"
        a.fertig_am = datetime.now().isoformat(timespec="seconds")
        db.commit()
        if a.status == "fertig":
            from notifications import notify
            notify(db, "recherche_fertig", f"Recherche fertig: {neu} neue Kontakte",
                   f"Auftrag: {a.auftrag[:120]} / {neu} neue Kontakte, "
                   f"{verworfen} verworfen, {a.suchen} Suchen, "
                   f"{a.kosten_cent:.0f} Cent.", "/admin/crm/akquise")
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"[RECHERCHE] Auftrag {auftrag_id} fehlgeschlagen: {e}")
    finally:
        db.close()
