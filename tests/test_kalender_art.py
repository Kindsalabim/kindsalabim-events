"""Kalender-Kürzel aus den gebuchten Aktionen + Event-Formular (Anlass-Freitext, neue Produkte)."""
from types import SimpleNamespace

from calendar_service import _event_art, _title


def _ev(produkte, **kw):
    base = dict(produkte=produkte, veranstaltungsort="Markt 1, 45127 Essen",
                kunde_kontakt="Frau Test", kunde_firma="Test GmbH", anlass="Sommerfest",
                status="Gebucht")
    base.update(kw)
    return SimpleNamespace(**base)


def test_art_nur_zaubershow():
    assert _event_art(_ev("Zaubershow")) == "Z"


def test_art_zaubershow_plus_ballon_als_kombi_produkt():
    assert _event_art(_ev("Zaubershow + Ballonmodellage")) == "ZB"


def test_art_zaubershow_plus_ballon_als_zwei_produkte():
    assert _event_art(_ev("Zaubershow, Ballonmodellage")) == "ZB"


def test_art_nur_ballon():
    assert _event_art(_ev("Ballonmodellage")) == "B"


def test_art_nur_kinderschminken():
    assert _event_art(_ev("Kinderschminken")) == "Kischmi."


def test_art_kein_material_wird_ignoriert():
    assert _event_art(_ev("Zaubershow, Kein Material")) == "Z"


def test_art_verschiedene_dienstleistungen_ist_div():
    assert _event_art(_ev("Bunter Bastelspaß, Hüpfburg, Kinderschminken")) == "div."


def test_art_zaubershow_mit_anderer_aktion_ist_div():
    # Zaubershow + etwas ohne eigenes Kürzel → kein sauberes (Z) mehr
    assert _event_art(_ev("Zaubershow, Glitzertattoos")) == "div."


def test_art_zauberworkshop_ist_div():
    assert _event_art(_ev("Zauberworkshop")) == "div."


def test_art_leer_ist_div():
    assert _event_art(_ev("")) == "div."
    assert _event_art(_ev(None)) == "div."


def test_title_nutzt_kuerzel():
    t = _title(_ev("Zaubershow"))
    assert t.startswith("(Z) ") and "Essen" in t and "Sommerfest" in t


def test_title_abgesagt_behaelt_kuerzel():
    t = _title(_ev("Kinderschminken", status="Abgesagt"))
    assert t.startswith("ABGESAGT – (Kischmi.)")


# ── Event-Formular: Anlass-Freitext + neue Produkte ───────────────────────────

def test_neue_produkte_in_liste():
    from routes.admin import PRODUKTE_LIST
    assert "Zauberworkshop" in PRODUKTE_LIST
    assert "Zaubershow + Ballonmodellage" in PRODUKTE_LIST


def test_formular_anlass_ist_freitext(admin):
    r = admin.get("/admin/events/new")
    assert r.status_code == 200
    # Freitext-Input mit Vorschlagsliste statt fixem <select>
    assert 'name="anlass"' in r.text and 'list="anlass_optionen"' in r.text
    assert '<datalist id="anlass_optionen">' in r.text
    # neue Aktionen als Auswahl vorhanden
    assert "Zauberworkshop" in r.text and "Zaubershow + Ballonmodellage" in r.text
