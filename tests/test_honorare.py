"""Fremdleistungen: Schätzung bei der Zusage, Nachtrag der echten Rechnung, Arbeitsliste."""
from datetime import date, timedelta
from types import SimpleNamespace

import honorare
from database import SessionLocal
from models import (Dienstleister, Event, EventHonorar, Rechnung,
                    Verfuegbarkeitsanfrage, Benachrichtigung)
from factories import make_event, make_dienstleister, make_anfrage, reload, portal_login


def _ev_ns(**over):
    base = dict(startzeit="14:00", endzeit="18:00", veranstaltungsort="Markt 1, 45127 Essen")
    base.update(over)
    return SimpleNamespace(**base)


def _dl_ns(**over):
    base = dict(stundensatz_teamer=25.0, stundensatz_kuenstler=60.0,
                plz="45127", strasse="", stadt="Essen")
    base.update(over)
    return SimpleNamespace(**base)


def _a_ns(**over):
    base = dict(rolle_anfrage="Teamer", budget=None, als_logistiker=False)
    base.update(over)
    return SimpleNamespace(**base)


# ── Schätzung ────────────────────────────────────────────────────────────────

def test_schaetzung_enthaelt_aufbauzeit():
    """4 Std Aktionszeit + 1 Std Auf-/Abbau × 25 € = 125 € (Fahrzeit ~0, gleiche PLZ)."""
    wert = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns())
    assert wert >= 125.0
    # Die reine Aktionszeit (100 €) wäre zu wenig – genau das ist der Punkt
    assert wert > 100.0


def test_schaetzung_mit_fahrzeit():
    """Weiter entfernter Dienstleister → Fahrzeit schlägt sich nieder."""
    nah = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns(plz="45127", stadt="Essen"))
    fern = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns(plz="80331", stadt="München"))
    assert fern > nah


def test_schaetzung_kuenstler_nimmt_budget():
    wert = honorare.schaetzung(_a_ns(rolle_anfrage="Künstler", budget=450.0), _ev_ns(), _dl_ns())
    assert wert == 450.0


def test_schaetzung_ohne_satz_ist_none():
    assert honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns(stundensatz_teamer=None)) is None


def test_schaetzung_logistiker_bekommt_zuschlag():
    ohne = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns())
    mit = honorare.schaetzung(_a_ns(als_logistiker=True), _ev_ns(), _dl_ns())
    assert mit > ohne


def test_faktor_wird_angewendet():
    basis = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns())
    erhoeht = honorare.schaetzung(_a_ns(), _ev_ns(), _dl_ns(), faktor=1.2)
    assert round(erhoeht, 2) == round(basis * 1.2, 2)


# ── Lernfaktor ───────────────────────────────────────────────────────────────

def test_lernfaktor_ohne_daten_ist_neutral(db):
    """Aus drei Zufallswerten wird nicht hochgerechnet."""
    assert honorare.lernfaktor(db) == 1.0


def test_lernfaktor_aus_ist_werten(db):
    s = SessionLocal()
    try:
        eid = make_event()
        for i in range(honorare.LERN_MINDESTZAHL):
            did = make_dienstleister()
            s.add(EventHonorar(event_id=eid, dienstleister_id=did,
                               geschaetzt=100.0, tatsaechlich=120.0))
        s.commit()
        assert honorare.lernfaktor(s) == 1.2
    finally:
        s.close()


def test_lernfaktor_ist_gedeckelt(db):
    s = SessionLocal()
    try:
        eid = make_event()
        for i in range(honorare.LERN_MINDESTZAHL):
            did = make_dienstleister()
            s.add(EventHonorar(event_id=eid, dienstleister_id=did,
                               geschaetzt=100.0, tatsaechlich=1000.0))
        s.commit()
        assert honorare.lernfaktor(s) == honorare.LERN_MAX
    finally:
        s.close()


# ── Zusage / Absage ──────────────────────────────────────────────────────────

