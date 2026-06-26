"""Einmal-Teamer (extern) zählt bei der Team-Vollständigkeit mit."""
from models import Event, ExternerTeamer
from factories import make_event, make_dienstleister, make_anfrage
from routes.admin import auto_status
from database import SessionLocal


def test_externer_teamer_zaehlt_zur_teamer_zahl():
    eid = make_event(anzahl_teamer=2, material_bestellt=True, checkliste_uebersprungen=True)
    did = make_dienstleister()
    make_anfrage(eid, did, status="Ja", rolle="Teamer")

    # nur 1 zugesagter Teamer von 2 -> noch nicht "Planung fertig"
    s = SessionLocal(); ev = s.get(Event, eid)
    assert auto_status(ev, s) != "Planung fertig"
    s.close()

    # 1 Einmal-Teamer (extern) dazu -> 1 + 1 = 2 -> jetzt fertig
    s = SessionLocal()
    s.add(ExternerTeamer(event_id=eid, name="Tom Extern", telefon="0177"))
    s.commit(); s.close()

    s = SessionLocal(); ev = s.get(Event, eid)
    assert auto_status(ev, s) == "Planung fertig"
    s.close()
