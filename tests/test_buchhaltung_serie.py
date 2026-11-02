"""Buchhaltung bei mehrtägigen Events (Aykut 02.11.2026): Eine Rechnung hing immer an
einem Termintag, die Fremdleistungen kamen nur von diesem Tag und die übrigen Tage
blieben in „Aus Event übernehmen" liegen. Jetzt gilt die Rechnung für die ganze
Serie; einzelne Tage lassen sich weiter getrennt abrechnen (Wert „<id>-tag")."""
import re
import secrets
from datetime import date, timedelta

from factories import make_event, make_dienstleister
from models import EventHonorar, Rechnung


def _serie(db, n=3):
    """n Termintage mit je einem offenen Honorar: 100 €, 200 €, am letzten Tag ohne
    Schätzung (so verfälschen die eingetragenen Ist-Beträge den Lernfaktor nicht)."""
    sid = secrets.token_hex(8)
    firma = f"Serienkunde {sid[:6]}"
    start = date.today() - timedelta(days=20)
    ids = [make_event(serien_id=sid, kunde_firma=firma, datum=start + timedelta(days=i))
           for i in range(n)]
    for i, eid in enumerate(ids):
        db.add(EventHonorar(event_id=eid, dienstleister_id=make_dienstleister(),
                            geschaetzt=100.0 * (i + 1) if i < n - 1 else None))
    db.commit()
    return ids, firma


def _optionen(admin):
    return re.findall(r'data-id="([^"]+)"', admin.get("/admin/buchhaltung").text)


def _neu(admin, wert, firma):
    admin.post("/admin/buchhaltung/neu", data={
        "datum": date.today().isoformat(), "kunde": firma, "brutto": "1000",
        "event_id": wert}, follow_redirects=False)


def test_serie_steht_einmal_mit_summe_und_einzeltagen(admin, db):
    ids, firma = _serie(db)
    html = admin.get("/admin/buchhaltung").text
    assert f"{firma} · alle 3 Tage" in html
    assert "Fremdl. 300,00 €" in html                       # 100 + 200 (+ Tag 3 ohne Satz)
    werte = _optionen(admin)
    assert str(ids[0]) in werte
    assert all(f"{eid}-tag" in werte for eid in ids)
    assert str(ids[1]) not in werte and str(ids[2]) not in werte


def test_rechnung_fuer_serie_deckt_alle_tage_ab(admin, db):
    ids, firma = _serie(db)
    _neu(admin, str(ids[0]), firma)
    werte = _optionen(admin)
    assert not any(w.split("-")[0] in map(str, ids) for w in werte)   # kein Datenmüll
    r = db.query(Rechnung).filter(Rechnung.kunde == firma).one()
    panel = admin.get(f"/admin/buchhaltung/{r.id}/honorare").text
    assert panel.count("/loeschen") == 3                     # Dienstleister aller Tage
    # Honorar am dritten Tag eintragen → Fremdleistungen über alle Tage nachgezogen
    h = db.query(EventHonorar).filter(EventHonorar.event_id == ids[2]).one()
    admin.post(f"/admin/buchhaltung/honorar/{h.id}", data={"betrag": "350"},
               follow_redirects=False)
    db.refresh(r)
    assert r.fremdleistungen == 650.0                        # 100 + 200 + 350 von Tag 3


def test_einzelner_tag_laesst_die_anderen_offen(admin, db):
    ids, firma = _serie(db)
    _neu(admin, f"{ids[1]}-tag", firma)
    r = db.query(Rechnung).filter(Rechnung.kunde == firma).one()
    assert r.nur_tag is True and r.event_id == ids[1]
    werte = _optionen(admin)
    assert str(ids[0]) in werte and str(ids[2]) in werte     # übrige Tage einzeln
    assert str(ids[1]) not in werte and f"{ids[0]}-tag" not in werte
    h = db.query(EventHonorar).filter(EventHonorar.event_id == ids[2]).one()
    admin.post(f"/admin/buchhaltung/honorar/{h.id}", data={"betrag": "999"},
               follow_redirects=False)
    db.refresh(r)
    assert not r.fremdleistungen                             # fremder Tag zieht nicht nach
    # Zweite Rechnung für Tag 3: deckt nur Tag 3 ab, nicht Tag 1
    _neu(admin, str(ids[2]), firma + " B")
    assert str(ids[0]) in _optionen(admin)


def test_bestandsrechnung_an_einem_tag_gilt_fuer_die_serie(admin, db):
    # Vor dem Umbau verknüpft (nur_tag leer), am mittleren Tag: deckt jetzt alle ab
    ids, firma = _serie(db)
    r = Rechnung(datum=date.today(), kunde=firma, brutto=900.0, event_id=ids[1])
    db.add(r)
    db.commit()
    assert not any(w.split("-")[0] in map(str, ids) for w in _optionen(admin))
    html = admin.get(f"/admin/buchhaltung/{r.id}/edit").text
    assert "gilt für alle 3 Tage" in html
