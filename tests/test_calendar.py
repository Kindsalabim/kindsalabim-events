"""Kalender-Helfer (Unit): Titelformat, Stadt-Extraktion, +1h."""
from types import SimpleNamespace
from datetime import date

import calendar_service


def test_stadt_aus_plz():
    assert calendar_service._stadt("Musterstr. 1, 45127 Essen") == "Essen"
    assert calendar_service._stadt("50667 Köln") == "Köln"


def test_event_title_format():
    ev = SimpleNamespace(veranstaltungsort="Markt 1, 45127 Essen", kunde_kontakt="Fr. Becker",
                         kunde_firma="Kita", anlass="Sommerfest", status="Gebucht")
    assert calendar_service._title(ev) == "(div.) Essen, Sommerfest, Fr. Becker"


def test_event_title_abgesagt_praefix():
    ev = SimpleNamespace(veranstaltungsort="45127 Essen", kunde_kontakt="X", kunde_firma="Y",
                         anlass="Fest", status="Abgesagt")
    assert calendar_service._title(ev).startswith("ABGESAGT –")


def test_plus_eine_stunde():
    assert calendar_service._plus_eine_stunde("17:45") == "18:45"
    assert calendar_service._plus_eine_stunde("23:30") == "24:00"
    assert calendar_service._plus_eine_stunde("") == "24:00"