def test_zusage_legt_honorarzeile_an(client, db):
    eid = make_event()
    did = make_dienstleister(stundensatz_teamer=25.0)
    aid = make_anfrage(eid, did, status="Ausstehend")
    c = portal_login(client, did)
    r = c.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    h = db.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                      EventHonorar.dienstleister_id == did).first()
    assert h is not None and h.geschaetzt > 0
    assert h.offen and h.tatsaechlich is None


def test_absage_entfernt_offene_zeile(client, db):
    eid = make_event()
    did = make_dienstleister(stundensatz_teamer=25.0)
    aid = make_anfrage(eid, did, status="Ausstehend")
    c = portal_login(client, did)
    r = c.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    assert r.status_code == 303
    c.post(f"/portal/antwort/{aid}", data={"antwort": "Nein"}, follow_redirects=False)
    db.expire_all()
    assert db.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                         EventHonorar.dienstleister_id == did).first() is None


def test_erfasste_rechnung_ueberlebt_eine_absage(db):
    """Ist das Honorar schon bezahlt, darf eine spätere Absage es nicht löschen."""
    s = SessionLocal()
    try:
        eid = make_event()
        did = make_dienstleister()
        s.add(EventHonorar(event_id=eid, dienstleister_id=did,
                           geschaetzt=100.0, tatsaechlich=140.0))
        s.commit()
        a = SimpleNamespace(event_id=eid, dienstleister_id=did)
        honorare.honorar_entfernen(s, a)
        s.commit()
        assert s.query(EventHonorar).filter(EventHonorar.event_id == eid,
                                            EventHonorar.dienstleister_id == did).first()
    finally:
        s.close()


# ── Nachtrag in der Buchhaltung ──────────────────────────────────────────────

def _event_mit_rechnung(db, honorare_werte=(200.0, 300.0)):
    """Event mit zwei geschätzten Honoraren + verknüpfter Kundenrechnung."""
    eid = make_event(datum=date.today() - timedelta(days=10))
    s = SessionLocal()
    try:
        hids = []
        for wert in honorare_werte:
            did = make_dienstleister()
            h = EventHonorar(event_id=eid, dienstleister_id=did, geschaetzt=wert)
            s.add(h); s.commit(); s.refresh(h)
            hids.append(h.id)
        r = Rechnung(datum=date.today(), kunde="Testkunde", brutto=2000.0,
                     event_id=eid, fremdleistungen=sum(honorare_werte),
                     marke="Kindsalabim")
        s.add(r); s.commit(); s.refresh(r)
        return eid, hids, r.id
    finally:
        s.close()


def test_ist_wert_zieht_die_rechnung_nach(admin, db):
    eid, hids, rid = _event_mit_rechnung(db)          # 200 + 300 geschätzt
    admin.post(f"/admin/buchhaltung/honorar/{hids[0]}", data={"betrag": "260,00"},
               follow_redirects=False)
    db.expire_all()
    assert reload(EventHonorar, hids[0]).tatsaechlich == 260.0
    assert reload(EventHonorar, hids[0]).eingegangen_am == date.today()
    # Fremdleistungen der Kundenrechnung: 260 (Ist) + 300 (weiter geschätzt)
    assert reload(Rechnung, rid).fremdleistungen == 560.0


def test_geleerte_eingabe_macht_die_zeile_wieder_offen(admin, db):
    eid, hids, rid = _event_mit_rechnung(db)
    admin.post(f"/admin/buchhaltung/honorar/{hids[0]}", data={"betrag": "260,00"})
    admin.post(f"/admin/buchhaltung/honorar/{hids[0]}", data={"betrag": ""})
    db.expire_all()
    h = reload(EventHonorar, hids[0])
    assert h.tatsaechlich is None and h.offen
    assert reload(Rechnung, rid).fremdleistungen == 500.0     # wieder beide geschätzt


def test_zeile_loeschen_zieht_die_rechnung_nach(admin, db):
    eid, hids, rid = _event_mit_rechnung(db)
    admin.post(f"/admin/buchhaltung/honorar/{hids[0]}/loeschen", follow_redirects=False)
    db.expire_all()
    assert reload(EventHonorar, hids[0]) is None
    assert reload(Rechnung, rid).fremdleistungen == 300.0


