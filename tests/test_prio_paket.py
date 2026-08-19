"""Prio-Paket Scheinselbstständigkeit II: Auto-Bestellung bei Zusage,
Lieferantenbewertung (1–10) statt EP/5-Sterne, jährliche Scoring-Erinnerung."""
from datetime import date, timedelta
from types import SimpleNamespace

from database import SessionLocal
from models import Dienstleister, Verfuegbarkeitsanfrage, Benachrichtigung
from factories import make_dienstleister, make_event, make_anfrage, reload, portal_login


# ── Lieferantenbewertung im Ranking ───────────────────────────────────────────

def test_score_nutzt_lieferantenbewertung():
    from distance import compute_score
    def dl(bew):
        return SimpleNamespace(plz="", strasse="", stadt="", logistiker=False,
                               lieferantenbewertung=bew)
    top, _ = compute_score(dl(10), None, False)
    neutral, _ = compute_score(dl(None), None, False)
    schwach, _ = compute_score(dl(2), None, False)
    assert top == 40 and neutral == 24 and schwach == 8   # Bewertung × 4, unbewertet = 6


def test_formular_speichert_bewertung(admin):
    did = make_dienstleister()
    d = reload(Dienstleister, did)
    daten = {"vorname": d.vorname, "nachname": d.nachname, "email": d.email,
             "aktiv": "true", "lieferantenbewertung": "9"}
    r = admin.post(f"/admin/dienstleister/{did}/edit", data=daten, follow_redirects=False)
    assert r.status_code == 303
    assert reload(Dienstleister, did).lieferantenbewertung == 9
    h = admin.get(f"/admin/dienstleister/{did}").text
    assert "★ 9/10" in h and "Bisherige Aufträge" in h
    assert "Erfahrungspunkte" not in h


def test_formular_zeigt_10_sterne_auswahl(admin):
    h = admin.get("/admin/dienstleister/new").text
    assert "Interne Lieferantenbewertung" in h and "★ 10/10" in h
    assert 'name="erfahrungspunkte"' not in h and 'name="qualitaet"' not in h


# ── Auto-Bestellung: Vergütungstext + Sicherung ───────────────────────────────

def _ev_ns(**kw):
    base = dict(anlass="Sommerfest", marke="Kindsalabim", datum=date(2026, 9, 1),
                startzeit="14:00", endzeit="18:00",
                veranstaltungsort="Markt 1, 45127 Essen")
    base.update(kw)
    return SimpleNamespace(**base)


def _a_ns(rolle="Teamer", budget=None, als_logistiker=False):
    return SimpleNamespace(rolle_anfrage=rolle, budget=budget, als_logistiker=als_logistiker)


def _d_ns(st=None, sk=None):
    return SimpleNamespace(vorname="Max", nachname="Muster", strasse="", plz="", stadt="",
                           stundensatz_teamer=st, stundensatz_kuenstler=sk,
                           kuenstler_sparte=None)


def test_verguetung_teamer_mit_stundensatz():
    from bestellung import verguetungs_positionen
    haupt, zusatz = verguetungs_positionen(_a_ns(), _ev_ns(), _d_ns(st=20.0))
    assert haupt.startswith("ca. 80 €")            # 4 Std. × 20 €
    assert "4 Std. à 20,00 €/Std." in haupt and "Kalkulationsgrundlage" in haupt
    text = " ".join(zusatz)
    # Verlängerung/frühere Anwesenheit, Fahrzeit und Nebenkosten sind mitbestellt
    assert "längere Aktionszeit oder frühere Anwesenheit" in text and "20,00 €/Std." in text
    assert "Fahrzeit: 10,00 €/Std." in text and "ohne Stau" in text
    assert "Park- und Mautgebühren" in text


def test_verguetung_kuenstler_pauschal_mit_nebenkosten():
    from bestellung import verguetungs_positionen
    haupt, zusatz = verguetungs_positionen(_a_ns("Künstler", budget=300.0), _ev_ns(), _d_ns())
    assert haupt.startswith("Pauschalhonorar 300,00 € netto")
    assert "inklusive Fahrtkosten und Fahrzeit" in haupt
    text = " ".join(zusatz)
    assert "Park- und Mautgebühren" in text          # Nebenkosten trotz Pauschale
    assert "längere Aktionszeit" in text
    assert "Fahrzeit:" not in text                    # in der Pauschale enthalten


def test_verguetung_kuenstler_stundensatz_fallback():
    from bestellung import verguetungs_positionen
    haupt, _ = verguetungs_positionen(_a_ns("Künstler"), _ev_ns(), _d_ns(sk=60.0))
    assert haupt.startswith("ca. 240 €")             # 4 Std. × 60 €


