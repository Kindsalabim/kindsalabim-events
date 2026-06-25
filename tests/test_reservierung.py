"""Reservierungen: Uhrzeit + Art, zeitgebundener Kalendereintrag, Wunschformat, Liste."""
from datetime import date

import calendar_service
from models import Reservierung
from factories import reload
from database import SessionLocal


def _make_res(**over):
    s = SessionLocal()
    try:
        r = Reservierung(datum=over.get("datum", date(2026, 7, 20)),
                         kunde_firma=over.get("kunde_firma", "Familie Otto"),
                         kunde_kontakt=over.get("kunde_kontakt", "Fr. Otto"),
                         anlass=over.get("anlass", "Kindergeburtstag"),
                         veranstaltungsort=over.get("veranstaltungsort", "50667 Köln"),
                         startzeit=over.get("startzeit"), endzeit=over.get("endzeit"),
                         art=over.get("art", "Div."), frist=over.get("frist", date(2026, 7, 10)),
                         marke="Kindsalabim")
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def test_create_reservierung_mit_uhrzeit(admin):
    r = admin.post("/admin/reservierungen/new", data={
        "datum": "2026-07-20", "kunde_firma": "Familie Otto", "kunde_kontakt": "Fr. Otto",
        "startzeit": "17:45", "endzeit": "18:45", "art": "Z",
        "anlass": "Kindergeburtstag", "veranstaltungsort": "50667 Köln",
        "frist": "2026-07-10", "marke": "Kindsalabim"}, follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    res = s.query(Reservierung).filter_by(kunde_firma="Familie Otto").order_by(Reservierung.id.desc()).first()
    assert res.startzeit == "17:45" and res.endzeit == "18:45" and res.art == "Z"
    s.close()


def test_reservierung_body_zeitgebunden_und_format():
    rid = _make_res(startzeit="17:45", endzeit="18:45", art="Z")
    res = reload(Reservierung, rid)
    body = calendar_service._reservierung_body(res)
    assert body["start"] == {"dateTime": "2026-07-20T17:45:00", "timeZone": "Europe/Berlin"}
    assert body["end"] == {"dateTime": "2026-07-20T18:45:00", "timeZone": "Europe/Berlin"}
    assert body["summary"] == "(Z) Köln, Kindergeburtstag, Fr. Otto, reserv. bis 10.07.2026"
    assert body["colorId"] == "8"


def test_reservierung_body_ohne_endzeit_plus_stunde():
    rid = _make_res(startzeit="17:45", endzeit=None)
    body = calendar_service._reservierung_body(reload(Reservierung, rid))
    assert body["end"]["dateTime"] == "2026-07-20T18:45:00"


def test_reservierung_body_ohne_zeit_ganztags():
    rid = _make_res(startzeit=None, endzeit=None)
    body = calendar_service._reservierung_body(reload(Reservierung, rid))
    assert "date" in body["start"] and "dateTime" not in body["start"]


def test_reservierung_liste_zeigt_uhrzeit(admin):
    _make_res(startzeit="17:45", endzeit="18:45")
    h = admin.get("/admin/reservierungen").text
    assert "17:45–18:45 Uhr" in h
