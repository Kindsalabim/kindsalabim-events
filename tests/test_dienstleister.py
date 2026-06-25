"""Dienstleister: Team-Shirt-Häkchen (Kindsalabim / Knallfrosch) anlegen/bearbeiten/abwählen."""
import re

from models import Dienstleister
from factories import reload
from database import SessionLocal


def test_create_teamshirt_nur_kindsalabim(admin):
    r = admin.post("/admin/dienstleister/new", data={
        "vorname": "Max", "nachname": "Muster", "email": "shirt1@example.com",
        "rolle": "Teamer", "teamshirt_kindsalabim": "true"}, follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    d = s.query(Dienstleister).filter_by(email="shirt1@example.com").first()
    assert d.teamshirt_kindsalabim is True and d.teamshirt_knallfrosch is False
    s.close()


def test_edit_teamshirt_form_vorauswahl_und_abwaehlen(admin):
    s = SessionLocal()
    d = Dienstleister(vorname="A", nachname="B", email="shirt2@example.com", rolle="Teamer",
                      teamshirt_kindsalabim=True, teamshirt_knallfrosch=False)
    s.add(d); s.commit(); did = d.id
    s.close()
    h = admin.get(f"/admin/dienstleister/{did}/edit").text
    ks = re.search(r'name="teamshirt_kindsalabim"[^>]*>', h).group(0)
    kf = re.search(r'name="teamshirt_knallfrosch"[^>]*>', h).group(0)
    assert "checked" in ks and "checked" not in kf
    # Abwählen (kein Häkchen gesendet) -> beide False
    admin.post(f"/admin/dienstleister/{did}/edit", data={
        "vorname": "A", "nachname": "B", "email": "shirt2@example.com", "rolle": "Teamer"},
        follow_redirects=False)
    d2 = reload(Dienstleister, did)
    assert d2.teamshirt_kindsalabim is False and d2.teamshirt_knallfrosch is False
