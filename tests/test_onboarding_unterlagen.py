"""Portal-Onboarding: Profil-Selbstauskunft, DSGVO-Online-Einwilligung (beide Firmen),
Gewerbeschein-Upload + Zusage-Sperre + wöchentliche Erinnerung."""
from datetime import date, timedelta

from database import SessionLocal
from models import Dienstleister, Benachrichtigung
from factories import make_dienstleister, make_event, make_anfrage, reload, portal_login
import routes.fotos as fotos_routes


def _neuer_dl(**kw):
    """Neuer Dienstleister im Neu-Zustand (keine Unterlagen)."""
    kw.setdefault("aktiv", True)
    kw.setdefault("gewerbeschein_vorliegt", False)
    kw.setdefault("dsgvo_unterzeichnet", False)
    return make_dienstleister(**kw)


# ── Profil-Seite ───────────────────────────────────────────────────────────────

def test_profil_speichert_daten_und_benachrichtigt(client):
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/profil", data={
        "telefon": "0176 123", "strasse": "Neue Straße 9", "plz": "45127",
        "stadt": "Essen", "kleidergroesse": "M", "fuehrerschein": "true",
        "mobilitaet": "ÖPNV"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    d = reload(Dienstleister, did)
    assert (d.strasse, d.plz, d.stadt) == ("Neue Straße 9", "45127", "Essen")
    assert d.kleidergroesse == "M" and d.fuehrerschein and d.mobilitaet == "ÖPNV"
    s = SessionLocal()
    n = s.query(Benachrichtigung).filter(Benachrichtigung.typ == "dl_unterlagen")\
         .order_by(Benachrichtigung.id.desc()).first()
    s.close()
    assert n and "Profil aktualisiert" in n.titel


def test_profil_plausibilitaet_plz_und_telefon(client):
    did = _neuer_dl()
    portal_login(client, did)
    # Ungültige PLZ (4 Ziffern) → Fehler, nichts gespeichert
    r = client.post("/portal/profil", data={"plz": "4512", "stadt": "Essen"},
                    follow_redirects=False)
    assert "fehler=plz" in r.headers["location"]
    assert reload(Dienstleister, did).stadt is None
    # Ungültige Telefonnummer (Buchstaben) → Fehler
    r = client.post("/portal/profil", data={"telefon": "keine nummer!"},
                    follow_redirects=False)
    assert "fehler=telefon" in r.headers["location"]
    # Manipulierte Select-Werte werden verworfen statt gespeichert
    client.post("/portal/profil", data={"kleidergroesse": "RIESIG", "mobilitaet": "Hubschrauber"},
                follow_redirects=False)
    d = reload(Dienstleister, did)
    assert d.kleidergroesse is None and d.mobilitaet == "Auto"
    # Formular trägt die HTML5-Muster (Client-Prüfung)
    h = client.get("/portal/profil").text
    assert 'pattern="\\d{5}"' in h and 'inputmode="tel"' in h


def test_profil_seite_zeigt_formulare_und_vorlagen(client):
    did = _neuer_dl()
    portal_login(client, did)
    h = client.get("/portal/profil").text
    assert "Datenschutz-Einwilligung" in h
    assert "Malca &amp; Akmanoglu GbR" in h and "Kindsalabim Kinderevents" in h
    assert "Gewerbeschein" in h and "/portal/profil/gewerbeschein" in h
    assert "/static/vorlagen/Rechnungsvorlage.xls" in h
    assert "/static/vorlagen/Infoblatt-Kleingewerbe.pdf" in h


# ── DSGVO (beide Firmen in einem Rutsch) ──────────────────────────────────────

def test_dsgvo_beide_firmen_in_einem_rutsch(client):
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/profil/dsgvo", data={
        "dsgvo_name": "Ayse Nur Test", "einwilligung_knallfrosch": "true",
        "einwilligung_kindsalabim": "true"}, follow_redirects=False)
    assert r.status_code == 303 and "dsgvo=1" in r.headers["location"]
    d = reload(Dienstleister, did)
    assert d.dsgvo_unterzeichnet and d.dsgvo_ok
    assert d.dsgvo_knallfrosch_am and d.dsgvo_kindsalabim_am
    assert d.dsgvo_name == "Ayse Nur Test"


def test_dsgvo_ohne_beide_haken_wird_abgelehnt(client):
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/profil/dsgvo", data={
        "dsgvo_name": "Nur Eins", "einwilligung_knallfrosch": "true"},
        follow_redirects=False)
    assert "dsgvo_fehler=1" in r.headers["location"]
    assert not reload(Dienstleister, did).dsgvo_ok


# ── Gewerbeschein-Upload ──────────────────────────────────────────────────────

def test_gewerbeschein_upload_setzt_status(client, monkeypatch):
    monkeypatch.setattr(fotos_routes, "_r2_put", lambda key, data, ct: True)
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/profil/gewerbeschein",
                    files={"file": ("schein.jpg", b"fake-bild-daten", "image/jpeg")},
                    follow_redirects=False)
    assert r.status_code == 303 and "gewerbeschein=1" in r.headers["location"]
    d = reload(Dienstleister, did)
    assert d.gewerbeschein_r2_key and d.gewerbeschein_ok
    assert d.gewerbeschein_filename == "schein.jpg"