def test_liste_zeigt_aufschluesselung_und_badge(admin, db):
    eid, hids, rid = _event_mit_rechnung(db)
    html = admin.get(f"/admin/buchhaltung?jahr={date.today().year}").text
    assert f"hon-{rid}" in html                    # Aufklapper vorhanden
    assert "⏳2" in html                            # zwei Rechnungen ausstehend
    assert "Ausstehende Dienstleister-Rechnungen" in html


def test_abgerechnete_events_stehen_nicht_zur_auswahl(admin, db):
    """Eine zweite Rechnung an dasselbe Event gibt es nicht – solche Events
    gehören nicht in die „Aus Event übernehmen"-Liste."""
    eid, hids, rid = _event_mit_rechnung(db)
    html = admin.get(f"/admin/buchhaltung?jahr={date.today().year}").text
    assert f'data-id="{eid}"' not in html

    # Ohne Rechnung taucht dasselbe Event wieder auf
    s = SessionLocal()
    try:
        s.query(Rechnung).filter(Rechnung.id == rid).update({Rechnung.event_id: None})
        s.commit()
    finally:
        s.close()
    html2 = admin.get(f"/admin/buchhaltung?jahr={date.today().year}").text
    assert f'data-id="{eid}"' in html2


def test_event_laesst_sich_nachtraeglich_zuordnen(admin, db):
    """Bestandsrechnungen haben keine Event-Verknüpfung – ohne die gibt es keine
    Aufschlüsselung. Das Bearbeiten-Formular muss sie nachtragen können."""
    eid = make_event(datum=date.today() - timedelta(days=5))
    s = SessionLocal()
    try:
        did = make_dienstleister()
        s.add(EventHonorar(event_id=eid, dienstleister_id=did, geschaetzt=190.0))
        r = Rechnung(datum=date.today(), kunde="Nachtrag GmbH", brutto=900.0,
                     marke="Kindsalabim", fremdleistungen=0.0)
        s.add(r); s.commit(); s.refresh(r)
        rid = r.id
    finally:
        s.close()
    assert 'name="event_id"' in admin.get(f"/admin/buchhaltung/{rid}/edit").text
    admin.post(f"/admin/buchhaltung/{rid}/edit", data={
        "datum": date.today().isoformat(), "kunde": "Nachtrag GmbH", "rgnr": "",
        "brutto": "900,00", "fremdleistungen": "0", "materialkosten": "0",
        "notiz": "", "marke": "Kindsalabim", "event_id": str(eid),
    }, follow_redirects=False)
    db.expire_all()
    r2 = reload(Rechnung, rid)
    assert r2.event_id == eid
    assert r2.fremdleistungen == 190.0        # Summe aus den Honorarzeilen übernommen


def test_bestandsrechnungen_werden_ihrem_event_zugeordnet(db):
    """Ohne Verknüpfung greift weder die Aufschlüsselung noch der Filter
    „Event hat schon eine Rechnung". Der Backfill stellt sie über Kunde + Datum her."""
    from main import link_rechnungen_events
    from models import AppEinstellung
    s = SessionLocal()
    try:
        # Schalter zurücksetzen – der Backfill läuft bewusst nur einmal
        s.query(AppEinstellung).filter(
            AppEinstellung.key == "rechnung_event_backfill").delete()
        s.commit()
        eid = make_event(datum=date.today() - timedelta(days=20),
                         kunde_firma="Zuordnungs-Kunde GmbH")
        r = Rechnung(datum=date.today(), kunde="zuordnungs-kunde gmbh",   # andere Schreibung
                     brutto=1200.0, marke="Kindsalabim")
        s.add(r); s.commit(); s.refresh(r)
        rid = r.id
    finally:
        s.close()
    link_rechnungen_events()
    db.expire_all()
    assert reload(Rechnung, rid).event_id == eid


def test_zuordnung_ueberspringt_zu_alte_events(db):
    """Ein Event von vor über 90 Tagen gehört nicht zu einer heutigen Rechnung."""
    from main import link_rechnungen_events
    from models import AppEinstellung
    s = SessionLocal()
    try:
        s.query(AppEinstellung).filter(
            AppEinstellung.key == "rechnung_event_backfill").delete()
        s.commit()
        make_event(datum=date.today() - timedelta(days=200), kunde_firma="Uralt AG")
        r = Rechnung(datum=date.today(), kunde="Uralt AG", brutto=500.0,
                     marke="Kindsalabim")
        s.add(r); s.commit(); s.refresh(r)
        rid = r.id
    finally:
        s.close()
    link_rechnungen_events()
    db.expire_all()
    assert reload(Rechnung, rid).event_id is None


