"""Reservierung per Link vorbefüllen (Anfrage-Assistent → „Als Reservierung in der
Events-App anlegen", nur Geschäftskunden). Es wird nichts gespeichert."""
from urllib.parse import urlencode

from database import SessionLocal
from models import Reservierung

BASIS = {
    "neu": "1", "kunde_firma": "Vorlage Stadtwerke & Co", "datum": "2026-11-14",
    "startzeit": "14:00", "endzeit": "17:30", "veranstaltungsort": "Rathausplatz 1, 45127 Essen",
    "art": "zb", "anlass": "Herbstfest", "kunde_kontakt": "Fr. Beispiel",
    "kunde_email": "fest@stadtwerke.example", "kunde_telefon": "0201 123",
    "frist": "2026-10-01", "marke": "knallfrosch",
}


def _seite(admin, **aenderung):
    return admin.get("/admin/reservierungen?" + urlencode({**BASIS, **aenderung})).text


def _anzahl():
    s = SessionLocal()
    try:
        return s.query(Reservierung).count()
    finally:
        s.close()


def test_formular_ist_vollstaendig_vorbefuellt(admin):
    vorher = _anzahl()
    html = _seite(admin)
    assert "Aus dem Anfrage-Assistenten übernommen" in html
    for wert in ('value="2026-11-14"', 'value="2026-10-01"', "Vorlage Stadtwerke &amp; Co",
                 "Rathausplatz 1, 45127 Essen", "Herbstfest", "fest@stadtwerke.example",
                 "0201 123", "Fr. Beispiel"):
        assert wert in html, wert
    assert '<option value="ZB" selected' in html
    assert 'value="14:00" selected' in html and 'value="17:30" selected' in html
    assert "<option selected>Knallfrosch</option>" in html
    assert "⚠️" not in html
    assert _anzahl() == vorher          # nur Formular, nichts gespeichert


def test_div_ist_eine_gueltige_wahl_ohne_warnung(admin):
    """Der Anfrage-Assistent schickt „Div." bewusst, wenn Aykut nicht selbst auftritt
    (02.10.2026). Dann ist „blockiert nicht" richtig – kein Hinweis mehr."""
    html = _seite(admin, art="Div.")
    assert "Art bitte wählen" not in html
    assert '<option value="Div." selected' in html


def test_warnt_nur_bei_fehlender_art(admin):
    html = _seite(admin, art="", startzeit="")
    assert "Art bitte wählen" in html
    assert "ganztägig" in html


def test_kombi_arten_werden_uebernommen(admin):
    """Gemischte Events: Aykut tritt selbst auf UND Stationen laufen."""
    for roh, erwartet in [("z+div.", "Z+Div."), ("ZB+DIV", "ZB+Div."),
                          ("workshop", "WORKSHOP"), ("zb", "ZB")]:
        html = _seite(admin, art=roh)
        assert f'<option value="{erwartet}" selected' in html, roh
        assert "Art bitte wählen" not in html, roh


def test_krumme_uhrzeit_wird_gerundet_und_gemeldet(admin):
    html = _seite(admin, startzeit="14:10")
    assert 'value="14:00" selected' in html
    assert "14:10 auf 14:00 gerundet" in html


def test_kaputtes_datum_bleibt_leer_mit_hinweis(admin):
    html = _seite(admin, datum="14.11.2026")
    assert "nicht lesbar" in html
    assert 'value="14.11.2026"' not in html


def test_ohne_neu_kein_vorbefuellen(admin):
    html = admin.get("/admin/reservierungen?kunde_firma=Sollte+nicht+erscheinen").text
    assert "Sollte nicht erscheinen" not in html
