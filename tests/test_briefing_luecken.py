"""Briefing senden fragt nach, wenn die Planung noch Lücken hat (Aykut 21.11.2026),
und die Wissensdatenbank zeigt wieder Aufzählungspunkte."""
from factories import make_event, make_dienstleister, make_anfrage


def test_rueckfrage_nennt_fehlende_teamer_und_offene_bestellung(admin):
    eid = make_event(produkte="Bastelaktion", anzahl_teamer=2, anzahl_kuenstler=0,
                     bestellung_manuell="ja")
    make_anfrage(eid, make_dienstleister(), status="Ja", rolle="Teamer")
    html = admin.get(f"/admin/events/{eid}").text
    assert 'data-luecken="Es fehlt noch 1 Teamer.|Die Bestellung ist noch offen."' in html
    assert "Trotzdem an alle bestätigten Dienstleister senden?" in html


def test_keine_luecken_kein_hinweis(admin):
    eid = make_event(produkte="Kinderschminken", anzahl_teamer=0, anzahl_kuenstler=1,
                     bestellung_manuell="nein")
    make_anfrage(eid, make_dienstleister(), status="Ja", rolle="Künstler")
    html = admin.get(f"/admin/events/{eid}").text
    assert 'data-luecken=""' in html


def test_leiste_sagt_team_statt_verfuegbarkeit(admin):
    eid = make_event()
    html = admin.get(f"/admin/events/{eid}").text
    assert 'title="Verfügbarkeit' not in html and ">Verfügbarkeit<" not in html


def test_wissen_listen_haben_punkte():
    for p in ("templates/admin/wissen_browse.html", "templates/portal/wissen_browse.html"):
        css = open(p, encoding="utf-8").read()
        assert ".prose-wissen ul{list-style:disc}" in css
        assert 'li[data-list="bullet"]{list-style:disc}' in css