def test_auswahl_zeigt_events_ohne_erfasste_kosten(admin, db):
    """Auch ein Event ohne Bestellungen/Honorare braucht die Verknüpfung –
    sonst fehlt es in der Auswahl (Fall „ggw")."""
    eid = make_event(datum=date.today() - timedelta(days=3),
                     kunde_firma="Ohne Kosten GmbH")
    html = admin.get(f"/admin/buchhaltung?jahr={date.today().year}").text
    assert f'data-id="{eid}"' in html


def test_auswahl_sortiert_zuletzt_gelaufene_zuerst(admin, db):
    from routes.buchhaltung import _event_vorschlaege
    make_event(datum=date.today() - timedelta(days=2), kunde_firma="Gestern GmbH")
    make_event(datum=date.today() + timedelta(days=40), kunde_firma="Bald GmbH")
    v = _event_vorschlaege(db, "beide")
    daten = [e["datum"] for e in v]
    vergangen = [d for d in daten if d <= date.today()]
    kuenftig = [d for d in daten if d > date.today()]
    assert vergangen == sorted(vergangen, reverse=True)   # jüngstes zuerst
    assert kuenftig == sorted(kuenftig)                   # danach die kommenden
    if vergangen and kuenftig:
        assert daten.index(vergangen[0]) < daten.index(kuenftig[0])


def test_erinnerung_verschickt_mail(admin, db, mails):
    eid, hids, rid = _event_mit_rechnung(db)
    admin.post(f"/admin/buchhaltung/honorar/{hids[0]}/erinnern", follow_redirects=False)
    db.expire_all()
    assert reload(EventHonorar, hids[0]).erinnert_am == date.today()
    assert mails and "Rechnung zu" in mails[-1][1]


# ── Glocke 30 Tage nach dem Event ────────────────────────────────────────────

def test_glocke_nach_30_tagen_einmalig(db):
    """Die Test-DB wird nicht pro Test zurückgesetzt – deshalb wird gezielt auf das
    eigene Event geprüft statt auf absolute Zähler."""
    from routes.cron import _run_honorar_erinnerungen
    eid = make_event(datum=date.today() - timedelta(days=31))
    s = SessionLocal()
    try:
        firma = s.get(Event, eid).kunde_firma
        for _ in range(2):
            s.add(EventHonorar(event_id=eid, dienstleister_id=make_dienstleister(),
                               geschaetzt=200.0))
        s.commit()
        _run_honorar_erinnerungen(s)
        meine = [b for b in s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "honorar_offen").all() if firma in (b.text or "")]
        assert len(meine) == 1                       # eine Sammelmeldung, nicht zwei
        assert "2 Dienstleister-Rechnungen" in meine[0].titel
        zeilen = s.query(EventHonorar).filter(EventHonorar.event_id == eid).all()
        assert all(h.erinnert_am == date.today() for h in zeilen)

        # Zweiter Lauf meldet zu diesem Event nichts mehr
        _run_honorar_erinnerungen(s)
        nochmal = [b for b in s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "honorar_offen").all() if firma in (b.text or "")]
        assert len(nochmal) == 1
    finally:
        s.close()


def test_keine_glocke_vor_30_tagen(db):
    from routes.cron import _run_honorar_erinnerungen
    eid = make_event(datum=date.today() - timedelta(days=5))
    s = SessionLocal()
    try:
        s.add(EventHonorar(event_id=eid, dienstleister_id=make_dienstleister(),
                           geschaetzt=200.0))
        s.commit()
        vorher = s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "honorar_offen").count()
        _run_honorar_erinnerungen(s)
        assert s.query(Benachrichtigung).filter(
            Benachrichtigung.typ == "honorar_offen").count() == vorher
    finally:
        s.close()
