"""Ankunfts-/Treffpunkt-Logik fürs Briefing.

Der Vorlauf (wie früh das Team vor Aktionsbeginn da sein soll) wird aus den
gebuchten Aktionen vor-berechnet, ist aber pro Event überschreibbar:
  ankunft_modus: "auto" | "30" | "45" | "60" | "90" | "eigen" | "sonderfall"
Bei "sonderfall" zählt der Freitext ankunft_text. Bei "eigen" / reiner
Künstler-Buchung: "in Eigenverantwortung" (kein fester Treffpunkt/Ankunftszeit).
"""

# Reine Künstler-Aktionen: sind ALLE gebuchten Aktionen daraus → Eigenverantwortung
KUENSTLER = {"Zaubershow", "Walkact", "Ballonmodellage", "Kinderschminken"}

# Vorlauf je Aktion in Minuten (Künstler-Aktionen = 0, zählen im Mix nicht hoch)
VORLAUF = {
    # 60 – große Aufbauten
    "Spieleland": 60, "U3 Spieleland": 60, "Mitmachzirkus": 60,
    "Mini Mitmachzirkus": 60, "Hüpfburg": 60,
    # 45 – Bastelaktionen
    "Bunter Bastelspaß": 45, "Bastelaktion": 45,
    "Prickeln": 45, "Knusperhäuschen": 45, "Lebkuchenherzen": 45,
    "Bastelspaß Weihnachten": 45,
    # 30 – leichte Aktionen / Betreuung / Kinderschminken im Mix
    "Glitzertattoos": 30, "Fotoaktion": 30, "Buttonmaschine": 30,
    "Kein Material": 30, "Kinderschminken": 30,
    # 0 – reine Künstler
    "Zaubershow": 0, "Walkact": 0, "Ballonmodellage": 0,
}

DEFAULT_TREFFPUNKT = "vor dem Haupteingang"


def _produkte_liste(produkte) -> list:
    return [p.strip() for p in (produkte or "").split(",") if p.strip()]


def auto_vorlauf(produkte):
    """Automatischer Vorlauf in Minuten aus den gebuchten Aktionen; None = Eigenverantwortung."""
    items = _produkte_liste(produkte)
    if not items:
        return None
    if all(p in KUENSTLER for p in items):
        return None  # reine Künstler-Buchung
    return max(VORLAUF.get(p, 30) for p in items) or 30


def vorlauf_minuten(ev):
    """Effektiver Vorlauf in Minuten je nach Modus; None bei Eigenverantwortung/Sonderfall."""
    modus = getattr(ev, "ankunft_modus", None) or "auto"
    if modus in ("eigen", "sonderfall"):
        return None
    if modus in ("30", "45", "60", "90"):
        return int(modus)
    return auto_vorlauf(getattr(ev, "produkte", ""))


def _minus(zeit, mins):
    try:
        h, m = (int(x) for x in str(zeit).split(":"))
    except (ValueError, AttributeError):
        return ""
    t = max(0, h * 60 + m - mins)
    return f"{t // 60:02d}:{t % 60:02d}"


def ankunft_anzeige(ev) -> str:
    """Anzeige-Text für die Ankunft im Briefing/Event-Detail."""
    modus = getattr(ev, "ankunft_modus", None) or "auto"
    if modus == "sonderfall":
        return (getattr(ev, "ankunft_text", "") or "").strip() or "—"
    mins = vorlauf_minuten(ev)
    if mins is None:
        return "in Eigenverantwortung"
    start = getattr(ev, "startzeit", "") or ""
    uhr = _minus(start, mins)
    if not uhr:
        return f"{mins} Min vor Aktionsbeginn"
    return f"{uhr} Uhr (= {mins} Min vor Aktionsbeginn)"


def treffpunkt_anzeige(ev) -> str:
    return (getattr(ev, "treffpunkt", "") or "").strip() or DEFAULT_TREFFPUNKT
