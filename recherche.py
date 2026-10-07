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
- **Ohne Mailadresse keine Zeile.** Schau auf der Impressum-, Kontakt-, Presse-, Team-
  oder Ansprechpartner-Seite nach. Findest du nirgends eine Adresse, lass die
  Organisation weg, auch wenn der Anlass gut passt.
- **Suche bevorzugt die persönliche Adresse der zuständigen Person** (Marketing,
  Kommunikation, Veranstaltungen, Presse oder Personal). Eine Mail an info@ landet in
  einem Servicepostfach und erreicht die Person meist nicht. Setze dann
  "mail_art": "person" und trage den Namen in "ansprechpartner" ein.
- **Nur Adressen, die wörtlich auf einer Seite stehen.** Bilde niemals eine Adresse aus
  einem Muster wie vorname.nachname@firma.de, auch wenn andere Adressen der Firma so
  aussehen. Eine geratene Adresse ist ein Rückläufer und schadet uns.
- **Name und Adresse müssen von derselben Seite stammen.** Sonst steht der Name der
  einen Person neben der Adresse einer anderen.
- Findest du keine persönliche Adresse, nimm ein Funktionspostfach (info@, kontakt@,
  event@, marketing@, presse@), setze "mail_art": "funktion" und lass
  "ansprechpartner" dann **leer**. An ein Sammelpostfach wird niemand mit Namen
  angesprochen.
- Nicht aufnehmen: Anwaltskanzleien, Krankenhäuser und Kliniken, Pflegedienste, Parteien und
  politische Gremien, Privatpersonen.
- Große Arbeitgeber sind ausdrücklich erwünscht, wenn sie ein eigenes Familienfest, ein
  Ferienprogramm oder ein Kinderbetreuungsangebot für Mitarbeiterkinder haben. Dann ist der
  Anlass dieses eigene Fest, nicht ein Stadtfest.

Antworte ausschließlich mit JSON nach diesem Schema, ohne weiteren Text:
{"kontakte": [{"organisation": "...", "art": "Veranstalter|Aussteller|Firma",
"ort": "...", "email": "...", "mail_art": "person|funktion", "ansprechpartner": "",
"funktion": "", "quelle": "https://...", "quelle_mail": "https://...",
"anlass": "...", "ansprachemonat": 1-12, "branche": "...", "beleg": "geprüft|snippet",
"warum": "ein Satz"}],
"nicht_aufgenommen": [{"organisation": "...", "grund": "ein Satz"}]}

"quelle_mail" ist die Seite, auf der die Mailadresse steht. "funktion" ist die Rolle der
Person laut Quelle, zum Beispiel „Leiterin Unternehmenskommunikation".

