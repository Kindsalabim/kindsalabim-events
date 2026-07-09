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
