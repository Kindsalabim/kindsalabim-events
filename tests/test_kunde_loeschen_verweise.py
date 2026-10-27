"""Kunde löschen, auf den noch Zeilen zeigen (Aykut 27.10.2026: „TEST Schnittstelle“ in der
Akquise ließ sich nicht löschen, Internal Server Error). Postgres prüft Fremdschlüssel,
SQLite in den Tests normalerweise nicht; hier wird die Prüfung deshalb eingeschaltet.

Das Kontaktprotokoll bleibt erhalten (Nachweis im Streitfall), nur der Verweis wird
gelöst; beim Wiederherstellen aus dem Papierkorb hängt es wieder am Kunden."""
import pytest
from sqlalchemy import event

import vertrieb
from database import engine
from models import GeloeschtesObjekt, Kunde, VertriebKontaktLog


@pytest.fixture
def fk_an():
    """Fremdschlüssel wie in Postgres erzwingen (nur für neue Verbindungen, daher dispose)."""
    def _an(dbapi_con, _):
        dbapi_con.execute("PRAGMA foreign_keys=ON")
    engine.dispose()
    event.listen(engine, "connect", _an)
    yield
    event.remove(engine, "connect", _an)
    engine.dispose()


def _akquise_mit_protokoll(db, firma):
    k = Kunde(firma=firma, email="test@verweis.example", herkunft="akquise",
              pipeline_status="kontakt")
    db.add(k)
    db.commit()
    vertrieb.protokollieren(db, k, "mail", "Erstkontakt", "test@verweis.example")
    db.commit()
    return k.id


def test_akquise_kontakt_mit_protokoll_loeschen(admin, db, fk_an):
    kid = _akquise_mit_protokoll(db, "Verweis Akquise GmbH")
    r = admin.post(f"/admin/crm/akquise/{kid}/loeschen", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Kunde, kid) is None
    log = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.empfaenger == "test@verweis.example",
                                             VertriebKontaktLog.betreff == "Erstkontakt").all()
    assert log and all(e.kunde_id is None for e in log)          # Nachweis bleibt


def test_bestandskunde_mit_protokoll_loeschen(admin, db, fk_an):
    kid = _akquise_mit_protokoll(db, "Verweis Bestand GmbH")
    k = db.get(Kunde, kid)
    k.herkunft = None
    db.commit()
    r = admin.post(f"/admin/crm/{kid}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Kunde, kid) is None


def test_wiederherstellen_haengt_protokoll_wieder_an(admin, db):
    from papierkorb import restore
    kid = _akquise_mit_protokoll(db, "Verweis Zurueck GmbH")
    log_id = db.query(VertriebKontaktLog).filter(VertriebKontaktLog.kunde_id == kid).one().id
    admin.post(f"/admin/crm/akquise/{kid}/loeschen", follow_redirects=False)
    eintrag = (db.query(GeloeschtesObjekt).filter(GeloeschtesObjekt.typ == "kunde",
                                                   GeloeschtesObjekt.objekt_id == kid)
               .order_by(GeloeschtesObjekt.id.desc()).first())
    restore(db, eintrag)
    db.commit()
    neu = db.query(Kunde).filter(Kunde.firma == "Verweis Zurueck GmbH").one()
    assert db.get(VertriebKontaktLog, log_id).kunde_id == neu.id