**"nicht_aufgenommen" ist Pflicht, wenn im Auftrag Organisationen namentlich genannt
sind.** Jede genannte Organisation, die nicht in "kontakte" steht, braucht dort eine
Zeile mit dem konkreten Grund, zum Beispiel „kein eigenes Familienfest belegt, nur
Sponsoring" oder „Fest belegt, aber keine Mailadresse auf der Seite gefunden". Nenne
den Grund, der tatsächlich ausschlaggebend war, nicht eine allgemeine Floskel."""


def _kosten_cent(modell: str, usage: dict) -> float:
    ein, aus = PREISE.get(modell, PREISE[MODELL_RECHERCHE])
    i = usage.get("input_tokens") or 0
    o = usage.get("output_tokens") or 0
    return round((i / 1_000_000 * ein + o / 1_000_000 * aus) * 100, 2)


def _suchen_gezaehlt(usage: dict) -> int:
    return (usage.get("server_tool_use") or {}).get("web_search_requests") or 0


def _json_aus_text(text: str):
    """JSON aus der Modellantwort lösen, manchmal steckt es in einem Codeblock.

    Gibt None zurück, wenn sich nichts lesen lässt. Das ist wichtig: ein leeres
    Ergebnis und eine unlesbare Antwort sahen vorher gleich aus (Aykut 07.10.2026,
    ein Lauf meldete „0 neu, 0 verworfen" ohne Hinweis auf die Ursache)."""
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
    return None


def _such_fehler(inhalt: list) -> list:
    """Fehler des Websuche-Werkzeugs. Die kommen mit HTTP 200 als Ergebnisblock
    zurück, lösen also keine Ausnahme aus und wären sonst unsichtbar."""
    fehler = []
    for b in inhalt or []:
        if b.get("type") != "web_search_tool_result":
            continue
        c = b.get("content")
        if isinstance(c, dict) and c.get("error_code"):
            fehler.append(c["error_code"])
    return fehler


def suchen(auftrag: str, modell: str = MODELL_RECHERCHE, max_suchen: int = 12,
           max_fortsetzungen: int = 5) -> dict:
    """Einen Rechercheauftrag ausführen. Rückgabe: kontakte, suchen, kosten_cent, meldung.

    Die Websuche läuft serverseitig in einer eigenen Schleife. Nach zehn Durchläufen
    hält die API mit `stop_reason: "pause_turn"` an und erwartet, dass wir die Antwort
    zurückschicken und weitermachen. Ohne das kam bei zehn Firmen gar kein Text und
    damit kein Kontakt an (Aykut 07.10.2026, Lauf meldete „0 neu, 0 verworfen")."""
    key = get_config().get("anthropic_api_key")
    if not key:
        return {"kontakte": [], "suchen": 0, "kosten_cent": 0.0, "fehler": True,
                "meldung": "Kein Anthropic-Schlüssel hinterlegt (ANTHROPIC_API_KEY)."}

    nachrichten = [{"role": "user", "content": auftrag}]
    ein = aus = anzahl_suchen = 0
    text = letzter_text = ""
    ende = ""
    such_fehler = []
    for _runde in range(max_fortsetzungen + 1):
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": modell, "max_tokens": 16000, "system": SYSTEM,
                      "tools": [{"type": "web_search_20260209", "name": "web_search",
                                 "max_uses": max_suchen}],
                      "messages": nachrichten},
                timeout=600,   # Websuche über mehrere Seiten braucht Minuten
            )
            r.raise_for_status()
            daten_roh = r.json()
        except Exception as e:
            return {"kontakte": [], "suchen": anzahl_suchen,
                    "kosten_cent": _kosten_cent(modell, {"input_tokens": ein,
                                                         "output_tokens": aus}),
                    "fehler": True,
                    "meldung": f"Recherche fehlgeschlagen: {str(e)[:200]}"}

        inhalt = daten_roh.get("content") or []
        usage = daten_roh.get("usage") or {}
        ein += usage.get("input_tokens") or 0
        aus += usage.get("output_tokens") or 0
        anzahl_suchen += _suchen_gezaehlt(usage)
        such_fehler += _such_fehler(inhalt)
        letzter_text = "".join(b.get("text", "") for b in inhalt if b.get("type") == "text")
        text += letzter_text
        ende = daten_roh.get("stop_reason") or ""
        if ende != "pause_turn":
            break
        # Antwort unverändert zurückschicken, der Server macht von selbst weiter.
        # Kein zusätzliches „Weiter" dazwischen, das würde die Fortsetzung stören.
        nachrichten.append({"role": "assistant", "content": inhalt})

    ergebnis = {"kontakte": [], "suchen": anzahl_suchen, "meldung": "", "fehler": False,
                "kosten_cent": _kosten_cent(modell, {"input_tokens": ein,
                                                     "output_tokens": aus})}
    hinweis_suche = (" Das Suchwerkzeug meldete: " + ", ".join(sorted(set(such_fehler)))
                     if such_fehler else "")

    if ende == "pause_turn":
        ergebnis["meldung"] = ("Die Suche war auch nach "
                               f"{max_fortsetzungen} Fortsetzungen nicht fertig. Nimm "
                               "weniger Firmen pro Lauf, etwa fünf." + hinweis_suche)
        ergebnis["fehler"] = True
        return ergebnis

    # Jeder Fall bekommt eine eigene Meldung, sonst sucht man im Dunkeln.
    if ende == "max_tokens":
        ergebnis["meldung"] = ("Die Antwort wurde abgeschnitten (Längenlimit). Nimm weniger "
                              "Firmen pro Lauf, etwa fünf." + hinweis_suche)
        ergebnis["fehler"] = True
        return ergebnis
    if not text.strip():
        ergebnis["meldung"] = (f"Das Modell hat keinen Text geliefert (Abbruchgrund: "
                               f"{ende or 'unbekannt'})." + hinweis_suche)
        ergebnis["fehler"] = True
        return ergebnis

    # Das JSON steht in der letzten Runde; die früheren enthalten nur Zwischentext.
    daten = _json_aus_text(letzter_text) or _json_aus_text(text)
    if daten is None:
        ergebnis["meldung"] = ("Die Antwort war kein lesbares JSON. Anfang der Antwort: "
                               + " ".join(text.split())[:300] + hinweis_suche)
        ergebnis["fehler"] = True
        return ergebnis

    ergebnis["kontakte"] = daten.get("kontakte") or []
    # Warum eine genannte Firma nicht dabei ist, ist die wichtigste Information eines
    # Laufs: sie unterscheidet „schlechte Liste" von „schlechter Auftrag".
    abgelehnt = [f"{(z.get('organisation') or '?').strip()}: "
                 f"{(z.get('grund') or 'ohne Grund').strip()}"
                 for z in (daten.get("nicht_aufgenommen") or [])
                 if isinstance(z, dict)]
    ergebnis["nicht_aufgenommen"] = abgelehnt
    if not ergebnis["kontakte"]:
        begruendung = "; ".join(abgelehnt) or (daten.get("hinweis") or "").strip()
        ergebnis["meldung"] = ("Das Modell hat keine Organisation aufgenommen. "
                               + (begruendung[:600] if begruendung else
                                  "Vermutlich fand es weder Anlass noch Postfach belegt."))
    return ergebnis


