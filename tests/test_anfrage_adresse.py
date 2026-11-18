"""Adresse in der Verfügbarkeitsanfrage: Teamer sehen die volle Adresse,
Künstler nur PLZ/Ort (Kundenschutz). Entscheidung Aykut 22.07.2026."""
from datetime import date
from types import SimpleNamespace

import email_service
from choices import anfrage_ort

ADRESSE = "Musterstraße 12, 45127 Essen"


def _ev(**over):
    base = dict(marke="Kindsalabim", anlass="Sommerfest", datum=date(2026, 8, 1),
                startzeit="14:00", endzeit="18:00", veranstaltungsort=ADRESSE,
                produkte="Spieleland", transporter_angeboten=False, material_info="")
    base.update(over)
    return SimpleNamespace(**base)


def _dl():
    return SimpleNamespace(vorname="Max", nachname="Muster", email="dl@example.com")


def _gesendet(fn, *args, **kw):
    captured = {}
    orig = email_service._deliver
    email_service._deliver = lambda to, subject, html, anhaenge=None: captured.setdefault("html", html)
    try:
        fn(*args, **kw)
    finally:
        email_service._deliver = orig
    return captured.get("html", "")


def test_anfrage_ort_nach_rolle():
    assert anfrage_ort(ADRESSE, "Teamer") == ADRESSE
    assert anfrage_ort(ADRESSE, "Künstler") == "45127 Essen"
    assert anfrage_ort(ADRESSE, None) == "45127 Essen"   # ohne Rolle konservativ maskieren
    assert anfrage_ort("", "Teamer") == ""


def test_anfrage_mail_teamer_sieht_volle_adresse():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(), 1, "http://t", rolle="Teamer")
    assert "Musterstraße 12" in html


def test_anfrage_mail_kuenstler_sieht_nur_plz_ort():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(), 1, "http://t", rolle="Künstler")
    assert "Musterstraße 12" not in html and "45127 Essen" in html


def test_serie_mail_folgt_der_rolle():
    tage = [_ev(), _ev(datum=date(2026, 8, 2))]
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t", rolle="Teamer")
    assert "Musterstraße 12" in html
    html = _gesendet(email_service.send_serie_anfrage, _dl(), tage, "http://t")
    assert "Musterstraße 12" not in html   # Default bleibt maskiert


def test_plz_fallback_kommt_vom_veranstaltungsort_nicht_vom_kunden(admin, db):
    # Aykut 18.11.2026, Korrektur: Agentur (Hauptsitz Düsseldorf) bucht fuer Essen -
    # die PLZ im Kuenstler-Ort darf NICHT vom Kundenhauptsitz stammen.
    from models import Kunde, Event
    from factories import make_event, reload
    k = Kunde(firma="Fullservice Event GmbH", plz="40210", ort="Düsseldorf")
    db.add(k); db.commit()
    eid = make_event(kunde_id=k.id, kunde_firma="Fullservice Event GmbH",
                     veranstaltungsort="Spielstraße 1, Essen",   # keine PLZ in der Adresse
                     cl_ort_gleich=False, cl_ort_strasse="Spielstraße 1",
                     cl_ort_plz_ort="45127 Essen")
    ev = reload(Event, eid)
    assert anfrage_ort(ev.veranstaltungsort, "Künstler",
                       __import__("veranstaltungsort").anschrift(ev)[2]) == "45127 Essen"


def test_ohne_checkliste_bleibt_nur_der_ort_ohne_plz(admin, db):
    from models import Event
    from factories import make_event, reload
    eid = make_event(veranstaltungsort="Spielstraße 1, Essen")
    ev = reload(Event, eid)
    import veranstaltungsort
    assert anfrage_ort(ev.veranstaltungsort, "Künstler", veranstaltungsort.anschrift(ev)[2]) == "Essen"


def test_anfrage_text_ohne_gedankenstrich_und_bittet_um_antwort_auch_ohne_zeit():
    # Aykut 18.11.2026: "- du bist sofort..." klang nach "nur klicken, wenn verfuegbar" ->
    # Teamer ohne Kapazitaet reagierten gar nicht. Ausserdem keine Gedankenstriche.
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(), 1, "http://t", rolle="Teamer")
    intro = html.split("Hallo Max")[1].split("</p>")[0]
    assert "–" not in intro and "—" not in intro and " - " not in intro
    assert "auch, wenn du keine Zeit hast" in html


def test_aktionen_statt_produkte_label():
    html = _gesendet(email_service.send_verfuegbarkeitsanfrage,
                     _dl(), _ev(produkte="Zaubershow"), 1, "http://t", rolle="Teamer")
    assert ">Aktionen<" in html and ">Produkte<" not in html
