"""Gebuchte Aktionen: gruppierte Anzeige (Künstler / Weitere / Saisonal) in fester
Reihenfolge; „Kleinkind Spieleland" → „U3 Spieleland" umbenannt."""
import ankunft
from routes.admin import PRODUKTE_LIST, PRODUKTE_GRUPPEN


def test_gruppen_reihenfolge_und_titel():
    titel = [g for g, _ in PRODUKTE_GRUPPEN]
    assert titel == ["Künstler-Aktionen", "Weitere Aktionen", "Saisonale Aktionen"]
    kuenstler = dict(PRODUKTE_GRUPPEN)["Künstler-Aktionen"]
    assert kuenstler == ["Zaubershow", "Zaubershow + Ballonmodellage", "Kinderschminken",
                         "Ballonmodellage", "Walkact", "Zauberworkshop"]


def test_flache_liste_bleibt_in_sync():
    aus_gruppen = [p for _, ps in PRODUKTE_GRUPPEN for p in ps]
    assert PRODUKTE_LIST == aus_gruppen


def test_u3_statt_kleinkind():
    assert "U3 Spieleland" in PRODUKTE_LIST
    assert "Kleinkind Spieleland" not in PRODUKTE_LIST
    # Vorlauf-Tabelle mitgezogen (sonst still „kein Vorlauf")
    assert ankunft.auto_vorlauf("U3 Spieleland") == 60
    assert "Kleinkind Spieleland" not in ankunft.VORLAUF


def test_formular_zeigt_gruppenueberschriften(admin):
    h = admin.get("/admin/events/new").text
    assert "Künstler-Aktionen" in h
    assert "Weitere Aktionen" in h
    assert "Saisonale Aktionen" in h
    assert "U3 Spieleland" in h
    assert "Kleinkind Spieleland" not in h
