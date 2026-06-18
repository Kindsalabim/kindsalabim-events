"""Baker-Ross-Recherche – Kuratierung & Preis-Nachladen.

- Quelle ist der lokale Katalog (BastelProdukt, aus der Sitemap). Es wird NICHT live
  via KI/WebFetch gescrapt (robots.txt sperrt KI-Crawler).
- Die KI (Claude API) kuratiert nur aus dem lokalen Katalog. Ohne API-Key greift ein
  deterministischer Stichwort-Fallback (sofort nutzbar, nur ohne Begründungen).
- Preise stehen nicht in der Sitemap → werden für die wenigen kuratierten Treffer
  respektvoll (eigener UA, Cache 7 Tage) von der jeweiligen Produktseite nachgeladen.
"""
import json
import re
import time
from datetime import date, datetime, timedelta

import httpx

from config import get_config

USER_AGENT = "KindsalabimKatalog/1.0 (+https://kindsalabim-events.onrender.com; Bastelset-Recherche)"
PREIS_CACHE_TAGE = 7
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Stichwort-Fallback (ohne API-Key): Motto/Saison -> Suchbegriffe im Katalog.
SAISON_STICHWORTE = {
    "herbst": ["herbst", "igel", "eichhörnchen", "blatt", "blätter", "pilz", "kürbis", "drache", "laterne", "kastanie", "eichel", "fuchs"],
    "weihnachten": ["weihnacht", "tannenbaum", "stern", "schneemann", "engel", "rentier", "nikolaus", "advent", "christbaum", "schnee", "elch"],
    "winter": ["winter", "schnee", "schneemann", "eiskristall", "stern", "pinguin", "eisbär"],
    "ostern": ["oster", "hase", "ei ", "eier", "küken", "frühling", "lamm", "karotte"],
    "frühling": ["frühling", "blume", "schmetterling", "marienkäfer", "biene", "vogel", "küken", "blüte"],
    "sommer": ["sommer", "sonne", "strand", "meer", "fisch", "muschel", "eis", "flamingo", "palme"],
    "halloween": ["halloween", "geist", "gespenst", "kürbis", "fledermaus", "spinne", "hexe", "skelett", "grusel", "monster"],
    "karneval": ["karneval", "fasching", "maske", "clown", "konfetti", "verkleidung", "party"],
    "fasching": ["fasching", "karneval", "maske", "clown", "konfetti", "party"],
    "tiere": ["tier", "löwe", "elefant", "affe", "katze", "hund", "vogel", "fisch", "eule"],
    "meerjungfrau": ["meerjungfrau", "muschel", "fisch", "meer", "perle", "seestern"],
    "einhorn": ["einhorn", "regenbogen", "glitzer", "stern"],
    "pirat": ["pirat", "schatz", "schiff", "totenkopf", "meer", "säbel"],
    "dino": ["dino", "dinosaurier", "urzeit", "vulkan"],
    "dinosaurier": ["dino", "dinosaurier", "urzeit", "vulkan"],
    "weltraum": ["weltraum", "rakete", "astronaut", "planet", "stern", "alien", "mond"],
    "ritter": ["ritter", "burg", "schwert", "drache", "wappen", "krone", "prinz"],
    "prinzessin": ["prinzessin", "krone", "schloss", "fee", "glitzer", "diadem"],
    "dschungel": ["dschungel", "affe", "löwe", "tiger", "palme", "papagei", "schlange"],
    "bauernhof": ["bauernhof", "kuh", "schwein", "huhn", "schaf", "traktor", "pferd"],
    "fußball": ["fußball", "ball", "tor", "sport", "medaille", "pokal"],
}


# ── Preis-Kalkulation ────────────────────────────────────────────────────────

def compute_kundenpreis(br_preis, faktor, stueckzahl=None):
    """Kundenpreis pro Stück = (BR-Packungspreis / Stückzahl) × Faktor.
    Ohne bekannte Stückzahl: Packungspreis × Faktor (Fallback)."""
    if br_preis is None:
        return None
    try:
        basis = float(br_preis)
        if stueckzahl and int(stueckzahl) > 0:
            basis = basis / int(stueckzahl)
        return round(basis * float(faktor), 2)
    except (TypeError, ValueError):
        return None


# ── Preis-Nachladen von der Produktseite (first-party) ───────────────────────

