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


# --- Realitäts-Abgleich mit den echten Lexoffice-ABs 2025 (Session 22.07.2026) ---
# Viele ABs kleben Einzel- und Gesamtbetrag zusammen („92,50647,50") oder nutzen
# Einheiten/Namen, die der Parser anfangs nicht kannte. Vorher fiel die Position
# dann durch und der Betrag der NÄCHSTEN Position (oft Fahrtkosten) wurde der
# Aktion zugeschrieben → falscher Budget-Vorschlag.

AB_GEKLEBT = (   # nach AB0422 Actemium: Beträge ohne Leerzeichen + Tagessatz
    "1 3 Knallfrosch - Mitarbeiter / Tagessatz (8Std.)Betreuung der Bastelaktion.\n"
    "3 Tagessatz292,50877,50\n"
    "2 Kinderschminkeninkl. 1 Kinderschminkerin, Schminktheke/Hocker und Ma-terial\n"
    "7 Stunde 92,50647,50\n"
    "3 Fahrtkostenpauschale25€ p.P 2 Stück 25,00 50,00\n"
)


def test_geklebte_betraege_und_tagessatz(monkeypatch):
    monkeypatch.setattr(ab_budget, "_text", lambda b: AB_GEKLEBT)
    gesamts = [g for _, g in ab_budget.positionen(b"x")]
    assert gesamts == [877.5, 647.5, 50.0]
    v = ab_budget.budget_vorschlaege(b"x", ["Kinderschminken"])
    # Vorher: Position unlesbar → Fahrtkosten (50 €) wurden Kinderschminken zugeordnet.
    assert v == [{"aktion": "Kinderschminken", "netto": 647.5, "budget": 520}]


def test_einheit_minuten(monkeypatch):   # Zaubershow wird in „45 min." abgerechnet
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: "1 ZaubershowInteraktive magische Weltreise mit Mr.Magic "
                                  "1 45 min. 450,00450,00\n")
    v = ab_budget.budget_vorschlaege(b"x", ["Zaubershow"])
    assert v == [{"aktion": "Zaubershow", "netto": 450.0, "budget": 360}]


def test_und_zeichen_statt_plus(monkeypatch):   # AB: „&" – App: „+"
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: "1 Zaubershow & BallonmodellageUnterhaltung mit Mr.Magic "
                                  "für die ganze Familie4 Stunde190,00760,00\n")
    v = ab_budget.budget_vorschlaege(b"x", ["Zaubershow + Ballonmodellage"])
    assert v == [{"aktion": "Zaubershow + Ballonmodellage", "netto": 760.0, "budget": 610}]


def test_bindestrich_schreibweise(monkeypatch):   # AB: „Knusper-Häuschen"
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: "1 Knusper-Häuschen Bastelstationinkl. Material "
                                  "(Hanutas, Butterkekse, Smarties etc.)\n1 Stück 490,00 490,00\n")
    v = ab_budget.budget_vorschlaege(b"x", ["Knusperhäuschen"])
    assert v == [{"aktion": "Knusperhäuschen", "netto": 490.0, "budget": 390}]


def test_alias_prickelaktion(monkeypatch):   # AB: „Prickelaktion" – App: „Prickeln"
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: '1 Prickelaktion "Porsche"\n1 Stück 195,00 195,00\n')
    v = ab_budget.budget_vorschlaege(b"x", ["Prickeln"])
    assert v == [{"aktion": "Prickeln", "netto": 195.0, "budget": 160}]


def test_alias_spieleland_u3(monkeypatch):   # AB: „Spieleland U3" – App: „U3 Spieleland"
    monkeypatch.setattr(ab_budget, "_text",
                        lambda b: "7 Spieleland U3Bällebad, Kriechtunnel, Spiele, Bücher\n"
                                  "1 Tagessatz162,50 162,50\n")
    v = ab_budget.budget_vorschlaege(b"x", ["U3 Spieleland"])
    assert v == [{"aktion": "U3 Spieleland", "netto": 162.5, "budget": 130}]
