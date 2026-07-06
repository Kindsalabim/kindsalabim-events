"""Briefing-Wünsche (Aykut, 02.07.): Ankunft/Treffpunkt direkt nach Aktionszeit,
Teamleiter zuerst, Künstler-Sparte im Team, Regeln-Seite 2, Auf-/Abbau raus aus
„Briefing bearbeiten", PDF-Logo-Header."""
import io
from datetime import date
from types import SimpleNamespace

import pypdf

import email_service
from briefing_pdf import build_briefing_pdf
from factories import make_event, reload
from models import Event


def _ev(**over):
    base = dict(marke="Kindsalabim", anlass="Fest", kunde_firma="X", datum=date(2026, 8, 1),
                startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen",
                produkte="Zaubershow", kunde_kontakt="Hr. A", kunde_telefon="0201",
                hinweise="", teamleiter_id=None,
                cl_aufbauort="Indoor", cl_parkplatz="", cl_teamkleidung="", cl_verpflegung="")
    base.update(over)
    return SimpleNamespace(**base)


def _dl(id, vorname, nachname, sparte=None):
    return SimpleNamespace(id=id, vorname=vorname, nachname=nachname,
                           telefon="0151", email=f"{vorname.lower()}@example.com",
                           kuenstler_sparte=sparte)


# ── Mail ─────────────────────────────────────────────────────────────────────────

def test_mail_ankunft_direkt_nach_aktionszeit(mails):
    email_service.send_briefing([_dl(1, "Max", "M")], _ev(), "https://x")
    html = mails[-1][2]
    assert html.index("Aktionszeit") < html.index("📍 Ankunft") < html.index("📍 Treffpunkt") < html.index("Indoor/Outdoor")


def test_mail_teamleiter_steht_zuerst(mails):
    team = [_dl(1, "Anna", "Erste"), _dl(2, "Bernd", "Leiter")]
    email_service.send_briefing(team, _ev(teamleiter_id=2), "https://x")
    html = mails[-1][2]
    assert html.index("Bernd Leiter") < html.index("Anna Erste")
    assert "TEAMLEITER" in html


def test_mail_kuenstler_sparte_erscheint(mails):
    team = [_dl(1, "Max", "M", sparte="Ballonkünstler"),
            _dl(2, "Lisa", "L", sparte="Sonstiges"),
            _dl(3, "Tom", "T")]
    email_service.send_briefing(team, _ev(), "https://x")
    html = mails[-1][2]
    assert "(Ballonmodellage)" in html          # gemapptes Label
    assert "(Sonstiges)" not in html            # „Sonstiges" bewusst ohne Label


def test_mail_regeln_abschnitt(mails):
    email_service.send_briefing([_dl(1, "Max", "M")], _ev(), "https://x",
                                regeln="1. Pünktlich sein\n2. Handy aus")
    html = mails[-1][2]
    # Text ohne „## " → eine Box „Grundlegende Regelungen"; Nummerierung ersetzt der Pfeil
    assert "Grundlegende Regelungen" in html and "Handy aus" in html
    email_service.send_briefing([_dl(1, "Max", "M")], _ev(), "https://x")
    assert "Grundlegende Regelungen" not in mails[-1][2]   # ohne Regeln kein Abschnitt


def test_mail_regeln_mehrere_boxen_und_marke(mails):
    email_service.send_briefing([_dl(1, "Max", "M")], _ev(marke="Knallfrosch"), "https://x",
                                regeln="## Regeln A\nPunkt eins\n## Künstler\nAuf {MARKE} verweisen.")
    html = mails[-1][2]
    assert "Regeln A" in html and "Künstler" in html
    assert "Auf Knallfrosch Kinderevents verweisen." in html


def test_regeln_abschnitte_parser():
    from choices import regeln_abschnitte, BRIEFING_REGELN_DEFAULT
    ab = regeln_abschnitte("## Box 1\n1. eins\n- zwei\n## Box 2\ndrei {MARKE}", "Kindsalabim")
    assert [t for t, _ in ab] == ["Box 1", "Box 2"]
    assert ab[0][1] == ["eins", "zwei"]                 # Nummerierung/Spiegelstrich entfernt
    assert ab[1][1] == ["drei Kindsalabim"]
    # Der Vorlagen-Standard hat die drei bekannten Boxen
    std = regeln_abschnitte(BRIEFING_REGELN_DEFAULT, "Kindsalabim")
    assert [t for t, _ in std][:2] == ["Grundlegende Regelungen", "Instaff / Externe Agentur"]


