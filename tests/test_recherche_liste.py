"""Firmenliste in Wochen-Paketen (Aykut 14.10.2026): einmal hochladen, die App
recherchiert fest drei Pakete zu fünf Firmen pro Woche, angestoßen vom ohnehin
laufenden Cron-Ping. Kein Test ruft die Claude-API: auftrag_ausfuehren ist gemockt."""
from datetime import datetime, timedelta

import pytest

import recherche
from config import get_config
from models import Kunde, Rechercheauftrag, RechercheListenFirma
from notifications import set_setting

CSV = ("﻿stufe;name;ort;plz\n"
       + "".join(f"A;Testfirma Liste {i};Essen;45127\n" for i in range(1, 13))).encode("utf-8")


def _aufraeumen(db):
    db.query(RechercheListenFirma).delete()
    for a in db.query(Rechercheauftrag).all():
        if recherche.LISTE_KENNUNG in (a.auftrag or ""):
            db.delete(a)
        elif a.status in ("offen", "laeuft"):
            a.status = "fertig"
    for k in (recherche.LISTE_PAUSE_KEY, recherche.LISTE_WOCHE_KEY, recherche.LISTE_NETZWERK_KEY):
        set_setting(db, k, "")
    db.query(Kunde).filter(Kunde.firma.like("Testfirma Liste%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def leer(db, monkeypatch):
    _aufraeumen(db)
    monkeypatch.setattr(recherche, "auftrag_ausfuehren", lambda aid: None)
    yield db
    db.rollback()
    _aufraeumen(db)


def _fertig(db, a):
    db.refresh(a)
    a.status, a.anzahl = "fertig", 5
    db.commit()


def test_liste_einlesen_ohne_doppelte(leer):
    assert recherche.liste_einlesen(leer, CSV) == (12, 0)
    assert recherche.liste_einlesen(leer, CSV) == (0, 12)
    erste = (leer.query(RechercheListenFirma).order_by(RechercheListenFirma.position).first())
    assert erste.name == "Testfirma Liste 1" and erste.ort == "Essen"


def test_liste_einlesen_mit_komma_und_spalte_firma(leer):
    neu, _ = recherche.liste_einlesen(leer, b"firma,ort\nTestfirma Liste K,Bochum\n")
    assert neu == 1


def test_paket_mit_fuenf_firmen_und_netzwerk_marker(leer):
    recherche.liste_einlesen(leer, CSV)
    a = recherche.liste_tick(leer)
    assert a is not None and a.automatisch
    assert a.auftrag.startswith(recherche.NETZWERK_MARKER)
    assert "Testfirma Liste 1 (Essen)" in a.auftrag and "Testfirma Liste 5" in a.auftrag
    assert "Testfirma Liste 6" not in a.auftrag
    assert leer.query(RechercheListenFirma).filter_by(status="im_lauf").count() == 5


def test_ohne_netzwerk_haekchen_kein_marker(leer):
    recherche.liste_einlesen(leer, CSV)
    set_setting(leer, recherche.LISTE_NETZWERK_KEY, "0")
    leer.commit()
    a = recherche.liste_tick(leer)
    assert not a.auftrag.startswith(recherche.NETZWERK_MARKER)


def test_nie_zwei_pakete_gleichzeitig(leer):
    recherche.liste_einlesen(leer, CSV)
    assert recherche.liste_tick(leer) is not None
    assert recherche.liste_tick(leer) is None          # erstes läuft noch


def test_drei_pakete_pro_woche_dann_ruhe(leer):
    """Zwölf Firmen: drei Pakete diese Woche (5 + 5 + 2), dann Schluss bis Montag."""
    recherche.liste_einlesen(leer, CSV + b"A;Testfirma Liste 13;Essen;45127\n"
               b"A;Testfirma Liste 14;Essen;45127\nA;Testfirma Liste 15;Essen;45127\n"
               b"A;Testfirma Liste 16;Essen;45127\n")
    for _ in range(3):
        a = recherche.liste_tick(leer)
        assert a is not None
        _fertig(leer, a)
    assert recherche.liste_tick(leer) is None
    assert recherche.liste_pakete_diese_woche(leer) == 3
    # Nächste Woche geht es weiter
    assert recherche.liste_tick(leer, datetime.now() + timedelta(days=7)) is not None


def test_wochenmenge_einstellbar(leer):
    recherche.liste_einlesen(leer, CSV)
    set_setting(leer, recherche.LISTE_WOCHE_KEY, "1")
    leer.commit()
    _fertig(leer, recherche.liste_tick(leer))
    assert recherche.liste_tick(leer) is None


def test_wochenstart_montag_sieben_uhr():
    montag_frueh = datetime(2026, 10, 12, 6, 30)       # Montag vor 7 Uhr: noch Vorwoche
    assert recherche._wochenstart(montag_frueh) == datetime(2026, 10, 5, 7, 0)
    mittwoch = datetime(2026, 10, 14, 12, 0)
    assert recherche._wochenstart(mittwoch) == datetime(2026, 10, 12, 7, 0)


def test_pause_haelt_an(leer):
    recherche.liste_einlesen(leer, CSV)
    set_setting(leer, recherche.LISTE_PAUSE_KEY, "1")
    leer.commit()
    assert recherche.liste_tick(leer) is None


def test_firma_im_crm_wird_uebersprungen(leer):
    recherche.liste_einlesen(leer, CSV)
    leer.add(Kunde(firma="testfirma liste 1", herkunft="akquise", pipeline_status="lead"))
    leer.commit()
    a = recherche.liste_tick(leer)
    assert "Testfirma Liste 1 " not in a.auftrag and "Testfirma Liste 6" in a.auftrag
    f = leer.query(RechercheListenFirma).filter_by(name="Testfirma Liste 1").one()
    assert f.status == "uebersprungen"


def test_fertiges_paket_wird_erledigt(leer):
    recherche.liste_einlesen(leer, CSV)
    _fertig(leer, recherche.liste_tick(leer))
    recherche._liste_aufraeumen(leer)
    assert leer.query(RechercheListenFirma).filter_by(status="erledigt").count() == 5


def test_fehlschlag_einmal_wiederholen_dann_aufgeben(leer):
    recherche.liste_einlesen(leer, CSV)
    set_setting(leer, recherche.LISTE_WOCHE_KEY, "5")
    leer.commit()
    a = recherche.liste_tick(leer)
    a.status = "fehler"
    leer.commit()
    b = recherche.liste_tick(leer)                    # dieselben fünf noch einmal
    assert "Testfirma Liste 1 (" in b.auftrag
    b.status = "fehler"
    leer.commit()
    c = recherche.liste_tick(leer)                    # jetzt die nächsten fünf
    assert "Testfirma Liste 1 (" not in c.auftrag and "Testfirma Liste 6" in c.auftrag
    assert leer.query(RechercheListenFirma).filter_by(status="fehlgeschlagen").count() == 5


def test_abgebrochener_lauf_blockiert_nicht(leer):
    """Neustart beim Deploy: ein Lauf bleibt auf „läuft" stehen. Nach 90 Minuten gilt er
    als abgebrochen, sonst stünde die Liste für immer still."""
    recherche.liste_einlesen(leer, CSV)
    a = recherche.liste_tick(leer)
    a.status = "laeuft"
    leer.commit()
    assert recherche.liste_tick(leer) is None
    spaeter = datetime.now() + timedelta(minutes=recherche.LAUF_ABGEBROCHEN_MIN + 5)
    neu = recherche.liste_tick(leer, spaeter)
    leer.refresh(a)
    assert a.status == "fehler" and "Neustart" in a.meldung
    assert neu is not None


def test_frischer_lauf_gilt_nicht_als_abgebrochen(leer):
    recherche.liste_einlesen(leer, CSV)
    a = recherche.liste_tick(leer)
    recherche._liste_aufraeumen(leer)
    leer.refresh(a)
    assert a.status == "offen"


# ── Anstoß über den Cron-Ping ────────────────────────────────────────────────

def _ping(client, pfad="/cron/bericht-erinnerung"):
    return client.get(pfad, headers={"X-Cron-Secret": get_config().get("cron_secret", "")})


def test_bericht_ping_startet_paket(client, leer):
    recherche.liste_einlesen(leer, CSV)
    r = _ping(client)
    assert r.status_code == 200 and r.json()["recherche_liste"]


def test_bericht_ping_ohne_liste_startet_nichts(client, leer):
    r = _ping(client)
    assert r.status_code == 200 and r.json()["recherche_liste"] is None


def test_ping_ohne_secret_startet_nichts(client, leer):
    recherche.liste_einlesen(leer, CSV)
    assert client.get("/cron/bericht-erinnerung").status_code == 401
    assert leer.query(RechercheListenFirma).filter_by(status="im_lauf").count() == 0


# ── Oberfläche ───────────────────────────────────────────────────────────────

def test_hochladen_und_anzeigen(admin, leer):
    r = admin.post("/admin/crm/akquise/liste", data={"netzwerk": "1"},
                   files={"datei": ("liste.csv", CSV, "text/csv")}, follow_redirects=True)
    assert r.status_code == 200
    assert "12 Firmen in die Liste übernommen" in r.text
    assert "0 von 12" in r.text and "Testfirma Liste 1" in r.text


def test_paket_heisst_im_verlauf_liste(admin, leer):
    recherche.liste_einlesen(leer, CSV)
    recherche.liste_tick(leer)
    h = admin.get("/admin/crm/akquise").text
    assert "(Liste)" in h


def test_pausieren_und_wochenmenge_ueber_knoepfe(admin, leer):
    recherche.liste_einlesen(leer, CSV)
    admin.post("/admin/crm/akquise/liste/einstellen", data={"aktion": "pause"})
    admin.post("/admin/crm/akquise/liste/einstellen", data={"aktion": "woche", "woche": "2"})
    leer.expire_all()
    assert recherche.liste_tick(leer) is None
    assert recherche.liste_wochenlimit(leer) == 2
    assert "Fortsetzen" in admin.get("/admin/crm/akquise").text


def test_offene_firmen_entfernen(admin, leer):
    recherche.liste_einlesen(leer, CSV)
    recherche.liste_tick(leer)
    admin.post("/admin/crm/akquise/liste/einstellen", data={"aktion": "entfernen"})
    leer.expire_all()
    assert leer.query(RechercheListenFirma).filter_by(status="offen").count() == 0
    assert leer.query(RechercheListenFirma).filter_by(status="im_lauf").count() == 5