def _price_from_offers(offers):
    if not offers:
        return None
    if isinstance(offers, list):
        for o in offers:
            p = _price_from_offers(o)
            if p:
                return p
        return None
    if isinstance(offers, dict):
        for key in ("price", "lowPrice", "lowprice"):
            v = offers.get(key)
            if v is not None:
                try:
                    p = float(v)
                    if p >= 0.10:
                        return p
                except (TypeError, ValueError):
                    pass
    return None


def _stueckzahl_from_html(html):
    """Inhalt pro Packung aus der Produktseite (z. B. <span class="pack_size">pro Set 4</span>
    oder '(16 Stück)' im Namen). None, wenn nicht erkennbar."""
    m = re.search(r'class="pack_size"[^>]*>([^<]*)<', html, re.I)
    if m:
        zahl = re.search(r'\d+', m.group(1))
        if zahl:
            return int(zahl.group(0))
    m = re.search(r'\(\s*(?:pro\s+set\s+|ca\.\s*)?(\d+)\s*(?:st(?:ü|ue)ck|stk|set)\b', html, re.I)
    if m:
        return int(m.group(1))
    return None


def fetch_preis_info(url):
    """{'preis': float|None, 'stueckzahl': int|None} von der Produktseite.
    Preis: JSON-LD → data-price-amount (kleinster = Ab-Preis) → Magento-Config."""
    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20,
                         follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return {"preis": None, "stueckzahl": None}
    html = resp.text

    preis = None
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                            html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") in ("Product", "ProductGroup"):
                p = _price_from_offers(item.get("offers"))
                if p:
                    preis = round(p, 2)
                    break
        if preis is not None:
            break

    if preis is None:
        amounts = [float(x) for x in re.findall(r'data-price-amount="([0-9.]+)"', html)]
        amounts = [a for a in amounts if a >= 0.10]
        if amounts:
            preis = round(min(amounts), 2)

    if preis is None:
        prices = [float(x) for x in re.findall(r'"price"\s*:\s*"?([0-9]+\.[0-9]+)', html)]
        prices = [p for p in prices if p >= 0.10]
        if prices:
            preis = round(min(prices), 2)

    return {"preis": preis, "stueckzahl": _stueckzahl_from_html(html)}


def fetch_price(url):
    """Nur der BR-Preis (Rückwärtskompatibilität)."""
    return fetch_preis_info(url)["preis"]


def ensure_price(db, produkt):
    """Liefert den BR-Preis; lädt Preis + Stückzahl nach, wenn fehlend/älter als 7 Tage."""
    frisch = False
    if produkt.preis is not None and produkt.preis_stand:
        try:
            frisch = date.fromisoformat(produkt.preis_stand) >= date.today() - timedelta(days=PREIS_CACHE_TAGE)
        except ValueError:
            frisch = False
    if frisch:
        return produkt.preis
    info = fetch_preis_info(produkt.url)
    if info["preis"] is not None:
        produkt.preis = info["preis"]
        if info["stueckzahl"]:
            produkt.stueckzahl = info["stueckzahl"]
        produkt.preis_stand = date.today().isoformat()
        db.commit()
    return produkt.preis


# ── Claude API ───────────────────────────────────────────────────────────────

def ki_verfuegbar():
    return bool(get_config().get("anthropic_api_key"))


def _claude(system, user, max_tokens=1024):
    cfg = get_config()
    key = cfg.get("anthropic_api_key")
    if not key:
        return None
    model = cfg.get("bakerross_model") or DEFAULT_MODEL
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
    except Exception as e:
        print(f"Claude-API-Fehler: {e}")
        return None


def _json_aus_text(text):
    """Erstes JSON-Array/-Objekt aus einer Modellantwort herauslösen."""
    if not text:
        return None
    m = re.search(r"\[.*\]|\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ── Stichwort-Filter (Katalog vorfiltern) ────────────────────────────────────

def _expand_stichworte(query):
    """Motto/Saison -> Liste von Suchbegriffen (Saison-Map + eigene Wörter)."""
    q = (query or "").lower()
    worte = set(re.findall(r"[a-zäöüß]{3,}", q))
    for schluessel, stichworte in SAISON_STICHWORTE.items():
        if schluessel in q:
            worte.update(stichworte)
    return [w.strip() for w in worte if w.strip()]


def _score(produkt, stichworte):
    text = f"{produkt.name} {produkt.beschreibung or ''}".lower()
    treffer = sum(1 for w in stichworte if w in text)
    # Treffer im Namen stärker gewichten
    name = produkt.name.lower()
    treffer += sum(1 for w in stichworte if w in name)
    return treffer


def _kandidaten(db, query, stichworte, cap=80):
    from models import BastelProdukt
    produkte = db.query(BastelProdukt).filter(BastelProdukt.aktiv == True).all()  # noqa: E712
    bewertet = [(p, _score(p, stichworte)) for p in produkte]
    bewertet = [(p, s) for p, s in bewertet if s > 0]
    bewertet.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in bewertet[:cap]]


