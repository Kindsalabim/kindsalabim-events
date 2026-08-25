"""Platzvergabe-Regeln: volles Team, verspätete Zusage, Warteliste + Nachrücken."""
from datetime import date, timedelta

from database import SessionLocal
from models import Verfuegbarkeitsanfrage, Event, ExternerTeamer, Benachrichtigung
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login

HEUTE = date.today()
GESTERN = HEUTE - timedelta(days=1)
MORGEN = HEUTE + timedelta(days=1)


def _dl():
    """Dienstleister mit vollständigen Unterlagen (sonst greift die Zusage-Sperre)."""
    return make_dienstleister(gewerbeschein_vorliegt=True, dsgvo_unterzeichnet=True)


def _event(teamer=1, kuenstler=0):
    return make_event(datum=HEUTE + timedelta(days=30), anzahl_teamer=teamer,
                      anzahl_kuenstler=kuenstler)


def _antwort(client, did, aid, wert="Ja"):
    portal_login(client, did)
    return client.post(f"/portal/antwort/{aid}", data={"antwort": wert},
                       follow_redirects=False)


# ── Rechenkern ────────────────────────────────────────────────────────────────

def test_plaetze_frei_zaehlt_zusagen_und_externe(db):
    from besetzung import plaetze_frei
    eid = _event(teamer=3)
    ev = reload(Event, eid)
    make_anfrage(eid, _dl(), status="Ja", rolle="Teamer")
    assert plaetze_frei(db, ev, "Teamer") == 2
    s = SessionLocal()
    try:
        s.add(ExternerTeamer(event_id=eid, name="Aushilfe"))
        s.commit()
    finally:
        s.close()
    assert plaetze_frei(db, ev, "Teamer") == 1
    # Kein Bedarf hinterlegt → None = kein Limit (wer angefragt wurde, darf zusagen)
    assert plaetze_frei(db, ev, "Künstler") is None


def test_warteliste_nur_bei_echter_konkurrenz(db):
    """Mehr freie Plätze als laufende Anfragen → verspätete Zusage nimmt niemandem
    etwas weg und geht durch (Aykuts 8-Teamer-Fall)."""
    from besetzung import zusage_pruefen, plaetze_frei
    eid = _event(teamer=8)
    ev = reload(Event, eid)
    for _ in range(4):                                   # 4 haben zugesagt
        make_anfrage(eid, _dl(), status="Ja", rolle="Teamer")
    s = SessionLocal()
    try:                                                 # 2 kommen über die Agentur
        s.add(ExternerTeamer(event_id=eid, name="Agentur 1"))
        s.add(ExternerTeamer(event_id=eid, name="Agentur 2"))
        s.commit()
    finally:
        s.close()
    assert plaetze_frei(db, ev, "Teamer") == 2           # 8 − 4 − 2
    make_anfrage(eid, _dl(), status="Ausstehend", frist_datum=MORGEN)   # 1 läuft noch
    spaet = make_anfrage(eid, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    # 2 Plätze frei, nur 1 laufende Anfrage → verspätete Zusage ist unproblematisch
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, spaet)) == "glueck"

    # Kippt, sobald die laufenden Anfragen alle freien Plätze abdecken
    make_anfrage(eid, _dl(), status="Ausstehend", frist_datum=MORGEN)   # jetzt 2 offen
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, spaet)) == "warteliste"


def test_ohne_bedarf_bleibt_zusage_moeglich(db, client):
    """Reines Zaubershow-Event o. Ä.: anzahl_teamer = 0, trotzdem jemand angefragt."""
    from besetzung import zusage_pruefen
    eid = make_event(datum=HEUTE + timedelta(days=20))      # anzahl_teamer/kuenstler = 0
    did = _dl()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=MORGEN)
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, aid)) == "ok"
    _antwort(client, did, aid)
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"


