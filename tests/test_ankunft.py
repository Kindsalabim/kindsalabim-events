"""Ankunft/Treffpunkt: Auto-Vorlauf aus Aktionen, Anzeige, Briefing, Speichern."""
from types import SimpleNamespace

import ankunft
import email_service
from models import Event
from factories import make_event, reload, briefing_event_ns, briefing_dl_ns


# ── Auto-Vorlauf-Logik ────────────────────────────────────────────────────────
def test_auto_vorlauf_gross_60():
    assert ankunft.auto_vorlauf("Spieleland, Mini Mitmachzirkus, Bunter Bastelspaß") == 60
    assert ankunft.auto_vorlauf("Hüpfburg") == 60


def test_auto_vorlauf_bastel_45():
    assert ankunft.auto_vorlauf("Bunter Bastelspaß") == 45
    assert ankunft.auto_vorlauf("Bunter Bastelspaß, Glitzertattoos") == 45


def test_auto_vorlauf_leicht_30():
    assert ankunft.auto_vorlauf("Glitzertattoos") == 30
    assert ankunft.auto_vorlauf("Glitzertattoos, Kinderschminken") == 30  # Kinderschminke im Mix = 30


def test_auto_vorlauf_nur_kuenstler_eigen():
    assert ankunft.auto_vorlauf("Zaubershow") is None
    assert ankunft.auto_vorlauf("Kinderschminken") is None              # allein = Eigenverantwortung
    assert ankunft.auto_vorlauf("Zaubershow, Ballonmodellage") is None


def test_kinderschminke_mit_bastel_45():
    assert ankunft.auto_vorlauf("Kinderschminken, Bunter Bastelspaß") == 45


# ── Anzeige-Text ──────────────────────────────────────────────────────────────
def test_anzeige_auto_rechnet_uhrzeit():
    ev = SimpleNamespace(ankunft_modus="auto", produkte="Spieleland", startzeit="12:00", ankunft_text="", treffpunkt="")
    assert ankunft.ankunft_anzeige(ev).startswith("11:00 Uhr")


def test_anzeige_eigen():
    ev = SimpleNamespace(ankunft_modus="eigen", produkte="Spieleland", startzeit="12:00", ankunft_text="", treffpunkt="")
    assert ankunft.ankunft_anzeige(ev) == "in Eigenverantwortung"


def test_anzeige_sonderfall_freitext():
    ev = SimpleNamespace(ankunft_modus="sonderfall", produkte="Spieleland", startzeit="12:00",
                         ankunft_text="Aufbau am Vortag bis 14:00 Uhr", treffpunkt="")
    assert ankunft.ankunft_anzeige(ev) == "Aufbau am Vortag bis 14:00 Uhr"


def test_anzeige_fixer_vorlauf():
    ev = SimpleNamespace(ankunft_modus="45", produkte="Zaubershow", startzeit="12:00", ankunft_text="", treffpunkt="")
    assert ankunft.ankunft_anzeige(ev).startswith("11:15 Uhr")


def test_treffpunkt_default():
    assert ankunft.treffpunkt_anzeige(SimpleNamespace(treffpunkt="")) == "vor dem Haupteingang"
    assert ankunft.treffpunkt_anzeige(SimpleNamespace(treffpunkt="Parkplatz P3")) == "Parkplatz P3"


# ── Briefing-Mail ─────────────────────────────────────────────────────────────
def test_mail_ankunft_block_und_kein_aufbau(mails):
    ev = briefing_event_ns(produkte="Spieleland", startzeit="12:00", endzeit="16:00",
                           ankunft_modus="auto", treffpunkt="vor dem Haupteingang",
                           cl_aufbau_von="09:00", cl_aufbau_bis="11:00", cl_abbau_von="16:00")
    email_service.send_briefing([briefing_dl_ns()], ev, "https://x")
    html = mails[-1][2]
    # Ankunft/Treffpunkt stehen in der ersten Karte, direkt nach der Aktionszeit
    assert "Ankunft" in html and "11:00 Uhr" in html
    assert html.index("Aktionszeit") < html.index("Ankunft")
    # Kunden-Aufbau-/Abbauzeiten dürfen NICHT mehr im Dienstleister-Briefing stehen
    assert ">Aufbau<" not in html and ">Abbau<" not in html


# ── Speichern über das Formular ───────────────────────────────────────────────
def test_event_speichert_ankunft_felder(admin):
    eid = make_event()
    data = {"anlass": "Fest", "datum": "2026-08-01", "startzeit": "12:00", "endzeit": "16:00",
            "veranstaltungsort": "Markt 1, 45127 Essen", "kunde_firma": "K", "produkte": ["Zaubershow"],
            "marke": "Kindsalabim", "status": "Gebucht",
            "ankunft_modus": "sonderfall", "ankunft_text": "Aufbau am Vortag bis 14 Uhr",
            "treffpunkt": "Parkplatz P3, dann gemeinsam rein"}
    r = admin.post(f"/admin/events/{eid}/edit", data=data, follow_redirects=False)
    assert r.status_code == 303
    ev = reload(Event, eid)
    assert ev.ankunft_modus == "sonderfall"
    assert ev.ankunft_text == "Aufbau am Vortag bis 14 Uhr"
    assert ev.treffpunkt == "Parkplatz P3, dann gemeinsam rein"
