"""Künstler können mehrere Sparten haben (Aykut, 24.09.2026): Ballonkünstler UND
Showact war vorher nicht abbildbar, „Schminke + Ballon" war eine eigene Kategorie."""
from types import SimpleNamespace

from choices import (SPARTEN, benoetigte_sparten, kuenstler_passt, sparte_label,
                     sparten_liste)
from factories import make_dienstleister, reload
from models import Dienstleister


def _d(sparten):
    return SimpleNamespace(kuenstler_sparte=sparten)


def test_mehrere_sparten_werden_gelesen():
    assert sparten_liste(_d("Ballonkünstler, Showact")) == ["Ballonkünstler", "Showact"]
    assert sparten_liste(_d(None)) == []


def test_kombi_kategorie_ist_aufgeloest():
    assert "Schminke + Ballon" not in dict(SPARTEN)
    assert benoetigte_sparten("Kinderschminken") == {"Kinderschminke"}
    assert benoetigte_sparten("Ballonmodellage") == {"Ballonkünstler"}


def test_passt_wenn_eine_sparte_trifft():
    beide = _d("Kinderschminke, Ballonkünstler")
    assert kuenstler_passt(beide, benoetigte_sparten("Kinderschminken"))
    assert kuenstler_passt(beide, benoetigte_sparten("Ballonmodellage"))
    assert not kuenstler_passt(beide, benoetigte_sparten("Zaubershow"))
    assert kuenstler_passt(_d("Showact"), benoetigte_sparten("Zaubershow"))
    assert kuenstler_passt(_d(None), set())          # ohne Anforderung passt jeder


def test_briefing_label_nennt_alle():
    assert sparte_label(_d("Kinderschminke, Ballonkünstler")) == "(Kinderschminken + Ballonmodellage)"
    assert sparte_label(_d("Showact")) == "(Showact)"
    assert sparte_label(_d(None)) == ""


def test_formular_speichert_mehrere_sparten(admin, db):
    r = admin.post("/admin/dienstleister/new", data={
        "vorname": "Mehr", "nachname": "Sparten", "email": "mehr.sparten@example.de",
        "rolle": "Künstler", "kuenstler_sparte": ["Ballonkünstler", "Showact"],
        "aktiv": "true"}, follow_redirects=False)
    assert r.status_code == 303
    d = db.query(Dienstleister).filter(Dienstleister.email == "mehr.sparten@example.de").first()
    assert d.kuenstler_sparte == "Ballonkünstler, Showact"
    html = admin.get(f"/admin/dienstleister/{d.id}/edit").text
    assert html.count('name="kuenstler_sparte" value="Ballonkünstler" checked') == 1
    assert html.count('name="kuenstler_sparte" value="Showact" checked') == 1
    assert 'value="Kinderschminke" checked' not in html


def test_bearbeiten_kann_sparten_leeren(admin, db):
    did = make_dienstleister(rolle="Künstler", kuenstler_sparte="Showact")
    d = reload(Dienstleister, did)
    admin.post(f"/admin/dienstleister/{did}/edit", data={
        "vorname": d.vorname, "nachname": d.nachname, "email": d.email, "rolle": "Teamer"})
    assert reload(Dienstleister, did).kuenstler_sparte is None


def test_liste_zeigt_alle_sparten(admin, db):
    make_dienstleister(vorname="Vielseitig", rolle="Künstler",
                       kuenstler_sparte="Ballonkünstler, Showact")
    html = admin.get("/admin/dienstleister").text
    assert "🎈 Ballonkünstler · 🎩 Showact" in html
