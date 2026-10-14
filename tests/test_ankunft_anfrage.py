"""Ankunft schon in der Job-Anfrage und Auf-/Abbau als Arbeitszeit (Aykut 14.10.2026).

Bisher stand die Ankunft nur im Briefing, also erst nach der Zusage: Bei zwei Stunden
Aufbau sah ein Teamer „Aktion 13 Uhr“ und plante mit 12:30 Uhr. Und die Bestellung
rechnete nur die Aktionszeit, obwohl Auf- und Abbau Arbeitszeit sind."""
from datetime import date, timedelta
from types import SimpleNamespace

import ankunft
import email_service
import honorare
from bestellung import verguetungs_positionen
from factories import make_dienstleister, make_event, make_anfrage, portal_login


def _ev(**over):
    base = dict(marke="Kindsalabim", anlass="Sommerfest", datum=date(2026, 8, 1),
                startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                produkte="Spieleland", ankunft_modus="auto", ankunft_text=None,
                transporter_angeboten=False, material_info="")
    base.update(over)
    return SimpleNamespace(**base)


def _a(**over):
    base = dict(rolle_anfrage="Teamer", budget=None, als_logistiker=False,
                einsatz_von=None, einsatz_bis=None)
    base.update(over)
    return SimpleNamespace(**base)


def _dl(**over):
    base = dict(vorname="Max", nachname="Muster", email="dl@example.com",
                strasse="", plz="45127", stadt="Essen",
                stundensatz_teamer=20.0, stundensatz_kuenstler=None, kuenstler_sparte=None)
    base.update(over)
    return SimpleNamespace(**base)


def _gesendet(fn, *args, **kw):
    captured = {}
    orig = email_service._deliver
    email_service._deliver = lambda to, subject, html, anhaenge=None: captured.setdefault("html", html)
    try:
        fn(*args, **kw)
    finally:
        email_service._deliver = orig
    return captured.get("html", "")


# ── Ankunft in der Anfrage-Mail ──────────────────────────────────────────────

def test_anfrage_mail_zeigt_ankunft():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage, _dl(), _ev(), 1, "http://t",
                     rolle="Teamer", anfrage=_a())
    assert "Ankunft" in html and "13:00 Uhr (= 60 Min vor Aktionsbeginn)" in html


def test_eigene_aktionszeit_verschiebt_ankunft():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage, _dl(), _ev(), 1, "http://t",
                     rolle="Teamer", anfrage=_a(einsatz_von="15:00", einsatz_bis="16:00"))
    assert "14:00 Uhr (= 60 Min vor Aktionsbeginn)" in html
    assert "13:00 Uhr (=" not in html


def test_sonderfall_text_wird_uebernommen():
    ev = _ev(ankunft_modus="sonderfall", ankunft_text="Am Vortag 17 Uhr Aufbau")
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage, _dl(), ev, 1, "http://t",
                     rolle="Teamer", anfrage=_a())
    assert "Am Vortag 17 Uhr Aufbau" in html


def test_sonderfall_ohne_text_zeigt_keine_ankunft():
    ev = _ev(ankunft_modus="sonderfall", ankunft_text="")
    assert ankunft.ankunft_anfrage(ev) == ""
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage, _dl(), ev, 1, "http://t",
                     rolle="Teamer", anfrage=_a())
    assert ">Ankunft<" not in html


def test_kuenstler_in_eigenverantwortung():
    ev = _ev(produkte="Zaubershow")
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage, _dl(), ev, 1, "http://t",
                     rolle="Künstler", anfrage=_a(rolle_anfrage="Künstler"))
    assert "in Eigenverantwortung" in html and "Min vor Aktionsbeginn" not in html


def test_serien_anfrage_zeigt_ankunft_je_tag():
    tage = [_ev(), _ev(datum=date(2026, 8, 2), startzeit="10:00", endzeit="14:00")]
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t",
                     rolle="Teamer", anfragen=[_a(), _a()])
    assert "Ankunft: 13:00 Uhr" in html and "Ankunft: 09:00 Uhr" in html


def test_serien_anfrage_mit_eigener_aktionszeit():
    tage = [_ev(), _ev(datum=date(2026, 8, 2))]
    anfr = [_a(einsatz_von="15:00", einsatz_bis="16:00")] * 2
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t",
                     rolle="Teamer", anfragen=anfr)
    assert "deine Aktionszeit 15:00" in html and "Ankunft: 14:00 Uhr" in html


# ── Ankunft im Portal ────────────────────────────────────────────────────────

def test_portal_zeigt_ankunft_in_offener_anfrage(client):
    did = make_dienstleister()
    eid = make_event(produkte="Spieleland", datum=date.today() + timedelta(days=20),
                     startzeit="13:00", endzeit="17:00")
    make_anfrage(eid, did, status="Ausstehend")
    portal_login(client, did)
    h = client.get("/portal").text
    assert "Ankunft: 12:00 Uhr" in h


# ── Auf- und Abbau als Arbeitszeit ───────────────────────────────────────────

def test_aufbau_aus_ankunft_sonst_30_minuten():
    assert ankunft.aufbau_minuten(_ev(produkte="Spieleland")) == 60
    assert ankunft.aufbau_minuten(_ev(produkte="Bastelaktion")) == 45
    assert ankunft.aufbau_minuten(_ev(ankunft_modus="90")) == 90
    # keine Ankunftszeit in Minuten → pauschal 30 Min
    assert ankunft.aufbau_minuten(_ev(produkte="Zaubershow")) == 30
    assert ankunft.aufbau_minuten(_ev(ankunft_modus="sonderfall", ankunft_text="x")) == 30
    assert ankunft.ABBAU_MINUTEN == 30


def test_bestellung_rechnet_auf_und_abbau_ein():
    haupt, zusatz = verguetungs_positionen(_a(), _ev(), _dl())
    # 4 Std. Aktion + 1 Std. Aufbau (Spieleland) + 0,5 Std. Abbau = 5,5 Std. × 20 €
    assert haupt.startswith("ca. 110 €")
    assert "5,5 Std.: 4 Std. Aktion, 1 Std. Aufbau, 0,5 Std. Abbau" in haupt
    assert "Längere Auf- und Abbauzeiten" in " ".join(zusatz)


def test_bestellung_nimmt_eigene_aktionszeit():
    """Show 15 bis 16 Uhr in einem Event von 14 bis 18 Uhr: 1 Std. Aktion, nicht 4."""
    haupt, _ = verguetungs_positionen(_a(einsatz_von="15:00", einsatz_bis="16:00"),
                                      _ev(), _dl())
    assert haupt.startswith("ca. 50 €")          # (1 + 1 + 0,5) × 20 €


def test_eigene_aktionszeit_ohne_ende_laeuft_bis_eventende():
    haupt, _ = verguetungs_positionen(_a(einsatz_von="16:00"), _ev(), _dl())
    assert "2 Std. Aktion" in haupt


def test_schaetzung_nutzt_dieselbe_arbeitszeit():
    wert = honorare.schaetzung(_a(), _ev(), _dl(stundensatz_teamer=20.0))
    assert wert >= 110.0                          # 5,5 Std. × 20 € plus Fahrzeit
