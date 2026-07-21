"""AB-Parser: Netto-Position der gebuchten Aktion × 80 % = Künstler-Budget.
Getestet über den echten (aus der Lexoffice-AB extrahierten) Textinhalt."""
import ab_budget

# So liefert pypdf die Textebene der echten AB (Seiten zusammengefügt).
AB_TEXT = (
    "Pos.Bezeichnung Menge &EinheitEinzel €Gesamt €\n"
    "Samstag, 12.09.2025 von 12-16 Uhr\n"
    "1 Kinderschminkeninkl. 1 Kinderschminkerin, Schminktheke/Hocker und "
    "Material(Profifarben auf Wasserbasis nach EU-Norm 2009/48/EG)\n"
    "4 Stunde92,50 370,00\n"
    "Sonntag, 13.09.2025 von 12-16 Uhr\n"
    "2 Kinderschminkeninkl. 1 Kinderschminkerin, Schminktheke/Hocker und "
    "Material(Profifarben auf Wasserbasis nach EU-Norm 2009/48/EG)\n"
    "4 Stunde92,50 370,00\n"
    "3 AgenturvergütungKonzeption, Projektplanung, Vermittlung, Betreuung und "
    "Begleitung vor Ort\n"
    "0,5Stunde70,00 35,00\n"
    "Zwischensumme 775,00\n"
    "Übertrag 775,00\n"
    "4 Fahrtkostenpauschale(25€ p.P.) 2 Stück 25,00 50,00\n"
    "Zwischensumme (netto) 825,00\n"
    "Umsatzsteuer 19 % 156,75\n"
    "Gesamtbetrag 981,75\n"
)


def _patch(monkeypatch):
    monkeypatch.setattr(ab_budget, "_text", lambda b: AB_TEXT)


def test_positionen_erkennt_alle_vier(monkeypatch):
    _patch(monkeypatch)
    gesamts = [g for _, g in ab_budget.positionen(b"x")]
    assert gesamts == [370.0, 370.0, 35.0, 50.0]   # nicht Zwischensumme/USt/Gesamt


def test_budget_kinderschminken_80_prozent_auf_10_gerundet(monkeypatch):
    _patch(monkeypatch)
    v = ab_budget.budget_vorschlaege(b"x", ["Kinderschminken"])
    # 370 × 80 % = 296 → auf 300 gerundet; netto bleibt der Originalbetrag
    assert v == [{"aktion": "Kinderschminken", "netto": 370.0, "budget": 300}]


def test_auf_10_runden():
    assert ab_budget.auf_10(296) == 300
    assert ab_budget.auf_10(294) == 290
    assert ab_budget.auf_10(295) == 300   # kaufmännisch aufrunden
    assert ab_budget.auf_10(290) == 290
    assert ab_budget.auf_10(1000) == 1000


def test_ignoriert_agentur_und_fahrtkosten(monkeypatch):
    _patch(monkeypatch)
    v = ab_budget.budget_vorschlaege(b"x", ["Kinderschminken", "Ballonmodellage"])
    assert len(v) == 1 and v[0]["aktion"] == "Kinderschminken"   # nur die Aktion, keine Marge


def test_keine_passende_position(monkeypatch):
    _patch(monkeypatch)
    assert ab_budget.budget_vorschlaege(b"x", ["Zaubershow"]) == []


def test_parsefehler_gibt_leere_liste(monkeypatch):
    def boom(_):
        raise ValueError("kaputt")
    monkeypatch.setattr(ab_budget, "_text", boom)
    assert ab_budget.budget_vorschlaege(b"x", ["Kinderschminken"]) == []


def test_tausenderpunkt_im_betrag(monkeypatch):
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: "1 Zaubershow\n1 Pauschale1.250,00 1.250,00\n")
    v = ab_budget.budget_vorschlaege(b"x", ["Zaubershow"])
    assert v == [{"aktion": "Zaubershow", "netto": 1250.0, "budget": 1000.0}]
