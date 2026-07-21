"""Nachbesetzungs-Vorschlag für Künstler beachtet die Sparte.

Hintergrund (Aykut): Für ein Kinderschminken-Event (1 Künstler) wurde „Aykut" (Zauberer)
vorgeschlagen. Das System muss erkennen, dass eine Kinderschminkerin gebraucht wird.
"""
from datetime import date
from types import SimpleNamespace

import routes.admin as admin
from choices import benoetigte_sparten, kuenstler_passt
from factories import make_event, make_dienstleister
from models import Event
from database import SessionLocal


# ── Reine Logik (deterministisch) ────────────────────────────────────────────────

def test_benoetigte_sparten_mapping():
    assert benoetigte_sparten("Kinderschminken") == {"Kinderschminke", "Schminke + Ballon"}
    assert benoetigte_sparten("Ballonmodellage") == {"Ballonkünstler", "Schminke + Ballon"}
    assert benoetigte_sparten("Zaubershow") == {"Showact"}
    assert benoetigte_sparten("Walkact") == {"Walkact"}
    # Mehrere Aktionen → Vereinigung
    assert benoetigte_sparten("Kinderschminken, Zaubershow") == \
        {"Kinderschminke", "Schminke + Ballon", "Showact"}
    # Nicht-künstlerische Aktion / leer → keine Anforderung (kein Filter)
    assert benoetigte_sparten("Spieleland") == set()
    assert benoetigte_sparten("") == set()


def test_kuenstler_passt():
    benoetigt = {"Kinderschminke", "Schminke + Ballon"}
    assert kuenstler_passt(SimpleNamespace(kuenstler_sparte="Kinderschminke"), benoetigt) is True
    assert kuenstler_passt(SimpleNamespace(kuenstler_sparte="Schminke + Ballon"), benoetigt) is True
    # Der Aykut-Fall: Zauberer für Kinderschminken → nein
    assert kuenstler_passt(SimpleNamespace(kuenstler_sparte="Showact"), benoetigt) is False
    # Ohne Anforderung passt jeder
    assert kuenstler_passt(SimpleNamespace(kuenstler_sparte="Showact"), set()) is True


# ── Vorschlag (Invariante – robust gegen Alt-Daten in der geteilten Test-DB) ──────

def test_vorschlag_hat_immer_passende_sparte():
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1, anzahl_teamer=0,
                     datum=date(2027, 6, 1))
    # Ein passender + ein unpassender Künstler (der „Aykut"-Fall)
    make_dienstleister(rolle="Künstler", kuenstler_sparte="Kinderschminke", aktiv=True,
                       vorname="Klara", nachname="Schmink")
    make_dienstleister(rolle="Künstler", kuenstler_sparte="Showact", aktiv=True,
                       vorname="Aykut", nachname="Zauber")
    s = SessionLocal()
    try:
        ev = s.get(Event, eid)
        v = admin.vorschlag_ersatz(ev, s, "Künstler")
        assert v is not None                        # es gibt einen passenden
        assert (v.kuenstler_sparte or "") in {"Kinderschminke", "Schminke + Ballon"}
    finally:
        s.close()


def test_zauberer_wird_fuer_kinderschminken_nie_vorgeschlagen():
    # Event mit Kinderschminken; ein Showact-Künstler existiert – er darf NICHT kommen,
    # selbst wenn kein passender frei wäre (dann lieber kein Vorschlag).
    eid = make_event(produkte="Kinderschminken", anzahl_kuenstler=1, anzahl_teamer=0,
                     kunde_firma="Solo-Zauber-Test", veranstaltungsort="Nirgendwo 999, 99999 X",
                     datum=date(2027, 7, 1))
    zid = make_dienstleister(rolle="Künstler", kuenstler_sparte="Showact", aktiv=True,
                             vorname="NurZauber", nachname="Test999")
    s = SessionLocal()
    try:
        ev = s.get(Event, eid)
        v = admin.vorschlag_ersatz(ev, s, "Künstler")
        # Falls ein Vorschlag kommt (durch andere passende Alt-Daten), ist es NICHT der Zauberer
        assert v is None or v.id != zid
        if v is not None:
            assert (v.kuenstler_sparte or "") in {"Kinderschminke", "Schminke + Ballon"}
    finally:
        s.close()
