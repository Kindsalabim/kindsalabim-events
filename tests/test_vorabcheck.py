"""Vorab-Check: unverbindliche Anfrage an Dienstleister, bevor der Kunde ein Angebot bekommt.

Aykuts Problem (26.09.2026): Er fragt per WhatsApp „hältst du mir den Tag frei?", schickt
dem Kunden ein Angebot – und wenn der Kunde nie antwortet, erfährt der Dienstleister nichts.
Kalender und Mailversand sind in allen Tests gemockt.
"""
from datetime import date, timedelta

import calendar_service
from database import SessionLocal
from factories import make_dienstleister, reload
from models import Benachrichtigung, Dienstleister, Reservierung, Vorabanfrage, Vorabcheck

TAG = date.today() + timedelta(days=45)


def _check_anlegen(admin, **over):
    daten = {"datum": TAG.isoformat(), "startzeit": "14:00", "endzeit": "17:00",
             "aktion": "Ballonmodellage, Kinderschminken",
             "veranstaltungsort": "45657 Recklinghausen", "kunde_firma": "Stadtfest Recklinghausen",
             "budget": "300", "marke": "Kindsalabim"}
    daten.update(over)
    r = admin.post("/admin/vorabcheck/new", data=daten, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("/", 1)[1])


def _kuenstler(**kw):
    kw.setdefault("rolle", "Künstler")
    kw.setdefault("kuenstler_sparte", "Ballonkünstler")
    return make_dienstleister(**kw)


def _anfragen(admin, cid, dids, rolle="Künstler"):
    return admin.post(f"/admin/vorabcheck/{cid}/anfragen",
                      data={"dienstleister_ids": [str(d) for d in dids], "rolle": rolle},
                      follow_redirects=False)


def _anfrage(cid, did):
    s = SessionLocal()
    try:
        return s.query(Vorabanfrage).filter(Vorabanfrage.vorabcheck_id == cid,
                                            Vorabanfrage.dienstleister_id == did).first()
    finally:
        s.close()


def _an(mails, did):
    email = reload(Dienstleister, did).email
    return [m for m in mails if m[0] == email]


# ── Anlegen ──────────────────────────────────────────────────────────────────

def test_check_taucht_auf_der_reservierungsseite_auf(admin):
    cid = _check_anlegen(admin)
    html = admin.get("/admin/reservierungen").text
    assert "Vor dem Angebot" in html
    assert f"/admin/vorabcheck/{cid}" in html
    # Es entsteht KEINE Reservierung – der Kunde weiß noch nichts
    s = SessionLocal()
    try:
        assert s.query(Reservierung).filter(Reservierung.datum == TAG).count() == 0
    finally:
        s.close()


def test_detailseite_zeigt_daten_und_vorschlaege(admin):
    """Die Seite muss wirklich rendern – eigener Router, eigene Jinja-Umgebung."""
    cid = _check_anlegen(admin)
    _kuenstler(vorname="Ballon-Vorschlag", kuenstler_sparte="Ballonkünstler")
    html = admin.get(f"/admin/vorabcheck/{cid}").text
    assert "Ballonmodellage, Kinderschminken" in html
    assert TAG.strftime("%d.%m.%Y") in html
    assert "Künstler unverbindlich anfragen" in html
    assert "Ballon-Vorschlag" in html


def test_abschnitt_fehlt_ohne_offene_checks(admin):
    s = SessionLocal()
    try:
        for c in s.query(Vorabcheck).filter(Vorabcheck.status == "offen").all():
            c.status = "abgesagt"
        s.commit()
    finally:
        s.close()
    assert "Vor dem Angebot" not in admin.get("/admin/reservierungen").text


# ── Unverbindliche Anfrage ───────────────────────────────────────────────────

def test_anfrage_mail_sagt_deutlich_dass_es_keine_buchung_ist(admin, mails):
    cid = _check_anlegen(admin)
    did = _kuenstler(vorname="Nadja")
    _anfragen(admin, cid, [did])
    [(to, betreff, html)] = _an(mails, did)
    assert betreff.startswith("(Unverbindliche Anfrage)")
    assert "noch keine Buchung" in html
    a = _anfrage(cid, did)
    assert f"/vorab/{a.token}/ja" in html and f"/vorab/{a.token}/nein" in html
    assert a.status == "Ausstehend"


def test_keine_doppelte_anfrage(admin, mails):
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    _anfragen(admin, cid, [did])
    s = SessionLocal()
    try:
        assert s.query(Vorabanfrage).filter(Vorabanfrage.vorabcheck_id == cid).count() == 1
    finally:
        s.close()
    assert len(_an(mails, did)) == 1


# ── Antwort per Klick (ohne Login) ───────────────────────────────────────────

def test_zusage_per_klick_ohne_login(admin, client):
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    token = _anfrage(cid, did).token
    r = client.get(f"/vorab/{token}/ja")
    assert r.status_code == 200
    assert "Danke, notiert" in r.text and "noch keine Buchung" in r.text
    assert _anfrage(cid, did).status == "Ja"
    # Zweiter Klick (z. B. „Nein") ändert die gegebene Antwort nicht mehr
    r = client.get(f"/vorab/{token}/nein")
    assert "hattest du uns schon gegeben" in r.text
    assert _anfrage(cid, did).status == "Ja"


def test_absage_per_klick(admin, client):
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/nein")
    assert _anfrage(cid, did).status == "Nein"


