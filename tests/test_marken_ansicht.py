"""Persönliche Marken-Ansicht je Admin: Dashboard, Reservierungen, Buchhaltung,
Glocke und Mailversand zeigen nur die gewählte(n) Marke(n)."""
from datetime import date

import marken
from auth import create_token
from database import SessionLocal
from models import Admin, Benachrichtigung, Rechnung, Reservierung
from factories import make_event, reload


def _admin(email, filter_wert="beide"):
    """Admin anlegen/aktualisieren und einen passenden Login-Cookie liefern."""
    s = SessionLocal()
    try:
        a = s.query(Admin).filter(Admin.email == email).first()
        if not a:
            a = Admin(email=email, password_hash="x", aktiv=True)
            s.add(a)
        a.marken_filter = filter_wert
        a.aktiv = True
        s.commit()
    finally:
        s.close()
    return create_token({"sub": email, "role": "admin"}, expires_minutes=60)


def _als(client, email, filter_wert="beide"):
    client.cookies.set("admin_token", _admin(email, filter_wert))
    return client


# ── Helfer-Logik ──────────────────────────────────────────────────────────────

def test_passt_und_normalisieren():
    assert marken.normalisieren("Knallfrosch") == "Knallfrosch"
    assert marken.normalisieren("quatsch") == "beide"
    assert marken.normalisieren(None) == "beide"
    assert marken.passt("Kindsalabim", "beide")
    assert marken.passt(None, "Knallfrosch")          # ohne Marke = immer sichtbar
    assert not marken.passt("Kindsalabim", "Knallfrosch")


# ── Dashboard & Reservierungen ────────────────────────────────────────────────

def test_dashboard_filtert_events_und_reservierungen(client):
    make_event(kunde_firma="KS Sichtbar GmbH", marke="Kindsalabim",
               datum=date(2027, 5, 1), anlass="KS Fest")
    make_event(kunde_firma="KF Sichtbar GmbH", marke="Knallfrosch",
               datum=date(2027, 5, 2), anlass="KF Fest")
    s = SessionLocal()
    try:
        s.add(Reservierung(datum=date(2027, 6, 1), kunde_firma="KS Reservierung",
                           marke="Kindsalabim"))
        s.add(Reservierung(datum=date(2027, 6, 2), kunde_firma="KF Reservierung",
                           marke="Knallfrosch"))
        s.commit()
    finally:
        s.close()

    h = _als(client, "beides@example.com", "beide").get("/admin/dashboard").text
    assert "KS Sichtbar GmbH" in h and "KF Sichtbar GmbH" in h

    h = _als(client, "nurkf@example.com", "Knallfrosch").get("/admin/dashboard").text
    assert "KF Sichtbar GmbH" in h and "KS Sichtbar GmbH" not in h

    r = _als(client, "nurkf@example.com", "Knallfrosch").get("/admin/reservierungen").text
    assert "KF Reservierung" in r and "KS Reservierung" not in r


