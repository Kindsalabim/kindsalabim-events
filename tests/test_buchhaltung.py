"""Buchhaltung: Bearbeiten-Bug (#5), Monatsgruppen + Sortierung nach Rechnungsnummer,
Offen-Zähler pro Monat."""
from database import SessionLocal
from models import Rechnung


def _neu(admin, datum, kunde, rgnr, brutto="1000", bezahlt=False):
    admin.post("/admin/buchhaltung/neu",
               data={"datum": datum, "kunde": kunde, "rgnr": rgnr, "brutto": brutto},
               follow_redirects=False)
    s = SessionLocal()
    try:
        r = s.query(Rechnung).filter(Rechnung.rgnr == rgnr).first()
        rid = r.id
        if bezahlt:
            r.bezahlt = True
            s.commit()
        return rid
    finally:
        s.close()


def test_edit_formular_kein_500(admin):
    # Bug #5: das Bearbeiten-Formular warf durch eine Jinja-Präzedenzfalle
    # ('%.2f' % x | replace) einen Internal Server Error.
    rid = _neu(admin, "2095-07-03", "Kunde A", "RE-2095-050", brutto="1450")
    r = admin.get(f"/admin/buchhaltung/{rid}/edit")
    assert r.status_code == 200
    assert "1450,00" in r.text          # Brutto im deutschen Format vorbelegt


def test_edit_speichern_rundtrip(admin):
    rid = _neu(admin, "2095-07-04", "Alt", "RE-2095-051", brutto="500")
    admin.post(f"/admin/buchhaltung/{rid}/edit",
               data={"datum": "2095-07-04", "kunde": "Neu GmbH", "rgnr": "RE-2095-051",
                     "brutto": "1234,56", "personalkosten": "100", "materialkosten": "0",
                     "notiz": ""}, follow_redirects=False)
    s = SessionLocal()
    try:
        r = s.get(Rechnung, rid)
        assert r.kunde == "Neu GmbH"
        assert abs((r.brutto or 0) - 1234.56) < 0.01     # Komma-Eingabe korrekt geparst
    finally:
        s.close()


def test_monate_neueste_zuerst_und_nach_rgnr(admin):
    _neu(admin, "2096-05-10", "Mai-Kunde", "RE-2096-010")
    _neu(admin, "2096-07-01", "Juli-A", "RE-2096-030")
    _neu(admin, "2096-07-20", "Juli-B", "RE-2096-031")
    html = admin.get("/admin/buchhaltung?jahr=2096").text
    assert html.index("Juli 2096") < html.index("Mai 2096")        # neuester Monat oben
    assert html.index("RE-2096-031") < html.index("RE-2096-030")   # höhere Rgnr zuerst


def test_offen_zaehler_pro_monat(admin):
    _neu(admin, "2097-07-01", "Offen1", "RE-2097-040")
    _neu(admin, "2097-07-02", "Offen2", "RE-2097-041")
    _neu(admin, "2097-07-03", "Bezahlt", "RE-2097-042", bezahlt=True)
    html = admin.get("/admin/buchhaltung?jahr=2097").text
    assert "2 offen" in html            # 2 von 3 offen im Juli 2097


def test_volle_breite_aktiv(admin):
    # #4: Buchhaltung nutzt die volle Seitenbreite (kein max-w-5xl-Deckel)
    html = admin.get("/admin/buchhaltung?jahr=2098").text
    assert "max-w-none" in html


# ── Inline-Editieren (Excel-artig) + gekürzte Kunden-Spalte ──────────────────────

def test_parse_float_deutsches_format():
    from routes.buchhaltung import parse_float
    assert parse_float("1.234,56") == 1234.56    # Tausenderpunkt (machte vorher 0,00 daraus!)
    assert parse_float("1234,56") == 1234.56
    assert parse_float("1450") == 1450.0
    assert parse_float("1.450") == 1.45          # nur Punkt = Dezimalpunkt (engl. Eingabe)
    assert parse_float(" 99,90 € ") == 99.9
    assert parse_float("") == 0.0


def test_inline_feld_aendern(admin):
    rid = _neu(admin, "2099-07-01", "Inline-Kunde", "RE-2099-001", brutto="500")
    admin.post(f"/admin/buchhaltung/{rid}/feld",
               data={"feld": "brutto", "wert": "1.234,56"}, follow_redirects=False)
    s = SessionLocal()
    try:
        assert abs(s.get(Rechnung, rid).brutto - 1234.56) < 0.01
    finally:
        s.close()


def test_inline_nur_whitelist_felder(admin):
    rid = _neu(admin, "2099-07-02", "Whitelist-Kunde", "RE-2099-002", brutto="500")
    # berechnete/fremde Felder dürfen nicht über den Inline-Weg änderbar sein
    admin.post(f"/admin/buchhaltung/{rid}/feld",
               data={"feld": "kunde", "wert": "Gehackt"}, follow_redirects=False)
    admin.post(f"/admin/buchhaltung/{rid}/feld",
               data={"feld": "bezahlt", "wert": "1"}, follow_redirects=False)
    s = SessionLocal()
    try:
        r = s.get(Rechnung, rid)
        assert r.kunde == "Whitelist-Kunde" and r.bezahlt is False
    finally:
        s.close()


def test_kunde_spalte_gekuerzt_mit_tooltip(admin):
    lang = "Förderverein Evangelische Kindertagesstätte Pusteblume Heckstrasse Essen-Werden e.V"
    _neu(admin, "2099-08-01", lang, "RE-2099-003")
    html = admin.get("/admin/buchhaltung?jahr=2099").text
    assert f'title="{lang}"' in html          # voller Name als Maus-Tooltip
    assert "text-overflow: ellipsis" in html  # Spalte wird gekürzt statt zu wachsen