def test_gewerbeschein_upload_falscher_typ(client):
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/profil/gewerbeschein",
                    files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
                    follow_redirects=False)
    assert "gewerbeschein_fehler=typ" in r.headers["location"]
    assert not reload(Dienstleister, did).gewerbeschein_ok


# ── Zusage-Sperre ─────────────────────────────────────────────────────────────

def test_zusage_gesperrt_ohne_unterlagen(client):
    did = _neuer_dl()
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    r = client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    assert "unterlagen_fehlen=1" in r.headers["location"]
    from models import Verfuegbarkeitsanfrage
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ausstehend"


def test_absage_trotz_fehlender_unterlagen_moeglich(client):
    did = _neuer_dl()
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Nein"}, follow_redirects=False)
    from models import Verfuegbarkeitsanfrage
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Nein"


def test_zusage_erlaubt_mit_unterlagen(client):
    did = _neuer_dl(gewerbeschein_vorliegt=True, dsgvo_unterzeichnet=True)
    aid = make_anfrage(make_event(), did, status="Ausstehend")
    portal_login(client, did)
    client.post(f"/portal/antwort/{aid}", data={"antwort": "Ja"}, follow_redirects=False)
    from models import Verfuegbarkeitsanfrage
    assert reload(Verfuegbarkeitsanfrage, aid).status == "Ja"


def test_dashboard_zeigt_unterlagen_banner(client):
    did = _neuer_dl()
    portal_login(client, did)
    h = client.get("/portal").text
    assert "noch nicht vollständig" in h and "/portal/profil" in h


# ── Einladung startet Erinnerungs-Uhr, Cron erinnert wöchentlich ──────────────

def test_einladung_startet_gewerbeschein_uhr(admin, mails):
    did = _neuer_dl()
    r = admin.post(f"/admin/dienstleister/{did}/einladung", follow_redirects=False)
    assert r.status_code == 303
    d = reload(Dienstleister, did)
    assert d.gewerbeschein_erinnert_am == date.today()
    assert any("Willkommen" in m[1] for m in mails)


def test_einladung_zeigt_erfolgsmeldung_in_der_liste(admin):
    did = _neuer_dl(vorname="Banner", nachname="Test")
    r = admin.post(f"/admin/dienstleister/{did}/einladung", follow_redirects=False)
    h = admin.get(r.headers["location"]).text
    assert "Einladung verschickt" in h and "Banner Test" in h


def test_einladung_startet_keine_uhr_bei_bestand(admin):
    did = _neuer_dl(gewerbeschein_vorliegt=True)
    admin.post(f"/admin/dienstleister/{did}/einladung", follow_redirects=False)
    assert reload(Dienstleister, did).gewerbeschein_erinnert_am is None


def test_cron_erinnert_nach_7_tagen_und_wiederholt(client, mails):
    from routes.cron import _run_gewerbeschein_erinnerungen
    faellig  = _neuer_dl(gewerbeschein_erinnert_am=date.today() - timedelta(days=8))
    zu_frueh = _neuer_dl(gewerbeschein_erinnert_am=date.today() - timedelta(days=3))
    erledigt = _neuer_dl(gewerbeschein_vorliegt=True,
                         gewerbeschein_erinnert_am=date.today() - timedelta(days=30))
    ohne_uhr = _neuer_dl()   # nie eingeladen → keine Erinnerung
    s = SessionLocal()
    try:
        count = _run_gewerbeschein_erinnerungen(s)
    finally:
        s.close()
    assert count >= 1
    empfaenger = [m[0] for m in mails if "Gewerbeschein" in m[1]]
    assert reload(Dienstleister, faellig).email in empfaenger
    for did in (zu_frueh, erledigt, ohne_uhr):
        assert reload(Dienstleister, did).email not in empfaenger
    # Uhr wurde neu gestellt → nächste Erinnerung erst in 7 Tagen
    assert reload(Dienstleister, faellig).gewerbeschein_erinnert_am == date.today()


# ── Onboarding-Abschluss leitet zum Profil ────────────────────────────────────

def test_onboarding_ende_leitet_zum_profil_wenn_unterlagen_fehlen(client):
    did = _neuer_dl()
    portal_login(client, did)
    r = client.post("/portal/onboarding/abschliessen", follow_redirects=False)
    assert r.headers["location"] == "/portal/profil?willkommen=1"
    assert reload(Dienstleister, did).onboarding_abgeschlossen


def test_onboarding_ende_leitet_zum_dashboard_wenn_alles_da(client):
    did = _neuer_dl(gewerbeschein_vorliegt=True, dsgvo_unterzeichnet=True)
    portal_login(client, did)
    r = client.post("/portal/onboarding/abschliessen", follow_redirects=False)
    assert r.headers["location"] == "/portal"


# ── Admin sieht Status ────────────────────────────────────────────────────────

def test_admin_detail_zeigt_unterlagen_status(admin):
    did = _neuer_dl()
    h = admin.get(f"/admin/dienstleister/{did}").text
    assert "Gewerbeschein" in h and "fehlt" in h