# Postfächer, hinter denen keine einzelne Person steckt. Eine Namensanrede an so eine
# Adresse verrät sofort die Maschine: bei der Bogestra arbeiten zwanzig Schmidts.
_SAMMELPOSTFACH = ("info", "kontakt", "contact", "office", "mail", "email", "service",
                   "zentrale", "verwaltung", "presse", "pressestelle", "marketing",
                   "event", "events", "veranstaltungen", "kommunikation", "team",
                   "sekretariat", "empfang", "anfrage", "anfragen", "post", "buero",
                   "hello", "moin", "willkommen", "bewerbung", "personal", "hr",
                   "stadtmarketing", "tourismus", "noreply", "no-reply")


def _adresse_einordnen(mail: str, treffer: dict) -> tuple:
    """Entscheidet (mail_art, ansprechpartner) und hält beides konsistent.

    Die Regel ist eine Kopplung, keine Vorliebe (Aykut 07.10.2026): persönliche Adresse
    heißt persönliche Anrede, Sammelpostfach heißt keine Namensanrede. Was das Modell
    behauptet, wird dabei an der Adresse selbst geprüft."""
    person = (treffer.get("ansprechpartner") or "").strip()
    lokal = mail.split("@", 1)[0].lower()
    ist_sammel = (lokal in _SAMMELPOSTFACH
                  or any(lokal.startswith(p + "-") or lokal.startswith(p + ".")
                         for p in _SAMMELPOSTFACH))
    behauptet = (treffer.get("mail_art") or "").strip().lower()
    if ist_sammel or behauptet == "funktion" or not person:
        # Kein Name an ein Sammelpostfach, auch wenn das Modell einen mitgeliefert hat.
        return "funktion", ""
    return "person", person


