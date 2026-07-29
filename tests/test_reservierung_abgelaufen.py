"""Abgelaufene Reservierungen: eingeklapptes Dropdown in der Liste + Google-Kalender-
Umfärbung Anthrazit → Flamingo nach Fristablauf (Cron, idempotent über
kalender_abgelaufen_markiert). Kalender-Sync ist in allen Tests gemockt."""
from datetime import date, timedelta

import calendar_service
from models import Reservierung
from factories import reload
from database import SessionLocal
from routes.cron import _run_reservierung_farben, _run_reservierungen_aufraeumen
from test_reservierung import _make_res

GESTERN = date.today() - timedelta(days=1)
MORGEN = date.today() + timedelta(days=1)


# ── Liste: Clustering ────────────────────────────────────────────────────────────

def test_liste_clustert_abgelaufene_im_dropdown(admin):
    _make_res(kunde_firma="AbgelaufenGmbH", frist=GESTERN)
    _make_res(kunde_firma="AktivGmbH", frist=MORGEN)
    h = admin.get("/admin/reservierungen").text
    assert "Abgelaufene Reservierungen" in h
    aktiv_teil, abgelaufen_teil = h.split("Abgelaufene Reservierungen", 1)
    assert "AktivGmbH" in aktiv_teil
    assert "AbgelaufenGmbH" in abgelaufen_teil
    assert "AbgelaufenGmbH" not in aktiv_teil


# ── Kalender-Farbe ───────────────────────────────────────────────────────────────

def test_kalender_farbe_flamingo_nach_fristablauf():
    rid = _make_res(frist=GESTERN)
    body = calendar_service._reservierung_body(reload(Reservierung, rid))
    assert body["colorId"] == "4"


def test_kalender_farbe_anthrazit_vor_frist():
    rid = _make_res(frist=MORGEN)
    body = calendar_service._reservierung_body(reload(Reservierung, rid))
    assert body["colorId"] == "8"


# ── Cron-Umfärbung ───────────────────────────────────────────────────────────────

def _set_kalender_id(rid, wert="cal-test-123"):
    s = SessionLocal()
    try:
        s.get(Reservierung, rid).kalender_event_id = wert
        s.commit()
    finally:
        s.close()


def test_cron_umfaerbung_idempotent(monkeypatch):
    rid = _make_res(frist=GESTERN)
    _set_kalender_id(rid)
    aufrufe = []
    monkeypatch.setattr(calendar_service, "sync_reservierung_async",
                        lambda i: aufrufe.append(i) or True)
    s = SessionLocal()
    try:
        _run_reservierung_farben(s)
        assert rid in aufrufe
        assert reload(Reservierung, rid).kalender_abgelaufen_markiert is True
        # zweiter Lauf: bereits markiert → kein erneuter Kalender-Aufruf
        aufrufe.clear()
        _run_reservierung_farben(s)
        assert rid not in aufrufe
    finally:
        s.close()


def test_cron_ignoriert_reservierung_ohne_kalendereintrag(monkeypatch):
    rid = _make_res(frist=GESTERN)  # kein kalender_event_id
    aufrufe = []
    monkeypatch.setattr(calendar_service, "sync_reservierung_async",
                        lambda i: aufrufe.append(i) or True)
    s = SessionLocal()
    try:
        _run_reservierung_farben(s)
    finally:
        s.close()
    assert rid not in aufrufe


def test_cron_flag_nur_bei_erfolgreichem_sync(monkeypatch):
    rid = _make_res(frist=GESTERN)
    _set_kalender_id(rid)
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda i: False)
    s = SessionLocal()
    try:
        _run_reservierung_farben(s)
    finally:
        s.close()
    assert not reload(Reservierung, rid).kalender_abgelaufen_markiert


# ── Cron-Aufräumen: Termin verstrichen → Reservierung aus der App löschen ────────

def test_cron_loescht_reservierung_nach_termin(monkeypatch):
    geloescht = []
    monkeypatch.setattr(calendar_service, "delete_event_async",
                        lambda *a, **kw: geloescht.append(a))
    alt = _make_res(datum=GESTERN, frist=GESTERN - timedelta(days=5))
    _set_kalender_id(alt)
    heute_res = _make_res(datum=date.today(), frist=GESTERN)
    zukunft = _make_res(datum=date.today() + timedelta(days=30), frist=MORGEN)
    s = SessionLocal()
    try:
        _run_reservierungen_aufraeumen(s)
    finally:
        s.close()
    assert reload(Reservierung, alt) is None            # Termin vorbei → weg
    assert reload(Reservierung, heute_res) is not None  # heutiger Termin bleibt
    assert reload(Reservierung, zukunft) is not None
    assert geloescht == []                              # Kalender-Eintrag bleibt stehen
