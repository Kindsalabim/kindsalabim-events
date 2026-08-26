"""Bastel-Recherche: Andocken an Reservierungen, Übernahme beim Umwandeln,
gemerkte Recherche über Seitenwechsel hinweg."""
from datetime import date, timedelta

from database import SessionLocal
from models import Bastelvorschlag, BastelProdukt, Event, Reservierung
from factories import reload


def _reservierung(firma="Marler Stern GmbH"):
    s = SessionLocal()
    try:
        r = Reservierung(datum=date.today() + timedelta(days=40), kunde_firma=firma,
                         marke="Knallfrosch", anlass="Herbstfest",
                         frist=date.today() + timedelta(days=5))
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def _produkt(name="Herbst-Laternen-Set"):
    s = SessionLocal()
    try:
        p = BastelProdukt(name=name, url=f"https://www.bakerross.de/{name}",
                          bild_url=f"https://www.bakerross.de/{name}.jpg",
                          aktiv=True, preis=9.99, stueckzahl=6,
                          aktualisiert_am=date.today().isoformat())
        s.add(p); s.commit()
        return p.id
    finally:
        s.close()


# ── Andocken an eine Reservierung ─────────────────────────────────────────────

def test_bastelset_an_reservierung_andocken(admin):
    rid = _reservierung()
    r = admin.post("/admin/bakerross/an-event", data={
        "event_id": f"r{rid}", "name": "Laternen-Bastelset",
        "url": "https://www.bakerross.de/x", "bild_url": "https://www.bakerross.de/x.jpg",
        "br_preis": "9.99", "stueckzahl": "6", "faktor": "2.5"}, follow_redirects=False)
    assert r.status_code == 303 and f"reservierung_id={rid}" in r.headers["location"]
    s = SessionLocal()
    try:
        v = s.query(Bastelvorschlag).filter_by(reservierung_id=rid).first()
        assert v and v.event_id is None and v.name == "Laternen-Bastelset"
        assert v.kundenpreis and v.kundenpreis > 0
    finally:
        s.close()


def test_bastelset_an_event_weiterhin_moeglich(admin):
    from factories import make_event
    eid = make_event()
    r = admin.post("/admin/bakerross/an-event", data={
        "event_id": f"e{eid}", "name": "Event-Set", "br_preis": "5", "faktor": "2"},
        follow_redirects=False)
    assert f"event_id={eid}" in r.headers["location"]
    s = SessionLocal()
    try:
        v = s.query(Bastelvorschlag).filter_by(event_id=eid).first()
        assert v and v.reservierung_id is None
    finally:
        s.close()


def test_reservierungsliste_zeigt_sets_und_links(admin):
    rid = _reservierung("Sets Sichtbar GmbH")
    admin.post("/admin/bakerross/an-event", data={
        "event_id": f"r{rid}", "name": "Sichtbares Set", "br_preis": "4"},
        follow_redirects=False)
    h = admin.get("/admin/reservierungen").text
    assert "1 Bastelset recherchiert" in h
    assert f"/admin/angebot?reservierung_id={rid}" in h


# ── Umwandeln: Sets wandern mit ───────────────────────────────────────────────

def test_umwandeln_uebernimmt_bastelsets(admin):
    rid = _reservierung("Umwandel GmbH")
    admin.post("/admin/bakerross/an-event", data={
        "event_id": f"r{rid}", "name": "Mitwander-Set", "br_preis": "7"},
        follow_redirects=False)
    r = admin.post(f"/admin/reservierungen/{rid}/umwandeln", follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    try:
        ev = s.query(Event).filter_by(kunde_firma="Umwandel GmbH").first()
        v = s.query(Bastelvorschlag).filter_by(name="Mitwander-Set").first()
        assert ev and v and v.event_id == ev.id and v.reservierung_id is None
    finally:
        s.close()


def test_angebot_vorbefuellt_aus_reservierung(admin):
    rid = _reservierung("Angebot GmbH")
    admin.post("/admin/bakerross/an-event", data={
        "event_id": f"r{rid}", "name": "Angebots-Set", "br_preis": "6",
        "bild_url": "https://www.bakerross.de/angebot.jpg"}, follow_redirects=False)
    h = admin.get(f"/admin/angebot?reservierung_id={rid}").text
    assert "Angebots-Set" in h and "angebot.jpg" in h
    assert "Angebot GmbH" in h          # Kundenname vorbefüllt


# ── Gemerkte Recherche ────────────────────────────────────────────────────────

def test_recherche_bleibt_nach_seitenwechsel(admin, monkeypatch):
    import bakerross_service as br
    pid = _produkt("Gemerktes Set")
    s = SessionLocal()
    try:
        p = s.get(BastelProdukt, pid)
        monkeypatch.setattr(br, "kurate", lambda db, q, max_results=12, faktor=2.5: [
            {"produkt": db.get(BastelProdukt, pid), "br_preis": 9.99, "stueckzahl": 6,
             "kundenpreis": 4.16, "grund": "passt zum Herbst"}])
        assert p is not None
    finally:
        s.close()

    h = admin.post("/admin/bakerross/suche", data={"query": "Herbst", "faktor": "2.5"}).text
    assert "Gemerktes Set" in h

    # Ausflug ins Dashboard – danach ist die Recherche immer noch da
    admin.get("/admin/dashboard")
    h2 = admin.get("/admin/bakerross").text
    assert "Gemerktes Set" in h2 and "letzte Recherche" in h2 and "Herbst" in h2

    # ... bis sie bewusst verworfen wird
    admin.post("/admin/bakerross/verwerfen", follow_redirects=False)
    assert "Gemerktes Set" not in admin.get("/admin/bakerross").text