def uebernehmen(db, treffer: list, auftrag_id: int = None, protokoll: list = None) -> tuple:
    """Treffer als Akquise-Kontakte anlegen. Rückgabe (neu, verworfen).

    Verworfen wird, was keine Quelle oder keine Mailadresse hat, gesperrt ist oder die
    Organisation schon kennt. Die Sperrliste greift also schon beim Anlegen, nicht erst
    beim Versand.

    Die Mailadresse ist Pflicht (Aykut 06.10.2026, nach dem ersten Lauf): Ein Kontakt
    ohne Postfach lässt sich nicht übergeben, verstopft aber die Liste und zählt als
    offener Lead, wodurch der automatische Nachschub stillstehen würde.

    In `protokoll` landet je verworfener Zeile ein Satz mit dem Grund. Ohne das stand in
    der Oberfläche nur „1 verworfen" und niemand wusste, woran es lag (07.10.2026)."""
    import re as _re
    import vertrieb
    from sqlalchemy import func
    from models import Kunde
    protokoll = protokoll if protokoll is not None else []
    neu = verworfen = 0

    def ablehnen(name, grund):
        nonlocal verworfen
        verworfen += 1
        protokoll.append(f"{name or 'Ohne Namen'}: {grund}")

    for t in treffer:
        firma = (t.get("organisation") or "").strip()
        quelle = (t.get("quelle") or "").strip()
        mail = (t.get("email") or "").strip()
        if not firma:
            ablehnen("", "keine Organisation genannt")
            continue
        if not quelle.startswith("http"):
            ablehnen(firma, "kein Quelllink")
            continue
        # Nur was wirklich wie eine Adresse aussieht. „Kontaktformular" zählt nicht.
        gefunden = _re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", mail)
        mail = gefunden.group(0).rstrip(".,;") if gefunden else ""
        if not mail:
            ablehnen(firma, "keine Mailadresse gefunden"
                     + (f" (geliefert: {t['email'][:60]})" if t.get("email") else ""))
            continue
        darf, grund = vertrieb.darf_kontaktieren(db, email=mail, firma=firma)
        if not darf:
            ablehnen(firma, grund or "gesperrt")
            continue
        if db.query(Kunde).filter(func.lower(Kunde.firma) == firma.lower()).first():
            ablehnen(firma, "steht schon im CRM")
            continue
        monat = t.get("ansprachemonat")
        art, person = _adresse_einordnen(mail, t)
        notiz = (t.get("warum") or "").strip()
        quelle_mail = (t.get("quelle_mail") or "").strip()
        if art == "person" and quelle_mail.startswith("http"):
            # Woher die Adresse stammt, gehört ins Anschreiben (Informationspflicht)
            # und in die Akte, falls jemand nachfragt.
            notiz = (notiz + f"\nAdresse gefunden auf: {quelle_mail}").strip()
        if (t.get("funktion") or "").strip() and art == "person":
            notiz = (notiz + f"\nRolle laut Quelle: {t['funktion'].strip()}").strip()
        db.add(Kunde(
            firma=firma, email=mail or None, ort=(t.get("ort") or "").strip() or None,
            ansprechpartner=person or None, mail_art=art,
            herkunft="akquise", pipeline_status="lead",
            akquise_art=(t.get("art") or "").strip() or None,
            quelle=quelle, anlass=(t.get("anlass") or "").strip() or None,
            ansprachemonat=monat if isinstance(monat, int) and 1 <= monat <= 12 else None,
            branche=(t.get("branche") or "").strip() or None,
            quelle_beleg=(t.get("beleg") or "").strip().lower() or None,
            notizen=notiz or None,
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
        protokoll = []
        neu, verworfen = uebernehmen(db, ergebnis["kontakte"], a.id, protokoll)
        a.anzahl, a.verworfen = neu, verworfen
        a.suchen, a.kosten_cent = ergebnis["suchen"], ergebnis["kosten_cent"]
        # Die Meldung soll beides erklären: was die App verworfen hat und welche der
        # genannten Firmen das Modell gar nicht vorgeschlagen hat.
        teile = [ergebnis["meldung"]] if ergebnis["meldung"] else []
        if protokoll:
            teile.append("Verworfen: " + "; ".join(protokoll))
        if neu and ergebnis.get("nicht_aufgenommen"):
            teile.append("Nicht vorgeschlagen: "
                         + "; ".join(ergebnis["nicht_aufgenommen"]))
        a.meldung = (" | ".join(teile))[:2000] or None
        # Eine Meldung allein ist kein Fehler: „keine Organisation aufgenommen" ist ein
        # gültiges Ergebnis und soll nicht als fehlgeschlagen dastehen.
        a.status = "fehler" if ergebnis.get("fehler") else "fertig"
        a.fertig_am = datetime.now().isoformat(timespec="seconds")
        db.commit()
        # Immer melden, auch bei null Treffern oder Fehler: Aykut wartet auf das
        # Ergebnis und soll nicht selbst nachsehen müssen.
        from notifications import notify
        titel = (f"Recherche fehlgeschlagen" if a.status == "fehler"
                 else f"Recherche fertig: {neu} neue Kontakte")
        notify(db, "recherche_fertig", titel,
               f"Auftrag: {a.auftrag[:120]} / {neu} neu, {verworfen} verworfen, "
               f"{a.suchen} Suchen, {a.kosten_cent:.0f} Cent."
               + (f" {a.meldung}" if a.meldung else ""), "/admin/crm/akquise")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[RECHERCHE] Auftrag {auftrag_id} fehlgeschlagen: {e}")
    finally:
        db.close()
