"""Tailwind wird als fertige Datei ausgeliefert, nicht über den Play-CDN.

Hintergrund: Der Play-CDN (cdn.tailwindcss.com) lud 407 KB JavaScript und erzeugte
das CSS bei jedem Seitenaufruf im Browser des Nutzers – spürbar langsam, und
Tailwind warnt selbst davor, ihn produktiv einzusetzen. Neu erzeugt wird die Datei
mit `python doku/build_tailwind.py`.
"""
import io
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(REPO, "static", "css", "tailwind.css")
BASE = os.path.join(REPO, "templates", "base.html")


def _base():
    return io.open(BASE, encoding="utf-8").read()


def test_kein_tailwind_cdn_mehr():
    assert "cdn.tailwindcss.com" not in _base()


def test_lokales_css_wird_eingebunden():
    assert re.search(r'<link[^>]+href="/static/css/tailwind\.css', _base())


def test_cache_schluessel_haengt_an_der_datei():
    """Eine feste Versionsnummer wäre eine Falle: Nach einem Neubau des CSS
    würden Browser die alte Datei weiterverwenden (Fall 13.09.2026)."""
    assert "?v={{ css_version }}" in _base()


def test_css_version_ist_in_allen_umgebungen_gesetzt():
    """base.html rendert auch im Portal und in der Kunden-Checkliste."""
    import main   # noqa: F401  – registriert die Jinja-Globals beim Import
    import routes.admin, routes.portal, routes.checklist
    for modul in (routes.admin, routes.portal, routes.checklist):
        assert modul.templates.env.globals.get("css_version"), \
            f"css_version fehlt in {modul.__name__}"


def test_css_datei_existiert_und_ist_echtes_tailwind():
    assert os.path.exists(CSS), "static/css/tailwind.css fehlt – build_tailwind.py laufen lassen"
    inhalt = io.open(CSS, encoding="utf-8").read()
    assert "--tw-" in inhalt, "Datei enthält kein Tailwind-CSS"
    assert ".flex{display:flex}" in inhalt
    assert "@media (min-width: 768px)" in inhalt, "Breakpoint-Regeln fehlen"


def test_css_deckt_die_haeufigsten_klassen_ab():
    """Stichprobe quer durch die App – fehlt eine davon, ist die Datei veraltet."""
    inhalt = io.open(CSS, encoding="utf-8").read()
    regeln = {re.sub(r"\\(.)", r"\1", k)
              for k in re.findall(r"\.((?:[a-zA-Z0-9_-]|\\.)+)", inhalt)}
    for klasse in ["flex", "hidden", "grid", "w-full", "text-sm", "font-semibold",
                   "rounded-xl", "px-4", "py-2", "gap-3", "items-center",
                   "justify-between", "md:grid-cols-2", "whitespace-nowrap",
                   "overflow-x-auto", "max-w-none", "-mt-1", "space-y-4"]:
        assert klasse in regeln, f"Regel für '{klasse}' fehlt – build_tailwind.py laufen lassen"