# ── PDF ──────────────────────────────────────────────────────────────────────────

def _pdf_text(pdf_bytes):
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_pdf_regeln_zweite_seite():
    ohne = build_briefing_pdf(_ev(), [_dl(1, "Max", "M")])
    mit = build_briefing_pdf(_ev(), [_dl(1, "Max", "M")], regeln="Regel eins.\nRegel zwei.")
    assert len(pypdf.PdfReader(io.BytesIO(ohne)).pages) == 1
    r = pypdf.PdfReader(io.BytesIO(mit))
    assert len(r.pages) == 2
    assert "Regel zwei" in (r.pages[1].extract_text() or "")


def test_pdf_rechnung_und_sparte_und_tl_zuerst():
    team = [_dl(1, "Anna", "Erste", sparte="Kinderschminke"), _dl(2, "Bernd", "Leiter")]
    pdf = build_briefing_pdf(_ev(marke="Knallfrosch", teamleiter_id=2), team)
    txt = _pdf_text(pdf)
    assert "Rechnung senden an" in txt                 # eigener Bereich (Karte)
    assert "Malca & Akmanoglu GbR" in txt              # Rechnungsanschrift je Marke
    assert "personal@knallfrosch-kinderevents.de" in txt   # Rechnungs-Mail je Marke
    assert "(Kinderschminken)" in txt
    assert txt.index("Bernd Leiter") < txt.index("Anna Erste")   # Teamleitung zuerst


def test_dresscode_hinweis_in_pdf_und_mail(mails):
    pdf = build_briefing_pdf(_ev(), [_dl(1, "Max", "M")])
    assert "gepflegte Hose / Rock / Shorts" in _pdf_text(pdf)
    email_service.send_briefing([_dl(1, "Max", "M")], _ev(), "https://x")
    assert "gepflegte Hose / Rock / Shorts" in mails[-1][2]


def test_pdf_ankunft_in_datum_karte():
    pdf = build_briefing_pdf(_ev(), [_dl(1, "Max", "M")])
    txt = _pdf_text(pdf)
    # Ankunft/Treffpunkt stehen in der „Datum & Uhrzeit"-Box (linke Spalte, vor dem
    # rechten Spalten-Inhalt „Aufbauort")
    assert txt.index("Ankunft") < txt.index("Aufbauort")


def test_pdf_route_nutzt_vorlage_regeln_als_standard(admin):
    # Ohne gespeicherte Einstellung greifen die Vorlage-Regeln (Seite „Allgemeines")
    from database import SessionLocal
    from models import AppEinstellung
    s = SessionLocal()
    try:
        s.query(AppEinstellung).filter(AppEinstellung.key == "briefing_regeln").delete()
        s.commit()
    finally:
        s.close()
    eid = make_event()
    r = admin.get(f"/admin/events/{eid}/briefing/pdf")
    txt = _pdf_text(r.content)
    assert "Rauchverbot" in txt                       # Vorlage-Inhalt
    assert "Wir danken für euren Einsatz" in txt      # Abschluss-Zeile


# ── „Briefing bearbeiten" ohne Auf-/Abbau ────────────────────────────────────────

def test_briefing_edit_ohne_aufbau_und_ohne_datenverlust(admin):
    eid = make_event(kunde_email="k@x.de", cl_aufbau_von="08:00", cl_abbau_bis="20:00")
    h = admin.get(f"/admin/events/{eid}/checklist/edit").text
    assert "Aufbau- und Abbauzeitraum" not in h            # Karte ist weg
    admin.post(f"/admin/events/{eid}/checklist/edit",
               data={"ansprechpartner_name": "Neu", "verpflegung": "Ja"},
               follow_redirects=False)
    ev = reload(Event, eid)
    assert ev.cl_ansprechpartner_name == "Neu"
    assert ev.cl_aufbau_von == "08:00" and ev.cl_abbau_bis == "20:00"   # Kundenwerte bleiben


# ── Einstellungen: Regeln-Feld ───────────────────────────────────────────────────

def test_einstellungen_regeln_speichern(admin):
    h = admin.get("/admin/einstellungen").text
    assert "briefing_regeln" in h
    admin.post("/admin/einstellungen",
               data={"briefing_regeln": "Immer freundlich bleiben."}, follow_redirects=False)
    h2 = admin.get("/admin/einstellungen").text
    assert "Immer freundlich bleiben." in h2
    from database import SessionLocal
    from notifications import get_setting
    s = SessionLocal()
    try:
        assert get_setting(s, "briefing_regeln") == "Immer freundlich bleiben."
    finally:
        s.close()