def test_unbekannter_token_ist_404(client):
    assert client.get("/vorab/gibt-es-nicht/ja").status_code == 404


# ── Ausgang 1: Angebot raus → Reservierung ──────────────────────────────────

def test_zusage_wird_zur_reservierung(admin, client, monkeypatch):
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/ja")
    frist = date.today() + timedelta(days=7)
    r = admin.post(f"/admin/vorabcheck/{cid}/reservierung",
                   data={"frist": frist.isoformat()}, follow_redirects=False)
    assert r.status_code == 303
    s = SessionLocal()
    try:
        check = s.get(Vorabcheck, cid)
        res = s.get(Reservierung, check.reservierung_id)
        assert check.status == "uebernommen"
        assert res.datum == TAG and res.frist == frist
        assert res.kunde_firma == "Stadtfest Recklinghausen"
        assert res.anlass == "Ballonmodellage, Kinderschminken"
    finally:
        s.close()


# ── Ausgang 2: Kunde bekommt eine Absage ────────────────────────────────────

def test_absage_schickt_entwarnung(admin, client, mails):
    cid = _check_anlegen(admin)
    did = _kuenstler(vorname="Nadja")
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/ja")
    mails.clear()
    admin.post(f"/admin/vorabcheck/{cid}/absagen", follow_redirects=False)
    [(_, betreff, html)] = _an(mails, did)
    assert "Termin wieder frei" in betreff
    assert "wieder freigeben" in html
    assert _anfrage(cid, did).info_gesendet_am
    s = SessionLocal()
    try:
        assert s.get(Vorabcheck, cid).status == "abgesagt"
    finally:
        s.close()


def test_absage_ohne_zusagen_verschickt_nichts(admin, mails):
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    mails.clear()
    admin.post(f"/admin/vorabcheck/{cid}/absagen", follow_redirects=False)
    assert _an(mails, did) == []


# ── Reservierung endet: Rückmeldung an die, die freihalten ──────────────────

def test_freigeben_meldet_dem_dienstleister_dass_es_nichts_wird(admin, client, mails, monkeypatch):
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
    monkeypatch.setattr(calendar_service, "delete_event_async", lambda *a, **kw: True)
    cid = _check_anlegen(admin)
    did = _kuenstler(vorname="Nadja")
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/ja")
    admin.post(f"/admin/vorabcheck/{cid}/reservierung", data={}, follow_redirects=False)
    s = SessionLocal()
    try:
        rid = s.get(Vorabcheck, cid).reservierung_id
    finally:
        s.close()
    mails.clear()
    admin.post(f"/admin/reservierungen/{rid}/freigeben", follow_redirects=False)
    [(_, betreff, _html)] = _an(mails, did)
    assert "Termin wieder frei" in betreff


def test_umwandeln_meldet_die_buchung(admin, client, mails, monkeypatch):
    monkeypatch.setattr(calendar_service, "sync_reservierung_async", lambda rid: True)
    monkeypatch.setattr(calendar_service, "delete_event_async", lambda *a, **kw: True)
    monkeypatch.setattr(calendar_service, "sync_event_async", lambda eid: None)
    cid = _check_anlegen(admin)
    did = _kuenstler(vorname="Nadja")
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/ja")
    admin.post(f"/admin/vorabcheck/{cid}/reservierung", data={}, follow_redirects=False)
    s = SessionLocal()
    try:
        rid = s.get(Vorabcheck, cid).reservierung_id
    finally:
        s.close()
    mails.clear()
    admin.post(f"/admin/reservierungen/{rid}/umwandeln", follow_redirects=False)
    [(_, betreff, html)] = _an(mails, did)
    assert betreff.startswith("Gebucht:")
    assert "richtige Anfrage" in html
    s = SessionLocal()
    try:
        check = s.get(Vorabcheck, cid)
        assert check.status == "uebernommen" and check.event_id and check.reservierung_id is None
    finally:
        s.close()


# ── Erinnerung, solange jemand auf Bescheid wartet ──────────────────────────

def test_glocke_wenn_jemand_auf_bescheid_wartet(admin, client):
    from routes.vorab import offene_rueckmeldungen_melden
    cid = _check_anlegen(admin)
    did = _kuenstler(vorname="Nadja")
    _anfragen(admin, cid, [did])
    client.get(f"/vorab/{_anfrage(cid, did).token}/ja")
    s = SessionLocal()
    try:
        s.get(Vorabcheck, cid).frist = date.today() - timedelta(days=1)
        s.commit()
        offene_rueckmeldungen_melden(s)
        offene_rueckmeldungen_melden(s)          # zweiter Lauf am selben Tag: still
        meldungen = s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "vorab_wartet",
            Benachrichtigung.link == f"/admin/vorabcheck/{cid}").all()
        assert len(meldungen) == 1
        assert "Nadja" in meldungen[0].titel
    finally:
        s.close()


def test_texte_ohne_gedankenstrich(admin, client, mails):
    """Aykuts Vorgabe: In Texten an Dienstleister keine Gedankenstriche."""
    cid = _check_anlegen(admin)
    did = _kuenstler()
    _anfragen(admin, cid, [did])
    [(_, betreff, html)] = _an(mails, did)
    text = html.split("Hallo")[1].split("<table")[0]
    assert "–" not in betreff and "–" not in text
    seite = client.get(f"/vorab/{_anfrage(cid, did).token}/ja").text
    assert "–" not in seite.split("<body>")[1].split("<div class=\"daten\">")[0]