def test_verguetung_logistiker_zusatzposition():
    from bestellung import verguetungs_positionen
    _, zusatz = verguetungs_positionen(_a_ns(als_logistiker=True), _ev_ns(), _d_ns(st=20.0))
    text = " ".join(zusatz)
    assert "Gesondert beauftragte Transportleistung" in text
    assert "Abholung des Materials" in text and "Rücklieferung" in text


def test_verguetung_sicherung_ohne_zahlen():
    from bestellung import verguetungs_positionen
    assert verguetungs_positionen(_a_ns(), _ev_ns(), _d_ns())[0] is None            # kein Satz
    assert verguetungs_positionen(_a_ns("Künstler"), _ev_ns(), _d_ns())[0] is None  # nichts hinterlegt
    assert verguetungs_positionen(_a_ns(), _ev_ns(startzeit="", endzeit=""),
                                  _d_ns(st=20.0))[0] is None


def test_bestellung_pdf_baut():
    from bestellung import build_bestellung_pdf, verguetungs_positionen
    a, ev, d = _a_ns(), _ev_ns(marke="Knallfrosch"), _d_ns(st=20.0)
    haupt, zusatz = verguetungs_positionen(a, ev, d)
    pdf = build_bestellung_pdf(a, ev, d, haupt, zusatz)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_bestellung_mail_beruhigt_wegen_mehraufwand(client, mails):
    did = make_dienstleister(stundensatz_teamer=20.0)
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    html = next(m[2] for m in mails if m[1].startswith("Bestellung:"))
    assert "Kalkulationsgrundlage" in html
    assert "Rückfrage vorab brauchst du dafür nicht" in html


# ── Auto-Bestellung: kompletter Zusage-Flow ───────────────────────────────────

def _letzte_glocke(typ):
    s = SessionLocal()
    try:
        return s.query(Benachrichtigung).filter(Benachrichtigung.typ == typ)\
                .order_by(Benachrichtigung.id.desc()).first()
    finally:
        s.close()


def test_zusage_verschickt_bestellung(client, mails):
    did = make_dienstleister(stundensatz_teamer=25.0)
    eid = make_event()
    aid = make_anfrage(eid, did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.status == "Ja" and a.bestellung_am
    betreffe = [m[1] for m in mails]
    assert any(b.startswith("Bestellung:") for b in betreffe)
    g = _letzte_glocke("bestellung")
    assert g and g.titel.startswith("Bestellung verschickt")


def test_zusage_ohne_stundensatz_keine_bestellung_aber_hinweis(client, mails):
    did = make_dienstleister(stundensatz_teamer=None)
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.status == "Ja" and a.bestellung_am is None
    assert not any(m[1].startswith("Bestellung:") for m in mails)
    g = _letzte_glocke("bestellung")
    assert g and "Keine Bestellung erzeugt" in g.titel and "Stundensatz" in g.text


def test_bestellung_idempotent(client, mails):
    from bestellung import bestellung_erzeugen_async
    did = make_dienstleister(stundensatz_teamer=20.0)
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    n_vorher = sum(1 for m in mails if m[1].startswith("Bestellung:"))
    bestellung_erzeugen_async(aid)   # zweiter Aufruf (z. B. Doppelklick) → nichts passiert
    assert sum(1 for m in mails if m[1].startswith("Bestellung:")) == n_vorher


def test_absage_erzeugt_keine_bestellung(client, mails):
    did = make_dienstleister(stundensatz_teamer=20.0)
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Nein"}, follow_redirects=False)
    assert not any(m[1].startswith("Bestellung:") for m in mails)
    assert reload(Verfuegbarkeitsanfrage, aid).bestellung_am is None


# ── Jährliche Scoring-Erinnerung ──────────────────────────────────────────────

def test_scoring_erinnerung_nach_einem_jahr(db):
    from routes.cron import _run_scoring_erinnerungen
    alt = make_dienstleister(vorname="Erna", nachname="Alt",
                             scoring_datum=(date.today() - timedelta(days=400)).isoformat())
    frisch = make_dienstleister(scoring_datum=date.today().isoformat())
    ohne = make_dienstleister()   # nie bewertet → keine Erinnerung
    count = _run_scoring_erinnerungen(db)
    assert count >= 1
    g = _letzte_glocke("dl_unterlagen")
    assert g and "Status-Scoring aktualisieren" in g.titel and "Erna Alt" in g.text
    assert reload(Dienstleister, alt).scoring_erinnert_am == date.today()
    assert reload(Dienstleister, frisch).scoring_erinnert_am is None
    assert reload(Dienstleister, ohne).scoring_erinnert_am is None
    # 30-Tage-Sperre: direkt nochmal laufen lassen → niemand wird erneut gemeldet
    s = SessionLocal()
    try:
        assert _run_scoring_erinnerungen(s) == 0
    finally:
        s.close()