def test_urteil_deckt_alle_faelle_ab(db):
    from besetzung import zusage_pruefen
    # 1) fristgerecht + Platz frei → ok
    eid = _event(teamer=1)
    aid = make_anfrage(eid, _dl(), status="Ausstehend", frist_datum=MORGEN)
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, aid)) == "ok"
    # 2) fristgerecht, aber Team voll → voll
    make_anfrage(eid, _dl(), status="Ja")
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, aid)) == "voll"
    # 3) verspätet + Team voll → zu_spaet
    eid2 = _event(teamer=1)
    spaet = make_anfrage(eid2, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    make_anfrage(eid2, _dl(), status="Ja")
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, spaet)) == "zu_spaet"
    # 4) verspätet, Platz frei, aber jemand anderes noch fristgerecht dran → warteliste
    eid3 = _event(teamer=1)
    spaet3 = make_anfrage(eid3, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    make_anfrage(eid3, _dl(), status="Ausstehend", frist_datum=MORGEN)
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, spaet3)) == "warteliste"
    # 5) verspätet, Platz frei, keine Konkurrenz → glueck
    eid4 = _event(teamer=1)
    spaet4 = make_anfrage(eid4, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    assert zusage_pruefen(db, db.get(Verfuegbarkeitsanfrage, spaet4)) == "glueck"


# ── Portal-Verhalten ──────────────────────────────────────────────────────────

def test_zusage_bei_vollem_team_wird_abgelehnt(client):
    eid = _event(teamer=1)
    make_anfrage(eid, _dl(), status="Ja")
    did = _dl()
    aid = make_anfrage(eid, did, status="Ausstehend", frist_datum=MORGEN)
    r = _antwort(client, did, aid)
    assert "besetzt=voll" in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ausstehend"   # nicht angenommen
    assert "bereits vollständig besetzt" in client.get("/portal?besetzt=voll").text


def test_verspaetete_zusage_bei_vollem_team(client):
    eid = _event(teamer=1)
    make_anfrage(eid, _dl(), status="Ja")
    did = _dl()
    aid = make_anfrage(eid, did, status="Abgelaufen", frist_datum=GESTERN)
    r = _antwort(client, did, aid)
    assert "besetzt=zu_spaet" in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Abgelaufen"
    assert "Leider zu spät" in client.get("/portal?besetzt=zu_spaet").text


def test_verspaetete_zusage_mit_glueck(client):
    did = _dl()
    aid = make_anfrage(_event(teamer=1), did, status="Abgelaufen", frist_datum=GESTERN)
    r = _antwort(client, did, aid)
    assert "glueck=1" in r.headers["location"]
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"
    assert "Du hast Glück" in client.get("/portal?glueck=1").text


def test_verspaetete_zusage_kommt_auf_warteliste(client):
    eid = _event(teamer=1)
    make_anfrage(eid, _dl(), status="Ausstehend", frist_datum=MORGEN)  # pünktlicher Kandidat
    did = _dl()
    aid = make_anfrage(eid, did, status="Abgelaufen", frist_datum=GESTERN)
    r = _antwort(client, did, aid)
    assert "warteliste=1" in r.headers["location"]
    a = reload(Verfuegbarkeitsanfrage, aid)
    assert a.status == "Abgelaufen" and a.warteliste_seit
    h = client.get("/portal?warteliste=1").text
    assert "Warteliste" in h and "automatisch erneut" in h


# ── Nachrücken ────────────────────────────────────────────────────────────────

def test_absage_laesst_wartenden_nachruecken(client, mails):
    eid = _event(teamer=1)
    puenktlich_dl = _dl()
    puenktlich = make_anfrage(eid, puenktlich_dl, status="Ausstehend", frist_datum=MORGEN)
    wartend_dl = _dl()
    wartend = make_anfrage(eid, wartend_dl, status="Abgelaufen", frist_datum=GESTERN)
    _antwort(client, wartend_dl, wartend)                       # → Warteliste
    assert reload(Verfuegbarkeitsanfrage, wartend).warteliste_seit

    _antwort(client, puenktlich_dl, puenktlich, "Nein")          # Platz wird frei
    a = reload(Verfuegbarkeitsanfrage, wartend)
    assert a.status == "Ausstehend" and a.warteliste_seit is None
    assert a.frist_datum and a.frist_datum >= HEUTE
    assert any("Doch noch ein Platz frei" in m[1] for m in mails)
    s = SessionLocal()
    try:
        g = s.query(Benachrichtigung).filter(Benachrichtigung.typ == "warteliste").first()
        assert g and "rückt nach" in g.titel
    finally:
        s.close()


def test_fristablauf_laesst_wartenden_nachruecken(client, db):
    from routes.cron import _run_abgelaufene_anfragen
    eid = _event(teamer=1)
    # pünktliche Anfrage, deren Frist gerade verstrichen ist
    make_anfrage(eid, _dl(), status="Ausstehend", frist_datum=GESTERN)
    wartend_dl = _dl()
    wartend = make_anfrage(eid, wartend_dl, status="Abgelaufen",
                           frist_datum=HEUTE - timedelta(days=3))
    s = SessionLocal()
    try:
        w = s.get(Verfuegbarkeitsanfrage, wartend)
        w.warteliste_seit = "2026-08-01T10:00:00"
        s.commit()
    finally:
        s.close()
    _run_abgelaufene_anfragen(db)
    a = reload(Verfuegbarkeitsanfrage, wartend)
    assert a.status == "Ausstehend" and a.warteliste_seit is None


def test_nachruecken_nur_so_viele_wie_plaetze(db):
    from besetzung import warteliste_nachruecken
    eid = _event(teamer=1)
    ev = reload(Event, eid)
    a1 = make_anfrage(eid, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    a2 = make_anfrage(eid, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    s = SessionLocal()
    try:
        s.get(Verfuegbarkeitsanfrage, a1).warteliste_seit = "2026-08-01T09:00:00"
        s.get(Verfuegbarkeitsanfrage, a2).warteliste_seit = "2026-08-01T11:00:00"
        s.commit()
    finally:
        s.close()
    reaktiviert = warteliste_nachruecken(db, ev, "Teamer")
    assert len(reaktiviert) == 1                       # nur 1 Platz frei
    assert reload(Verfuegbarkeitsanfrage, a1).status == "Ausstehend"   # ältester zuerst
    assert reload(Verfuegbarkeitsanfrage, a2).status == "Abgelaufen"


def test_admin_sieht_warteliste_badge(admin):
    eid = _event(teamer=1)
    aid = make_anfrage(eid, _dl(), status="Abgelaufen", frist_datum=GESTERN)
    s = SessionLocal()
    try:
        s.get(Verfuegbarkeitsanfrage, aid).warteliste_seit = "2026-08-20T10:00:00"
        s.commit()
    finally:
        s.close()
    assert "⏳ Warteliste" in admin.get(f"/admin/events/{eid}").text
