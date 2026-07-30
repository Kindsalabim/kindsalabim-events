"""Verfügbarkeitsanfragen: Stammkunden-Bonus (+15 Score & Hinweis, wenn ein
Dienstleister bei früheren Events desselben Kunden zugesagt hat) + Namens-Suchzeile."""
from datetime import date, timedelta
from types import SimpleNamespace

from distance import rank_contractors
from factories import make_event, make_dienstleister, make_anfrage

BALD = date.today() + timedelta(days=21)


def _dl(i):
    return SimpleNamespace(id=i, plz="", strasse="", stadt="", qualitaet=3,
                           logistiker=False, erfahrungspunkte=0)


def test_rank_bonus_hebt_bekannte_nach_oben():
    a, b = _dl(1), _dl(2)
    ranked = rank_contractors([a, b], "45127 Essen", False, None, {2: 3})
    assert ranked[0].id == 2
    assert ranked[0].rang_kunde_einsaetze == 3
    assert ranked[1].rang_kunde_einsaetze == 0
    assert ranked[0].rang_score == ranked[1].rang_score + 15


def test_hinweis_und_suchzeile_bei_gleichem_kunden(admin):
    did = make_dienstleister(vorname="Stamm", nachname="Kraft")
    alt = make_event(datum=date.today() - timedelta(days=100), kunde_firma="Stamm AG")
    make_anfrage(alt, did, status="Ja", rolle="Teamer")
    neu = make_event(datum=BALD, kunde_firma="Stamm AG")
    h = admin.get(f"/admin/events/{neu}").text
    assert "bei diesem Kunden im Einsatz" in h
    assert "dl-suche" in h            # Namens-Suchzeile vorhanden
    assert 'data-dlname="stamm kraft"' in h


def test_kein_hinweis_bei_anderem_kunden(admin):
    make_dienstleister(vorname="Neu", nachname="Ling")
    neu = make_event(datum=BALD, kunde_firma="Frisch GmbH")
    h = admin.get(f"/admin/events/{neu}").text
    assert "bei diesem Kunden im Einsatz" not in h