# ── Kuratierung (Hauptfunktion) ──────────────────────────────────────────────

def kurate(db, query, max_results=12, faktor=2.5):
    """Liefert kuratierte Treffer als Liste von dicts:
    {produkt, br_preis, kundenpreis, grund}. Nutzt Claude, wenn ein Key gesetzt
    ist (Begriffs-Erweiterung + Auswahl mit Begründung), sonst Stichwort-Ranking."""
    use_ki = ki_verfuegbar()

    # 1. Suchbegriffe bestimmen (KI erweitert das Motto besser als die Saison-Map)
    stichworte = _expand_stichworte(query)
    if use_ki:
        antwort = _claude(
            "Du hilfst bei der Auswahl von Bastelsets für Kinder-Events. Antworte nur mit JSON.",
            f"Nenne 8-20 deutsche Suchbegriffe (Substantive, Motive, Materialien), die zu "
            f"diesem Motto/dieser Saison passende Bastelsets beschreiben: \"{query}\". "
            f"Antworte als JSON-Array von Strings, z. B. [\"igel\",\"blatt\"].",
            max_tokens=300,
        )
        ki_worte = _json_aus_text(antwort)
        if isinstance(ki_worte, list):
            stichworte = list({*stichworte, *[str(w).lower().strip() for w in ki_worte if str(w).strip()]})

    if not stichworte:
        return []

    kandidaten = _kandidaten(db, query, stichworte)
    if not kandidaten:
        return []

    # 2. Auswahl: KI rankt + begründet aus den Kandidaten; sonst Stichwort-Top-N
    ausgewaehlt = []  # Liste (produkt, grund)
    if use_ki:
        liste = "\n".join(
            f"{p.id}: {p.name} – {(p.beschreibung or '')[:160]}" for p in kandidaten
        )
        antwort = _claude(
            "Du kuratierst Bastelsets für ein Kinder-Event-Unternehmen. Wähle nur aus der "
            "vorgegebenen Liste. Erfinde keine Produkte. Antworte nur mit JSON.",
            f"Motto/Saison: \"{query}\".\n\nWähle die {max_results} am besten passenden "
            f"Bastelsets aus dieser Liste (Format 'ID: Name – Beschreibung'):\n\n{liste}\n\n"
            f"Antworte als JSON-Array: [{{\"id\": <ID>, \"grund\": \"<kurze Begründung, "
            f"warum es passt, max. 12 Wörter>\"}}]. Nur IDs aus der Liste.",
            max_tokens=1500,
        )
        picks = _json_aus_text(antwort)
        if isinstance(picks, list):
            by_id = {p.id: p for p in kandidaten}
            for pick in picks:
                if not isinstance(pick, dict):
                    continue
                p = by_id.get(pick.get("id"))
                if p and p not in [a for a, _ in ausgewaehlt]:
                    ausgewaehlt.append((p, str(pick.get("grund", "")).strip()))

    if not ausgewaehlt:  # Fallback (kein Key oder KI-Antwort unbrauchbar)
        ausgewaehlt = [(p, "") for p in kandidaten[:max_results]]

    ausgewaehlt = ausgewaehlt[:max_results]

    # 3. Preise + Stückzahl nachladen (nur für die wenigen Treffer, respektvoll mit kleiner Pause)
    treffer = []
    for i, (p, grund) in enumerate(ausgewaehlt):
        if i:
            time.sleep(0.4)
        br_preis = ensure_price(db, p)
        treffer.append({
            "produkt": p,
            "br_preis": br_preis,
            "stueckzahl": p.stueckzahl,
            "kundenpreis": compute_kundenpreis(br_preis, faktor, p.stueckzahl),
            "grund": grund,
        })
    return treffer
