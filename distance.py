import math
import os
import json
import re

# Vollständiger deutscher PLZ→(lat, lon)-Datensatz (GeoNames, gebündelt unter data/plz_coords.json).
# Deckt ganz Deutschland ab – kein externer API-Aufruf, keine Kosten.
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
try:
    with open(os.path.join(_DATA_DIR, "plz_coords.json"), encoding="utf-8") as _f:
        PLZ_COORDS = {plz: (c[0], c[1]) for plz, c in json.load(_f).items()}
except (FileNotFoundError, ValueError):
    PLZ_COORDS = {}

# Stadtname→(lat, lon) als Fallback, wenn keine (passende) PLZ vorhanden ist.
try:
    with open(os.path.join(_DATA_DIR, "city_coords.json"), encoding="utf-8") as _f:
        CITY_COORDS = {name: (c[0], c[1]) for name, c in json.load(_f).items()}
except (FileNotFoundError, ValueError):
    CITY_COORDS = {}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Entfernung in km zwischen zwei Koordinaten."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def get_coords_for_plz(plz: str):
    return PLZ_COORDS.get((plz or "")[:5])


def get_coords_for_city(stadt: str):
    return CITY_COORDS.get((stadt or "").strip().lower())


def _plz_in_text(text: str):
    """Erste 5-stellige PLZ aus einem Freitextfeld (z. B. Straße) holen."""
    match = re.search(r'\b(\d{5})\b', text or "")
    return get_coords_for_plz(match.group(1)) if match else None


def get_coords_for_address(address: str):
    """Koordinaten für eine Freitext-Adresse: erst PLZ darin, dann Stadtname am Ende."""
    coords = _plz_in_text(address)
    if coords:
        return coords
    # Letztes Wort als Stadtname versuchen (z. B. "Musterstr. 1, Köln")
    rest = re.sub(r'\d', '', address or "")
    teil = rest.replace(",", " ").split()
    return get_coords_for_city(teil[-1]) if teil else None


def get_coords_for_dienstleister(d):
    """Beste verfügbare Koordinaten: PLZ-Feld → PLZ in der Straße → Stadtname."""
    return (get_coords_for_plz(d.plz or "")
            or _plz_in_text(getattr(d, "strasse", "") or "")
            or get_coords_for_city(getattr(d, "stadt", "") or ""))


# --- Empfehlungs-Scoring -----------------------------------------------------
# Score 0–100, höher = zuerst anfragen. Gewichtung mit Aykut abgestimmt (13.06.2026):
#   Entfernung 40 · Qualität 30 · Logistik 20 (nur wenn Event Material braucht) · Erfahrung 10
_MAX_KM = 80          # ab dieser Entfernung 0 Entfernungspunkte
_XP_VOLL = 50         # ab so vielen Erfahrungspunkten die vollen 10 Punkte
_QUALITAET_UNBEWERTET = 3   # noch nicht bewertet → neutral behandeln (nicht abstrafen)


def compute_score(d, event_coords, needs_material: bool):
    """Berechnet (score, distanz_km) für einen Dienstleister. distanz_km kann None sein."""
    # Entfernung
    distanz_km = None
    if event_coords:
        c = get_coords_for_dienstleister(d)
        if c:
            distanz_km = haversine(event_coords[0], event_coords[1], c[0], c[1])
    if distanz_km is None:
        dist_pts = 0.0
    else:
        dist_pts = 40 * max(0.0, 1 - min(distanz_km, _MAX_KM) / _MAX_KM)

    # Qualität (1–5 ⭐ → 0–30). Unbewertet = neutral (3 ⭐).
    sterne = d.qualitaet if getattr(d, "qualitaet", None) else _QUALITAET_UNBEWERTET
    quali_pts = sterne * 6

    # Logistik: voller Boost nur wenn das Event Materialtransport braucht, sonst kleiner Allgemein-Bonus.
    log_pts = 0
    if d.logistiker:
        log_pts = 20 if needs_material else 5

    # Erfahrung (0–10)
    xp = d.erfahrungspunkte or 0
    exp_pts = 10 * min(xp, _XP_VOLL) / _XP_VOLL

    return round(dist_pts + quali_pts + log_pts + exp_pts), distanz_km


def rank_contractors(contractors, event_address: str, needs_material: bool = False,
                     unavailable_ids=None):
    """
    Sortiert Dienstleister als Empfehlungsreihenfolge (bester zuerst).
    Nicht verfügbare (Sperrzeit / am Tag schon gebucht) rutschen ans Ende, bleiben aber sichtbar.
    Hängt pro Objekt rang_score und rang_distanz_km an (für die Anzeige).
    """
    unavailable_ids = unavailable_ids or set()
    event_coords = get_coords_for_address(event_address)

    for d in contractors:
        score, dist = compute_score(d, event_coords, needs_material)
        d.rang_score = score
        d.rang_distanz_km = dist

    return sorted(
        contractors,
        key=lambda d: (1 if d.id in unavailable_ids else 0, -d.rang_score)
    )
