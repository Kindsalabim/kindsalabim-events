"""Aktion „Spezielle Bastelaktionen (Bakerross)" heißt jetzt nur noch „Bastelaktion":
Der Lieferant steht sonst im Briefing – Dienstleister müssen nicht wissen, wo wir bestellen.
"""
import ankunft
from routes.admin import PRODUKTE_LIST


def test_auswahlliste_ohne_lieferantennamen():
    assert "Bastelaktion" in PRODUKTE_LIST
    assert not any("Bakerross" in p for p in PRODUKTE_LIST)


def test_event_formular_zeigt_neuen_namen(admin):
    h = admin.get("/admin/events/new").text
    assert "Bakerross" not in h


def test_vorlauf_gilt_weiter_45_minuten():
    # Der Name steckt auch in der Vorlauf-Tabelle – sonst rutscht die Aktion still
    # auf „kein Vorlauf" und die Ankunftszeit im Briefing wäre falsch.
    assert ankunft.auto_vorlauf("Bastelaktion") == 45
    assert ankunft.auto_vorlauf("Bastelaktion, Glitzertattoos") == 45
    assert not any("Bakerross" in k for k in ankunft.VORLAUF)
