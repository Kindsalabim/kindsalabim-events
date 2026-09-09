# -*- coding: utf-8 -*-
"""Erzeugt static/css/tailwind.css – das fertige Tailwind-CSS der App.

Warum: Die App lud Tailwind früher über den Play-CDN (cdn.tailwindcss.com).
Der bringt 407 KB JavaScript mit und erzeugt das CSS bei JEDEM Seitenaufruf im
Browser des Nutzers, indem er das gesamte Markup durchsucht – bei großen Seiten
spürbar langsam, und Tailwind warnt selbst in der Konsole davor, ihn produktiv
einzusetzen. Stattdessen lassen wir Tailwind das CSS EINMAL erzeugen und
checken das Ergebnis als Datei ein.

Wie: Alle Klassen-Kandidaten aus den Templates sammeln, in eine Hilfsseite
schreiben, diese mit dem Play-CDN in Chrome-Headless rendern und das von
Tailwind erzeugte <style> herausschneiden. Also exakt dieselbe Tailwind-Version
und -Konfiguration wie bisher, nur eben vorberechnet.

Aufruf aus dem Repo-Wurzelverzeichnis (braucht kurz Internet für den CDN):
    PYTHONUTF8=1 python doku/build_tailwind.py

WANN NEU LAUFEN LASSEN: sobald in Templates neue Tailwind-Klassen dazukommen,
die vorher nirgends verwendet wurden. Ohne Neulauf fehlt deren Regel und das
Element bleibt ungestylt. `--pruefen` meldet genau das, ohne etwas zu schreiben.
"""
import io
import os
import re
import subprocess
import sys
import tempfile

DOKU = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DOKU)
ZIEL = os.path.join(REPO, "static", "css", "tailwind.css")

CHROME_KANDIDATEN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# Klassen-Token: fuehrendes "-" muss mit (negative Utilities wie -mt-1),
# ebenso ":" (md:flex), "/" (w-1/2) und "[]" (min-h-[120px]).
TOKEN = re.compile(r"-?[a-zA-Z0-9][a-zA-Z0-9:_\/.\-\[\]%#()]*")

JINJA_WOERTER = {
    "if", "else", "elif", "endif", "for", "endfor", "in", "and", "or", "not",
    "is", "true", "false", "none", "set", "block", "endblock", "with", "endwith",
    "extends", "include", "macro", "endmacro", "filter", "endfilter",
}

# Klassen, die erst zur Laufzeit per JavaScript gesetzt werden und deshalb in
# keinem class-Attribut stehen muessen.
LAUFZEIT = ["hidden", "block", "flex", "opacity-0", "opacity-60", "active"]


def klassen_sammeln() -> set:
    """Alle Klassen-Kandidaten aus den Templates.

    Bewusst der GESAMTE Dateitext, nicht nur class-Attribute: Klassen stehen
    auch in Jinja-Bloecken ({% block content_width %}max-w-none{% endblock %})
    und in JavaScript-Literalen. Falschtreffer sind harmlos – fuer Unbekanntes
    erzeugt Tailwind keine Regel.
    """
    gefunden = set()
    for wurzel, _, namen in os.walk(os.path.join(REPO, "templates")):
        for n in namen:
            if n.endswith(".html"):
                text = io.open(os.path.join(wurzel, n), encoding="utf-8").read()
                gefunden.update(TOKEN.findall(text))
    gefunden = {k for k in gefunden if len(k) > 1 and k.lower() not in JINJA_WOERTER}
    gefunden.update(LAUFZEIT)
    return gefunden


def css_erzeugen(klassen: set) -> str:
    """Laesst Tailwind das CSS im Browser erzeugen und gibt es zurueck."""
    chrome = next((c for c in CHROME_KANDIDATEN if os.path.exists(c)), None)
    if not chrome:
        sys.exit("Chrome nicht gefunden – Pfad in CHROME_KANDIDATEN ergaenzen.")

    tmp = tempfile.mkdtemp(prefix="tw_build_")
    seite = os.path.join(tmp, "sammel.html")
    io.open(seite, "w", encoding="utf-8").write(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<script src='https://cdn.tailwindcss.com'></script></head><body>"
        f"<div class=\"{' '.join(sorted(klassen))}\"></div>"
        "</body></html>")

    # --dump-dom liefert das gerenderte DOM inklusive des <style>, das Tailwind
    # zur Laufzeit einhaengt. --virtual-time-budget wartet, bis der CDN fertig ist.
    ergebnis = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={os.path.join(tmp, 'profil')}",
         "--virtual-time-budget=15000", "--dump-dom",
         "file:///" + seite.replace("\\", "/")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    dom = ergebnis.stdout or ""
    bloecke = re.findall(r"<style[^>]*>(.*?)</style>", dom, re.S)
    tailwind = [b for b in bloecke if "--tw-" in b]
    if not tailwind:
        sys.exit("Kein Tailwind-CSS im gerenderten DOM – kam der CDN durch? "
                 "(Internetverbindung noetig)")
    return max(tailwind, key=len).strip() + "\n"


def main():
    nur_pruefen = "--pruefen" in sys.argv
    klassen = klassen_sammeln()
    css = css_erzeugen(klassen)

    if nur_pruefen:
        alt = io.open(ZIEL, encoding="utf-8").read() if os.path.exists(ZIEL) else ""
        regeln_neu = set(re.findall(r"\.((?:[a-zA-Z0-9_-]|\\.)+)", css))
        regeln_alt = set(re.findall(r"\.((?:[a-zA-Z0-9_-]|\\.)+)", alt))
        fehlend = sorted(r.replace("\\", "") for r in regeln_neu - regeln_alt)
        if fehlend:
            print(f"VERALTET: {len(fehlend)} Regeln fehlen in {ZIEL}:")
            for r in fehlend[:40]:
                print("   ", r)
            sys.exit(1)
        print(f"Aktuell – {len(regeln_alt)} Regeln, nichts fehlt.")
        return

    os.makedirs(os.path.dirname(ZIEL), exist_ok=True)
    io.open(ZIEL, "w", encoding="utf-8", newline="\n").write(css)
    regeln = len(set(re.findall(r"\.((?:[a-zA-Z0-9_-]|\\.)+)", css)))
    print(f"{len(klassen)} Klassen-Kandidaten aus den Templates")
    print(f"CSS gebaut: {ZIEL} ({len(css)/1024:.0f} KB, {regeln} Regeln)")


if __name__ == "__main__":
    main()