def test_umschalter_speichert_und_wirkt(client):
    _als(client, "wechsel@example.com", "beide")
    r = client.post("/admin/marken-ansicht",
                    data={"wert": "Knallfrosch", "weiter": "/admin/dashboard"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/dashboard"
    s = SessionLocal()
    try:
        assert s.query(Admin).filter_by(email="wechsel@example.com").first().marken_filter == "Knallfrosch"
    finally:
        s.close()
    # offenes Redirect-Ziel wird abgewiesen
    r = client.post("/admin/marken-ansicht",
                    data={"wert": "beide", "weiter": "https://evil.example"},
                    follow_redirects=False)
    assert r.headers["location"] == "/admin/dashboard"


# ── Buchhaltung ───────────────────────────────────────────────────────────────

def _rechnung(kunde, marke, brutto=1000.0, jahr=2027):
    s = SessionLocal()
    try:
        r = Rechnung(datum=date(jahr, 3, 1), kunde=kunde, marke=marke,
                     brutto=brutto, rgnr=f"RE-{kunde[:4]}")
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def test_buchhaltung_blendet_fremde_marke_aus(client):
    _rechnung("KS Buchung GmbH", "Kindsalabim", 1000.0)
    _rechnung("KF Buchung GmbH", "Knallfrosch", 500.0)

    h = _als(client, "beides@example.com", "beide").get("/admin/buchhaltung?jahr=2027").text
    assert "KS Buchung GmbH" in h and "KF Buchung GmbH" in h

    h = _als(client, "nurkf@example.com", "Knallfrosch").get("/admin/buchhaltung?jahr=2027").text
    assert "KF Buchung GmbH" in h and "KS Buchung GmbH" not in h
    # Summen dürfen die ausgeblendete Rechnung nicht mitzählen
    assert "1.000,00" not in h


def test_buchhaltung_export_folgt_der_ansicht(client):
    _rechnung("KS Export GmbH", "Kindsalabim")
    _rechnung("KF Export GmbH", "Knallfrosch")
    csv_kf = _als(client, "nurkf@example.com", "Knallfrosch").get(
        "/admin/buchhaltung/export.csv?jahr=2027").text
    assert "KF Export GmbH" in csv_kf and "KS Export GmbH" not in csv_kf


def test_neue_rechnung_bekommt_marke(client):
    _als(client, "nurkf@example.com", "Knallfrosch")
    client.post("/admin/buchhaltung/neu",
                data={"datum": "2027-04-01", "kunde": "Neue KF Rechnung",
                      "brutto": "300", "marke": "Knallfrosch"}, follow_redirects=False)
    s = SessionLocal()
    try:
        r = s.query(Rechnung).filter_by(kunde="Neue KF Rechnung").first()
        assert r and r.marke == "Knallfrosch"
    finally:
        s.close()


# ── Glocke & Mailversand ──────────────────────────────────────────────────────

def test_glocke_filtert_nach_marke(client):
    from notifications import notify
    s = SessionLocal()
    try:
        notify(s, "dl_zusage", "KS-Meldung Zusage", "nur Kindsalabim", marke="Kindsalabim")
        notify(s, "dl_zusage", "KF-Meldung Zusage", "nur Knallfrosch", marke="Knallfrosch")
        notify(s, "dl_urlaub", "Allgemeine Meldung", "ohne Marke")
        s.commit()
    finally:
        s.close()
    h = _als(client, "nurkf@example.com", "Knallfrosch").get("/admin/benachrichtigungen").text
    assert "KF-Meldung Zusage" in h and "Allgemeine Meldung" in h
    assert "KS-Meldung Zusage" not in h


def test_notify_mail_nur_an_passende_admins(mails):
    from notifications import notify, set_mail_enabled
    _admin("mail_beide@example.com", "beide")
    _admin("mail_kf@example.com", "Knallfrosch")
    _admin("mail_ks@example.com", "Kindsalabim")
    s = SessionLocal()
    try:
        set_mail_enabled(s, "dl_zusage", True)
        s.commit()
        notify(s, "dl_zusage", "Zusage KS-Event", "Text", marke="Kindsalabim")
        s.commit()
    finally:
        s.close()
    empfaenger = [m[0] for m in mails]
    assert "mail_beide@example.com" in empfaenger and "mail_ks@example.com" in empfaenger
    assert "mail_kf@example.com" not in empfaenger


def test_benachrichtigung_ohne_marke_geht_an_alle(mails):
    from notifications import notify, set_mail_enabled
    _admin("mail_kf2@example.com", "Knallfrosch")
    s = SessionLocal()
    try:
        set_mail_enabled(s, "dl_urlaub", True)
        s.commit()
        notify(s, "dl_urlaub", "Urlaub gemeldet", "Text")   # markenneutral
        s.commit()
    finally:
        s.close()
    assert "mail_kf2@example.com" in [m[0] for m in mails]
