# -*- coding: utf-8 -*-
"""Erzeugt das Admin-Handbuch der Events-App als PDF (doku/Events-App_Handbuch.pdf).

Aufruf aus dem Repo-Wurzelverzeichnis:  PYTHONUTF8=1 python doku/build_handbuch.py

Ablauf (vollautomatisch, ~1 Minute):
  1. Abgesicherte Sandbox der App starten: Wegwerf-SQLite mit Beispieldaten,
     Mail/Kalender/R2 als No-ops gepatcht, Login per Dependency-Override umgangen
     (nur 127.0.0.1, lebt nur für die Dauer dieses Skripts).
  2. Screenshots der wichtigsten Seiten per Chrome-Headless aufnehmen.
  3. PDF mit Kapiteltexten + Screenshots bauen.

Bei UI-/Funktionsänderungen: Kapiteltexte unten anpassen und Skript neu laufen
lassen (Teil des /abschluss-Ablaufs). SICHERHEIT: Es wird NIE die echte DB
angefasst und nichts versendet – alle externen Effekte sind gepatcht.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta

DOKU = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DOKU)
TMP = os.path.join(DOKU, "_tmp")
SHOTS = os.path.join(DOKU, "_shots")
PORT = 8978
PDF_OUT = os.path.join(DOKU, "Events-App_Handbuch.pdf")

sys.path.insert(0, REPO)
os.chdir(REPO)   # Templates/Static werden relativ zum Repo geladen

# ── 1. Sandbox vorbereiten ────────────────────────────────────────────────────
for d in (TMP, SHOTS):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
DB = os.path.join(TMP, "handbuch.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ.setdefault("SECRET_KEY", "handbuch-sandbox")

import email_service, calendar_service                     # noqa: E402
email_service._deliver = lambda *a, **kw: None             # keine echten Mails
calendar_service._service = lambda: None                   # kein Google-Kalender
import routes.fotos as _fotos                              # noqa: E402
_fotos._r2_client = lambda: None                           # kein R2

import main                                                # noqa: E402
from auth import get_admin_user, get_portal_user           # noqa: E402
from database import SessionLocal, engine, Base            # noqa: E402

Base.metadata.create_all(bind=engine)
main.run_migrations()

# ── 2. Beispieldaten ─────────────────────────────────────────────────────────
import json                                                 # noqa: E402
from models import (Event, Kunde, Dienstleister, Verfuegbarkeitsanfrage,   # noqa: E402
                    EventBestellung, Reservierung, Rechnung, Benachrichtigung)

s = SessionLocal()

def dl(vorname, nachname, rolle, **kw):
    d = Dienstleister(vorname=vorname, nachname=nachname, rolle=rolle,
                      email=f"{vorname.lower()}@beispiel.example",
                      telefon="0151 000000", aktiv=True, **kw)
    s.add(d); s.flush()
    return d

lisa = dl("Lisa", "Klein", "Teamer", stadt="Essen", lieferantenbewertung=10)
tom  = dl("Tom", "Wagner", "Teamer", stadt="Bochum", lieferantenbewertung=8,
          logistiker=True, fuehrerschein=True)
mia  = dl("Mia", "Farben", "Künstler", stadt="Essen", lieferantenbewertung=10,
          kuenstler_sparte="Kinderschminke")
ziad = dl("Ziad", "Zauber", "Künstler", stadt="Dortmund", lieferantenbewertung=7,
          kuenstler_sparte="Showact")
nina = dl("Nina", "Neu", "Teamer", stadt="Gelsenkirchen", lieferantenbewertung=None)

kunde = Kunde(firma="Rheintal Werke GmbH", ansprechpartner="Lisa Muster",
              telefon="0201 123456", email="lisa@rheintal.example",
              rechnung_email="rechnung@rheintal.example",
              strasse="Werksallee 5", plz="45127", ort="Essen",
              pipeline_status="gebucht", branche="Industrie",
              weitere_ansprechpartner=json.dumps([
                  {"name": "Peter Plan", "telefon": "0151 2223344",
                   "email": "plan@rheintal.example"}]))
s.add(kunde); s.flush()

ev = Event(anlass="Sommerfest", datum=date.today() + timedelta(days=12),
           startzeit="11:00", endzeit="17:00",
           veranstaltungsort="Werksallee 5, 45127 Essen",
           kunde_firma="Rheintal Werke GmbH", kunde_kontakt="Lisa Muster",
           kunde_telefon="0201 123456", kunde_email="lisa@rheintal.example",
           kunde_adresse="Werksallee 5, 45127 Essen", kunde_id=kunde.id,
           produkte="Kinderschminken, Bastelaktion", anzahl_teamer=2, anzahl_kuenstler=1,
           marke="Kindsalabim", status="Checkliste eingegangen",
           material_mitnahme=True, checklist_token="handbuch-checkliste",
           teamleiter_id=lisa.id, logistiker_id=tom.id,
           cl_eingereicht_am="05.08.2026 14:12", cl_ansprechpartner_name="Lisa Muster",
           cl_ansprechpartner_mobil="0170 555444", cl_firma_name="Rheintal Werke GmbH",
           cl_strasse="Werksallee 5", cl_plz_ort="45127 Essen",
           cl_aufbau_von="09:30", cl_aufbau_bis="10:30",
           cl_abbau_von="17:00", cl_abbau_bis="18:00",
           cl_aufbauort="Outdoor, Überdacht", cl_verpflegung="Ja", cl_teamkleidung="Ja",
           cl_parkplatz="Parkplatz P2 direkt am Werkstor",
           cl_rechnung_firma="Rheintal Holding GmbH & Co. KG",
           cl_rechnung_strasse="Rechnungsweg 1", cl_rechnung_plz_ort="45127 Essen",
           cl_rechnung_email="rechnung@rheintal.example")
s.add(ev); s.flush()

ev2 = Event(anlass="Kindergeburtstag", datum=date.today() + timedelta(days=9),
            startzeit="14:00", endzeit="17:00",
            veranstaltungsort="Musterweg 3, 45889 Gelsenkirchen",
            kunde_firma="Familie Beispiel", kunde_kontakt="Anna Beispiel",
            kunde_telefon="0170 9998877", kunde_email="anna@beispiel.example",
            produkte="Zaubershow", anzahl_teamer=1, anzahl_kuenstler=1,
            marke="Kindsalabim", status="Gebucht", privatkunde=True,
            checklist_token="handbuch-checkliste-offen")
s.add(ev2); s.flush()

def anfrage(event, d, status, rolle, **kw):
    s.add(Verfuegbarkeitsanfrage(event_id=event.id, dienstleister_id=d.id,
                                 rolle_anfrage=rolle, status=status,
                                 erstellt_am="01.08.2026 10:00", **kw))

anfrage(ev, lisa, "Ja", "Teamer")
anfrage(ev, tom, "Ja", "Teamer", als_logistiker=True)
anfrage(ev, mia, "Ja", "Künstler", budget=290.0)
anfrage(ev, ziad, "Abgelaufen", "Künstler", frist_datum=date.today() - timedelta(days=2))
anfrage(ev, nina, "Ausstehend", "Teamer", frist_datum=date.today() + timedelta(days=2))
anfrage(ev2, lisa, "Ausstehend", "Teamer", frist_datum=date.today() + timedelta(days=3))

for bez, betrag in [("Baker Ross Bastelsets (Bestellung 12.08.)", 123.45),
                    ("Glitzertattoo-Nachschub", 49.90),
                    ("Deko & Tischdecken", 26.55)]:
    s.add(EventBestellung(event_id=ev.id, bezeichnung=bez, betrag=betrag,
                          erstellt_am=datetime.now().isoformat(timespec="seconds")))

s.add(Reservierung(datum=date.today() + timedelta(days=25), startzeit="14:00", endzeit="18:00",
                   art="Z", anlass="Firmenjubiläum", veranstaltungsort="50667 Köln",
                   kunde_firma="Beispiel & Söhne KG", kunde_kontakt="Hr. Beispiel",
                   marke="Kindsalabim", frist=date.today() + timedelta(days=4),
                   serien_id="handbuch-serie"))
s.add(Reservierung(datum=date.today() + timedelta(days=26), startzeit="10:00", endzeit="13:00",
                   art="Z", anlass="Firmenjubiläum", veranstaltungsort="50667 Köln",
                   kunde_firma="Beispiel & Söhne KG", kunde_kontakt="Hr. Beispiel",
                   marke="Kindsalabim", frist=date.today() + timedelta(days=4),
                   serien_id="handbuch-serie"))
s.add(Reservierung(datum=date.today() + timedelta(days=40), art="WORKSHOP",
                   anlass="Ferienprogramm", veranstaltungsort="45127 Essen",
                   kunde_firma="Stadt Musterhausen", marke="Kindsalabim",
                   frist=date.today() - timedelta(days=1)))

s.add(Rechnung(datum=date.today() - timedelta(days=40), kunde="Rheintal Werke GmbH",
               rgnr="RE-2026-089", brutto=1547.00, bezahlt=True,
               personalkosten=420.0, materialkosten=180.0))
s.add(Rechnung(datum=date.today() - timedelta(days=9), kunde="Familie Sommer",
               rgnr="RE-2026-101", brutto=830.00, bezahlt=True, personalkosten=250.0))
s.add(Rechnung(datum=date.today() - timedelta(days=4), kunde="Beispiel & Söhne KG",
               rgnr="RE-2026-102", brutto=1190.00, bezahlt=False,
               personalkosten=380.0, materialkosten=199.90))

for typ, titel, text in [
    ("dl_zusage", "Zusage: Mia Farben – Sommerfest",
     "Mia Farben hat für Sommerfest am %s zugesagt." % (date.today() + timedelta(days=12)).strftime("%d.%m.%Y")),
    ("checkliste", "Checkliste zurück: Rheintal Werke GmbH",
     "Rheintal Werke GmbH hat die Checkliste für Sommerfest ausgefüllt."),
    ("rechnung_erinnerung", "Vorkasse-Rechnung senden: Familie Beispiel",
     "Privatkunde: Die Rechnung für Kindergeburtstag soll 14 Tage vorher verschickt werden (Vorkasse)."),
]:
    s.add(Benachrichtigung(typ=typ, titel=titel, text=text,
                           erstellt_am=datetime.now().isoformat(timespec="seconds")))

s.commit()
EV1, LISA_ID = ev.id, lisa.id
s.close()

# ── 3. Server starten (Thread) + Login-Umgehung nur für die Sandbox ──────────
main.app.dependency_overrides[get_admin_user] = lambda: {"sub": "handbuch@local", "role": "admin"}
main.app.dependency_overrides[get_portal_user] = lambda: {"sub": str(LISA_ID), "role": "dienstleister"}

import uvicorn                                              # noqa: E402
server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(60):
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/admin/dashboard", timeout=1)
        break
    except Exception:
        time.sleep(0.5)

# ── 4. Screenshots (Chrome headless) ─────────────────────────────────────────
CHROME_KANDIDATEN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CHROME = next((c for c in CHROME_KANDIDATEN if os.path.exists(c)), None)
if not CHROME:
    print("FEHLER: Chrome nicht gefunden – Screenshots übersprungen."); sys.exit(1)

# (Dateiname, URL, Fensterbreite, Aufnahmehöhe)
SEITEN = [
    ("dashboard",        f"http://127.0.0.1:{PORT}/admin/dashboard",        1000, 2400),
    ("event_neu",        f"http://127.0.0.1:{PORT}/admin/events/new",       1000, 3400),
    ("event_detail",     f"http://127.0.0.1:{PORT}/admin/events/{EV1}",     1000, 5200),
    ("reservierungen",   f"http://127.0.0.1:{PORT}/admin/reservierungen",   1000, 1700),
    ("dienstleister",    f"http://127.0.0.1:{PORT}/admin/dienstleister",    1200, 1500),
    ("crm",              f"http://127.0.0.1:{PORT}/admin/crm/1",            1000, 1700),
    ("buchhaltung",      f"http://127.0.0.1:{PORT}/admin/buchhaltung",      1200, 1800),
    ("benachricht",      f"http://127.0.0.1:{PORT}/admin/benachrichtigungen", 1000, 1400),
    ("angebot",          f"http://127.0.0.1:{PORT}/admin/angebot",          1000, 1800),
    ("checkliste",       f"http://127.0.0.1:{PORT}/checklist/handbuch-checkliste-offen", 560, 3400),
    ("portal",           f"http://127.0.0.1:{PORT}/portal",                 520, 2200),
    ("portal_profil",    f"http://127.0.0.1:{PORT}/portal/profil",          520, 2800),
]
for name, url, w, h in SEITEN:
    out = os.path.join(SHOTS, f"{name}.png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=6000",   # warten bis CSS/Fonts geladen sind
                    f"--window-size={w},{h}", f"--screenshot={out}", url],
                   capture_output=True, timeout=90)
    print("Screenshot:", name)

server.should_exit = True

# ── 5. Screenshots zuschneiden: Leerraum unten weg, lange Seiten in Häppchen ──
from PIL import Image as PILImage                           # noqa: E402

def trim_und_teile(name, max_slice=1250, min_rest=350):
    """Schneidet unteren Leerraum ab und teilt hohe Screenshots in PDF-taugliche
    Abschnitte. Gibt Liste der Teil-Dateien zurück."""
    pfad = os.path.join(SHOTS, f"{name}.png")
    im = PILImage.open(pfad).convert("RGB")
    w, h = im.size
    # Leerraum unten: alle Zeilen, die (rechts der Sidebar, x >= 260) exakt so
    # aussehen wie die unterste Zeile, gehören zum Leerraum. Die Sidebar wird
    # ignoriert, weil unten links dauerhaft „Abmelden" steht.
    x0 = 260 if w > 700 else 0
    boden = im.crop((x0, h - 1, w, h)).tobytes()
    unten = h
    y = h - 2
    while y > 200:
        if im.crop((x0, y, w, y + 1)).tobytes() != boden:
            unten = min(h, y + 32)
            break
        y -= 4
    im = im.crop((0, 0, w, unten))
    teile = []
    y = 0
    n = 0
    while y < im.height:
        rest = im.height - y
        hoehe = rest if rest <= max_slice + min_rest else max_slice
        teil = im.crop((0, y, w, y + hoehe))
        tp = os.path.join(SHOTS, f"{name}_{n}.png")
        teil.save(tp)
        teile.append(tp)
        y += hoehe
        n += 1
    return teile

TEILE = {name: trim_und_teile(name) for name, *_ in SEITEN}

# ── 6. PDF bauen ─────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4                       # noqa: E402
from reportlab.lib.units import mm                           # noqa: E402
from reportlab.lib.colors import HexColor                    # noqa: E402
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                ListFlowable, ListItem, Image, PageBreak)  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle       # noqa: E402

BLAU = HexColor("#1D4E89"); GRAU = HexColor("#6b7280"); HELL = HexColor("#eef3fb")
RAND = HexColor("#d7e0ee")
styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=22, textColor=BLAU, spaceAfter=2, alignment=0)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=10.5, textColor=GRAU, spaceAfter=12)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, textColor=BLAU, spaceBefore=14, spaceAfter=5)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11.5, textColor=HexColor("#111827"), spaceBefore=8, spaceAfter=3)
P = ParagraphStyle("P", parent=styles["Normal"], fontSize=10.5, leading=15, spaceAfter=6)
LI = ParagraphStyle("LI", parent=P, spaceAfter=3)
CAP = ParagraphStyle("CAP", parent=styles["Normal"], fontSize=8.5, textColor=GRAU, spaceBefore=2, spaceAfter=10)
BOX = ParagraphStyle("BOX", parent=P, textColor=HexColor("#374151"), fontSize=10, leading=14)
TOC = ParagraphStyle("TOC", parent=P, fontSize=10.5, leading=17, spaceAfter=0)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(t, LI), leftIndent=12) for t in items],
                        bulletType="bullet", start="•", leftIndent=14, spaceAfter=6)


def shot(pfad, w_mm, caption=""):
    iw, ih = PILImage.open(pfad).size
    w = w_mm * mm
    hoehe = w * ih / iw
    img = Image(pfad, width=w, height=hoehe)
    t = Table([[img]], colWidths=[w + 6])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, RAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    out = [t]
    if caption:
        out.append(Paragraph(caption, CAP))
    else:
        out.append(Spacer(1, 6))
    return out


def shots(name, w_mm, caption=""):
    out = []
    for i, teil in enumerate(TEILE[name]):
        out += shot(teil, w_mm, caption if i == len(TEILE[name]) - 1 else "")
    return out


def hinweis(text):
    t = Table([[Paragraph(text, BOX)]], colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HELL), ("BOX", (0, 0), (-1, -1), 0.75, BLAU),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def tabelle(kopf, zeilen, breiten=None):
    daten = [[Paragraph(f"<b>{z}</b>", LI) for z in kopf]] + \
            [[Paragraph(z, LI) for z in reihe] for reihe in zeilen]
    t = Table(daten, colWidths=breiten)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HELL),
        ("GRID", (0, 0), (-1, -1), 0.5, RAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


stand = date.today().strftime("%d.%m.%Y")
doc = SimpleDocTemplate(PDF_OUT, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                        topMargin=16*mm, bottomMargin=16*mm,
                        title="Kindsalabim Events-App – Admin-Handbuch")

KAPITEL = [
    "1. Was die App ist & Anmeldung", "2. Das Dashboard", "3. Ein Event anlegen",
    "4. Die Event-Seite: der Workflow", "5. Die Kunden-Checkliste",
    "6. Team zusammenstellen (Verfügbarkeitsanfragen)", "7. Bestellungen & Material",
    "8. Briefing & Dienstleister-Portal", "9. Nach dem Event", "10. Reservierungen",
    "11. Dienstleister verwalten", "12. Kunden (CRM)", "13. Buchhaltung",
    "14. Angebot-PDF & Bastel-Recherche", "15. Was die App automatisch macht",
    "16. Benachrichtigungen & Einstellungen", "17. Weitere Bereiche & Sicherheitsnetz",
]

story = [
    Paragraph("Events-App: Admin-Handbuch", H1),
    Paragraph(f"Komplette Einführung für neue Admins · Kindsalabim &amp; Knallfrosch · Stand {stand} · "
              "Screenshots aus der App (Beispieldaten)", SUB),
    hinweis("<b>Die App in einem Satz:</b> Sie begleitet jedes Event von der Buchung bis zur Rechnung – "
            "Kunde, Team, Material, Briefing, Bericht – und erinnert automatisch an alles, was sonst "
            "vergessen wird."),
    Spacer(1, 8),
    Paragraph("Inhalt", H2),
    *[Paragraph(k, TOC) for k in KAPITEL],
    PageBreak(),

    Paragraph("1. Was die App ist &amp; Anmeldung", H2),
    bullets([
        "Adresse: <b>kindsalabim-events.onrender.com</b> – läuft im Browser, auch am Handy.",
        "Anmeldung unter <b>/admin/login</b> mit deinem Admin-Zugang (anlegen/verwalten unter "
        "&bdquo;Admin-Zugänge&ldquo;). Die Sitzung hält 30 Tage.",
        "Zwei Marken: <b>Kindsalabim</b> (blau) und <b>Knallfrosch</b> (grün) – die Marke wird pro "
        "Event/Reservierung gewählt und färbt Mails, Briefings und Kalender-Einträge.",
        "Dienstleister haben eine eigene Ansicht (<b>Portal</b>, Kapitel 8) – sie sehen nie interne Daten.",
    ]),

    Paragraph("2. Das Dashboard", H2),
    Paragraph("Startseite nach dem Login: kommende Events mit Status, Schnellzugriff auf Reservierungen "
              "und alles Dringende. Die <b>Glocke</b> oben zeigt neue Ereignisse (Zusagen, Absagen, "
              "Checklisten, Erinnerungen – Kapitel 16).", P),
    *shots("dashboard", 150, "Dashboard mit Event-Liste und Seitennavigation."),

    Paragraph("3. Ein Event anlegen", H2),
    Paragraph("<b>Neues Event</b> in der Seitenleiste. Das Formular von oben nach unten:", P),
    bullets([
        "<b>Marke &amp; Grunddaten:</b> Anlass, Datum, Uhrzeit. Unter <b>&bdquo;Weitere Aktionstage&ldquo;</b> "
        "lassen sich weitere Tage desselben Auftrags anlegen (Termin-Serie) – auch Wochen oder Monate "
        "auseinander. Jeder Tag wird ein eigenes, verknüpftes Event.",
        "<b>Kundendaten (intern):</b> Wer hat gebucht – erscheint nie im Briefing. Bekannte Kunden werden "
        "beim Tippen vorgeschlagen und Adresse/Kontakt automatisch übernommen. Häkchen "
        "<b>&bdquo;Privatkunde (Vorkasse)&ldquo;</b>: App erinnert 14 Tage vor dem Event an die Vorkasse-Rechnung. "
        "&bdquo;Mit Kundenprofil im CRM verknüpfen&ldquo; baut die Kundenhistorie auf.",
        "<b>Veranstaltung vor Ort:</b> Veranstaltungsadresse (falls abweichend), Ansprechpartner vor Ort, "
        "<b>&bdquo;+ weitere Ansprechpartner&ldquo;</b> (erscheinen im Briefing), Ankunfts-Vorlauf und Treffpunkt.",
        "<b>Produkte &amp; Personal:</b> gebuchte Aktionen ankreuzen (bestimmen Künstler-Sparte und "
        "Ankunfts-Vorlauf), Anzahl Teamer/Künstler, Material-Mitnahme (steuert Logistiker &amp; Erinnerungen).",
        "<b>Zaubershow-Event:</b> Sonderfall ohne Team/Checkliste/Bericht – schließt allein über die Rechnung ab.",
    ]),
    *shots("event_neu", 150, "Neues Event anlegen: Grunddaten, Kundendaten mit Privatkunde-Häkchen, vor Ort, Produkte."),

    PageBreak(),
    Paragraph("4. Die Event-Seite: der Workflow", H2),
    Paragraph("Jedes Event hat eine Seite mit allem Drum und Dran. Die <b>Chevron-Leiste</b> oben zeigt die "
              "fünf Stationen – Klick springt zum passenden Abschnitt:", P),
    bullets([
        "<b>Checkliste</b> → an den Kunden senden, Angaben kommen automatisch zurück (Kapitel 5).",
        "<b>Verfügbarkeit</b> → Team anfragen, bis &bdquo;Team komplett&ldquo; (Kapitel 6).",
        "<b>Bestellungen</b> → Material bestellen und Kosten erfassen (Kapitel 7).",
        "<b>Briefing</b> → alle Infos ans bestätigte Team (Kapitel 8).",
        "<b>Abschluss</b> → Eventbericht + Rechnung; vieles schließt automatisch (Kapitel 9).",
        "Oben rechts: <b>Bearbeiten</b>, <b>Kopieren</b> (füllt ein neues Event mit allen Stammdaten vor – "
        "ideal für Stammkunden, die jedes Jahr buchen) und dezent <b>Löschen</b> (landet im Papierkorb).",
        "Abgeschlossene/abgesagte Events sind gegen versehentliche Änderungen <b>gesperrt</b> – "
        "&bdquo;Bearbeitung entsperren&ldquo; hebt das gezielt auf.",
    ]),
    *shots("event_detail", 150, "Event-Seite: Workflow-Leiste, Karten, Bestellungen, Team-Anfragen, Briefing, Abschluss."),

    PageBreak(),
    Paragraph("5. Die Kunden-Checkliste", H2),
    bullets([
        "Im Event-Abschnitt &bdquo;Kunden-Angaben&ldquo;: <b>Checkliste senden</b> (blauer Knopf) – der Kunde "
        "bekommt einen persönlichen Link, ohne Login. &bdquo;Link ansehen&ldquo; zeigt denselben Link zum "
        "Selbst-Verschicken (z. B. WhatsApp).",
        "<b>Vorab ausfüllen erlaubt:</b> Was du über &bdquo;Briefing bearbeiten&ldquo; schon einträgst, sieht "
        "der Kunde <b>vorbefüllt</b> und muss es nur prüfen/ergänzen. &bdquo;(Erneut) senden&ldquo; öffnet "
        "eine bereits ausgefüllte Checkliste wieder, ohne dass Angaben verloren gehen. "
        "Ausnahme: <b>&bdquo;Weitere Details&ldquo;</b> ist für interne Team-Notizen – die sieht der Kunde "
        "NIE; seine eigene Eingabe wird darunter angehängt.",
        "Der Kunde füllt aus: Ansprechpartner vor Ort, Veranstaltungsanschrift, Auf-/Abbauzeiten "
        "(inkl. <b>Anlieferung am Vortag / Abholung am Folgetag</b> mit Zeitfenster und Bedingungs-"
        "Freitext), Aufbauort, Verpflegung, Teamkleidung, Parkplatz – und zum Schluss "
        "<b>&bdquo;Für die Rechnung&ldquo;</b> (abweichende Firmierung/Adresse/E-Mail – beugt nachträglichen "
        "Rechnungskorrekturen vor).",
        "Ein <b>Fortschrittsbalken</b> (&bdquo;X von 8 Abschnitten ausgefüllt&ldquo;, ca. 2 Minuten) und "
        "Häkchen je Karte führen den Kunden durch – vorbefüllte Karten zählen erst, wenn er sie "
        "beim Scrollen gesehen hat.",
        "Nach dem Absenden: Glocke + Status &bdquo;Checkliste eingegangen&ldquo;; die Angaben stehen im Event "
        "und fließen automatisch ins Briefing. Die Rechnungs-Mail wandert in die Kundenkartei.",
        "Für Stammkunden: Häkchen &bdquo;Keine Kunden-Checkliste nötig&ldquo; im Event-Formular überspringt "
        "den Schritt komplett.",
    ]),
    *shots("checkliste", 95, "Die öffentliche Kunden-Checkliste (Handy-Ansicht) – unten die Karte „Für die Rechnung“."),

    PageBreak(),
    Paragraph("6. Team zusammenstellen (Verfügbarkeitsanfragen)", H2),
    bullets([
        "Im Event unter <b>&bdquo;+ Verfügbarkeitsanfragen senden&ldquo;</b>: getrennte Listen für Teamer und "
        "Künstler. <b>Sortierung = Empfehlung</b>: Entfernung, Bewertung (⭐), Logistik, Erfahrung – plus "
        "<b>+15 Stammkunden-Bonus</b> (🤝 &bdquo;N× bei diesem Kunden im Einsatz&ldquo;). Nicht Verfügbare "
        "(Sperrzeit/schon gebucht) rutschen ans Ende.",
        "<b>Suchzeile</b> (&bdquo;Name eintippen zum Filtern&ldquo;) und bei Künstlern <b>Sparten-Chips</b> "
        "(Kinderschminke, Ballon, Showact …).",
        "Anfrage per Mail mit Magic-Link – der Dienstleister sagt im Portal zu oder ab (mit Frist; "
        "Verlängerung +2 Tage möglich). Bei Termin-Serien: eine Mail für alle Tage, Zusage pro Tag.",
        "<b>Künstler-Budget:</b> optional je Anfrage; liegt eine Auftragsbestätigung am Event, schlägt die "
        "App das Budget automatisch vor (Netto-Position × 80 %, auf 10er gerundet).",
        "<b>Direkt eintragen</b> (ohne Mail) für telefonisch Vereinbartes; <b>Einmal-Teamer (extern)</b> "
        "beim Briefing für Agentur-Personal.",
        "Zugesagte erscheinen mit Häkchen; dort <b>Teamleitung</b> und (bei Material) <b>Logistiker</b> "
        "zuweisen. Bei Lücken macht die App einen <b>1-Klick-Nachbesetzungs-Vorschlag</b>.",
        "<b>Platzvergabe läuft automatisch</b> – niemand muss prüfen, ob eine Zusage noch passt: "
        "Ist das Team für die Rolle bereits voll, lehnt die App die Zusage selbst ab. Nach "
        "Fristablauf gilt zusätzlich der Vorrang der Pünktlichen – läuft für dieselbe Rolle noch "
        "eine fristgerechte Anfrage, kommt die verspätete Zusage auf die <b>Warteliste</b> "
        "(Kennzeichen in der Rückmeldungstabelle) statt den Platz wegzuschnappen. Ist zufällig noch "
        "ein Platz frei und niemand anderes dran, geht die verspätete Zusage durch – der "
        "Dienstleister bekommt dabei den Hinweis, dass das Glück und kein Normalfall war.",
        "<b>Automatisches Nachrücken:</b> Wird ein Platz frei (Absage oder abgelaufene Frist), "
        "reaktiviert die App die älteste Wartelisten-Anfrage, setzt eine neue Frist (2 Tage) und "
        "verschickt die Anfrage erneut. Nur wenn für die Rolle gar kein Bedarf hinterlegt ist "
        "(z. B. reines Zaubershow-Event), greifen diese Regeln nicht.",
    ]),

    Paragraph("7. Bestellungen &amp; Material", H2),
    bullets([
        "<b>Material-Mitnahme</b> im Event steuert alles Weitere: Logistiker nötig, Bestell-Erinnerung "
        "(3 Wochen vorher), Abhol-Erinnerung an den Logistiker (3 Tage vorher), "
        "&bdquo;Material abholbereit&ldquo;-Meldung.",
        "Karte <b>&bdquo;Bestellungen&ldquo;</b>: jede Bestellung mit Bezeichnung + Betrag erfassen – die Summe "
        "&bdquo;Materialkosten gesamt&ldquo; wird später in der Buchhaltung vorgeschlagen (Kapitel 13).",
        "&bdquo;Als bestellt markieren&ldquo; hakt den Workflow-Schritt ab.",
    ]),

    Paragraph("8. Briefing &amp; Dienstleister-Portal", H2),
    bullets([
        "<b>Briefing senden</b> schickt allen Zugesagten eine Mail mit allen Details (Datum/Ankunft/"
        "Treffpunkt, Team-Liste mit Telefonnummern, Ansprechpartner, Adresse, Regeln) + <b>PDF-Anhang</b> "
        "fürs Handy. &bdquo;Als PDF&ldquo; lädt es zum Weitergeben, &bdquo;Briefing bearbeiten&ldquo; für Korrekturen.",
        "Die Briefing-Regeln (Seite &bdquo;Allgemeines&ldquo;) pflegst du unter Einstellungen.",
        "<b>Kontakt-Rangfolge:</b> Ist eine Teamleitung gesetzt, heißt die Kontaktkarte "
        "&bdquo;Wen du anrufst&ldquo; und nennt die Teamleitung zuerst (&bdquo;Erste Anlaufstelle "
        "für alle Fragen vor Ort&ldquo;), den Kunden darunter mit dem Zusatz, dass er nur "
        "angerufen wird, wenn die Teamleitung nicht erreichbar ist. So ruft niemand aus Reflex "
        "beim Kunden an – die Nummer bleibt aber für den Notfall im Briefing. Ohne Teamleitung "
        "(Ein-Personen-Einsatz) steht dort wie bisher schlicht &bdquo;Ansprechpartner Kunde&ldquo;.",
        "<b>Portal:</b> Dienstleister melden sich per Magic-Link an (E-Mail eintippen → Link kommt per Mail). "
        "Dort: offene Anfragen beantworten, Einsätze sehen, Briefing-PDF laden, Urlaub/Sperrzeiten "
        "eintragen, Profil &amp; Onboarding. Teamleiter reichen dort auch den <b>Eventbericht</b> ein.",
        "<b>Mein Profil (Selbstauskunft):</b> Neue Dienstleister füllen dort selbst Adresse, Telefon, "
        "Kleidergröße, Geburtsdatum, Führerschein, Mobilität sowie Lager-Mitnahme (Rüttenscheid) und "
        "Kastenwagen-Zutrauen aus, bestätigen die <b>DSGVO-Einwilligung online</b> "
        "(beide Firmen in einem Schritt, mit Zeitstempel) und laden ihren <b>Gewerbeschein</b> hoch. "
        "Dazu gibt es dort Downloads: Rechnungsvorlage, Rechnungs-Erläuterung, Kleingewerbe-Infoblatt.",
        "<b>DSGVO-Nachweis:</b> Bei jeder Online-Einwilligung geht automatisch ein <b>Nachweis-PDF</b> "
        "(Text, Name, Zeitstempel, IP) per Mail ans Büro und als Kopie an den Dienstleister; "
        "zusätzlich ist es jederzeit über die Dienstleisterkarte abrufbar.",
        "<b>Einkaufs-AGB:</b> Die Vertragsbedingungen (Stand 03.03.2025, beide Firmen) sind unter "
        "Portal → AGB jederzeit einsehbar und werden im Profil per Häkchen bestätigt (Zeitstempel + "
        "IP als Nachweis). Bestandsdienstleister erreicht der Knopf „AGB-Bestätigung anfordern“ "
        "in der Dienstleister-Liste.",
        "<b>Zusage-Sperre:</b> Ohne DSGVO-Einwilligung + Gewerbeschein kann ein Dienstleister keine "
        "Jobs annehmen (Absagen geht immer). Das Portal zeigt ihm dauerhaft einen Hinweis; zusätzlich "
        "erinnert ihn die App wöchentlich per Mail an den fehlenden Gewerbeschein.",
    ]),
    *shots("portal", 90, "Dienstleister-Portal (Handy): offene Anfragen und Einsätze."),
    *shots("portal_profil", 90, "„Mein Profil“ im Portal: Selbstauskunft, DSGVO-Einwilligung, Gewerbeschein, Vorlagen."),

    PageBreak(),
    Paragraph("9. Nach dem Event", H2),
    bullets([
        "<b>Eventbericht:</b> Der Teamleiter wird ab 2 h nach Event-Ende automatisch erinnert (dann alle "
        "3 Tage) und füllt den Bericht im Portal aus – Kinderzahl, Verlauf, Kundenfeedback, Fotos. "
        "Alles landet am Event und im CRM-Profil des Kunden.",
        "<b>Rechnung:</b> Im Abschluss-Bereich &bdquo;Als gestellt markieren&ldquo; (bei Serien wahlweise für "
        "alle Termine oder nur diesen Tag). Erinnerungen: Vorkasse 14 Tage vorher (Privatkunde), "
        "spezielle Rechnungs-Mail/Firmierung nach dem Event.",
        "<b>Automatischer Abschluss:</b> Bericht eingereicht + Rechnung gestellt → Status "
        "&bdquo;Abgeschlossen&ldquo; (Zaubershow: Rechnung allein genügt).",
    ]),

    Paragraph("10. Reservierungen", H2),
    bullets([
        "Unverbindliche Termin-Holds vor der Buchung – getrennt von echten Events. Mit Frist "
        "(&bdquo;Rückmeldung bis&ldquo;, vorbelegt heute + 5 Tage), Art-Kürzel (Z/B/ZB/WORKSHOP/Div.) und "
        "Kunden-Autofill wie im Event-Formular.",
        "Im Google-Kalender: <b>anthraziter</b> Block; nach Fristablauf färbt er sich automatisch "
        "<b>flamingo</b> und die Reservierung wandert in der App ins Dropdown &bdquo;Abgelaufene "
        "Reservierungen&ldquo;.",
        "<b>Mehrtägige Reservierung:</b> Im Neu-Formular unter &bdquo;Weitere Termintage&ldquo; beliebig "
        "viele Tage ergänzen (jeder mit eigener Uhrzeit, sonst gilt die des Haupttags). Jeder Tag bekommt "
        "seinen eigenen Kalender-Block; die Karten tragen die Markierung &bdquo;Serie&ldquo;.",
        "<b>In Buchung umwandeln</b> macht mit einem Klick ein echtes Event daraus – bei einer Serie werden "
        "alle Tage zusammen zu einer Termin-Serie (nicht gebuchte Tage vorher löschen). Ist der reservierte "
        "Tag vorbei, löscht die App den Eintrag automatisch (der Kalender-Block bleibt).",
        "<b>Kopieren</b> an der Karte befüllt das Neu-Formular mit allen Daten der Reservierung vor – "
        "nur der Termin bleibt leer.",
    ]),
    *shots("reservierungen", 150, "Reservierungen: aktive Liste, Neu-Formular, abgelaufene im Dropdown."),

    PageBreak(),
    Paragraph("11. Dienstleister verwalten", H2),
    bullets([
        "Liste aller Teamer/Künstler mit Rolle, Sparte, <b>interner Lieferantenbewertung (★ 1–10)</b>, "
        "Logistiker-/Führerschein-Häkchen, T-Shirt-Größen, DSGVO-Status. Name und Aktions-Knöpfe "
        "bleiben beim Scrollen sichtbar. Die Bewertung ersetzt die früheren Erfahrungspunkte + "
        "5-Sterne-Qualität (alte Sterne wurden ×2 übernommen), fließt ins Empfehlungs-Ranking ein "
        "und ist für Dienstleister nie sichtbar; die Zahl bisheriger Aufträge zeigt die Karte "
        "automatisch aus der Anfrage-Historie.",
        "<b>Aktiv</b>-Häkchen steuert, ob jemand anfragbar ist und sich einloggen kann. "
        "<b>Wichtig:</b> Der Portal-Login läuft NUR über Magic-Link (kein Passwort) – die hinterlegte "
        "E-Mail-Adresse muss stimmen (Groß-/Kleinschreibung ist egal). Landet jemand versehentlich "
        "auf der Admin-Login-Seite, zeigt ein Wegweiser zum Portal; &bdquo;Passwort vergessen&ldquo; "
        "schickt Dienstleistern automatisch ihren Portal-Anmeldelink.",
        "<b>Neue Dienstleister anlegen ist jetzt minimal:</b> Name + E-Mail eintragen, &bdquo;Einladen&ldquo; "
        "klicken – den Rest (Adresse, Kleidergröße, DSGVO, Gewerbeschein) erledigt die Person selbst im "
        "Portal-Onboarding. Du bekommst eine Glocke, sobald etwas ausgefüllt/hochgeladen wurde, und "
        "ergänzt nur noch EP, Qualität &amp; Co.",
        "<b>Geburtsdatum:</b> freiwillige Angabe (im Portal-Profil oder im Admin-Formular). Die Karte "
        "zeigt Datum und Alter; am Geburtstag selbst kommt automatisch eine Glocke – gedacht als "
        "Anstoß, kurz zu gratulieren.",
        "<b>Gewerbeschein-Status:</b> In der Detailansicht siehst du DSGVO- und Gewerbeschein-Status "
        "(hochgeladene Scheine per Klick ansehen). Das Formular-Häkchen &bdquo;Gewerbeschein liegt vor&ldquo; "
        "ist für Bestandsdienstleister mit Papier-Kopie im Büro – es hebt Sperre und Erinnerung auf. "
        "Alle Bestandsdienstleister wurden beim Update automatisch so markiert.",
        "Urlaub/Sperrzeiten pflegen Dienstleister selbst im Portal – gesperrte Personen rutschen in den "
        "Anfrage-Listen automatisch nach unten.",
        "<b>Scheinselbstständigkeits-Vorsorge in der Karte:</b> Das interne <b>Status-Scoring</b> "
        "(Anwalts-System, Ampel 🟢/🟡/🔴, ab 130 Punkten kritisch) bewertet jeden Dienstleister in "
        "ca. 2 Minuten. Das <b>Nachweis-Dossier</b> (PDF-Knopf in der Karte) dokumentiert für den "
        "Prüfungsfall die freie Auftragsannahme: alle angebotenen, angenommenen und abgelehnten "
        "Anfragen, Fristverlängerungen, Sperrzeiten und Unterlagen-Status.",
    ]),
    *shots("dienstleister", 160, "Dienstleister-Liste (volle Breite, Name und Knöpfe bleiben fixiert)."),

    Paragraph("12. Kunden (CRM)", H2),
    bullets([
        "Ein Profil je Kunde: Kontakt, <b>Rechnungs-E-Mail</b>, <b>weitere Ansprechpartner</b> (mit Telefon/"
        "E-Mail, erscheinen im Event-Formular als Klick-Vorschläge), Tags, Pipeline-Status, Notizen/"
        "Profilwissen, <b>Wiedervorlagen</b> (tägliche Sammel-Mail bei Fälligkeit), Aktivitäten, "
        "Eventhistorie und eingereichte Eventberichte.",
        "Events verknüpfst du beim Anlegen (Häkchen &bdquo;Mit Kundenprofil verknüpfen&ldquo;) – so entsteht "
        "die Historie für den Stammkunden-Bonus und die Rechnungs-Erinnerungen.",
    ]),
    *shots("crm", 150, "Kundenprofil: Kontakt (mit Rechnungs-Kachel), Wiedervorlagen, Aktivitäten, Eventhistorie."),

    PageBreak(),
    Paragraph("Marken-Ansicht (persönlich je Admin)", H2),
    bullets([
        "Über den Umschalter oben im Dashboard (oder unter Einstellungen) wählt <b>jeder Admin "
        "für sich</b>: beide Marken, nur Kindsalabim oder nur Knallfrosch.",
        "Die Auswahl wirkt auf <b>Events, Kalender, Kennzahlen, Reservierungen, Buchhaltung "
        "(inkl. Summen und CSV-Export), Glocke und alle Benachrichtigungs-E-Mails</b>. "
        "Allgemeine Meldungen ohne Marke (z. B. Urlaub eines Teamers) kommen weiterhin bei allen an.",
        "Hintergrund: Knallfrosch ist eine GbR mit Geschäftspartner, Kindsalabim ein "
        "Einzelunternehmen – so muss niemand Meldungen und Zahlen der jeweils anderen Firma sehen. "
        "Es ist eine Ansichts-Einstellung, keine Sperre: Jeder kann sie jederzeit selbst ändern.",
        "Jede <b>Rechnung hat eine Marke</b> (Auswahl im Formular). Beim Update wurden bestehende "
        "Rechnungen automatisch zugeordnet (über die Events/Kunden desselben Namens), der Rest "
        "läuft auf Kindsalabim – bitte einmal prüfen und ggf. beim Bearbeiten korrigieren.",
    ]),

    Paragraph("13. Buchhaltung", H2),
    bullets([
        "Alle Rechnungen nach Monaten gruppiert, mit Jahres-Summen (Brutto, offen, Personal-/Material"
        "kosten, MwSt., Netto, Gewinn, Steuerrücklage, Invest). Werte in der Tabelle sind per Klick "
        "direkt editierbar.",
        "<b>Neue Rechnung:</b> oben &bdquo;Aus Event übernehmen&ldquo; wählen → Kunde und Materialkosten "
        "werden aus den erfassten Bestellungen vorbefüllt.",
        "<b>Bezahlt-Haken</b> pro Rechnung. Unbezahlte Rechnungen nach Zahlungsziel (14 Werktage) melden "
        "sich wöchentlich per Glocke + Mail, bis der Haken gesetzt ist.",
        "CSV-Export für die Steuerberatung über &bdquo;Export&ldquo;.",
    ]),
    *shots("buchhaltung", 160, "Buchhaltung: Monatsgruppen, Jahres-Summen, Neue-Rechnung-Formular per Knopf."),

    Paragraph("14. Angebot-PDF &amp; Bastel-Recherche", H2),
    bullets([
        "<b>Angebot PDF:</b> baut in Minuten ein Bildmaterial-Angebot – Marke wählen, Aktionen ankreuzen, "
        "individuelle Seiten mit Titel + Fotos ergänzen, fertig ist das mailbare PDF (wird automatisch "
        "verkleinert). Aus einem Event heraus geöffnet, sind angedockte Bastelsets schon vorbefüllt.",
        "<b>Bastel-Recherche:</b> Motto eingeben (z. B. &bdquo;Herbst&ldquo;) → passende Baker-Ross-Bastelsets "
        "mit BR-Preis und kalkuliertem Kundenpreis (Aufschlag einstellbar). Katalog aktualisiert "
        "sich montags automatisch.",
        "Sets lassen sich an ein <b>gebuchtes Event ODER eine Reservierung</b> andocken – Angebote "
        "entstehen ja meist vor der Buchung. Wird die Reservierung später in eine Buchung "
        "umgewandelt, wandern die Sets automatisch ans neue Event.",
        "Das <b>Ergebnis bleibt gespeichert</b>: Nach einem Ausflug ins Dashboard steht die letzte "
        "Recherche noch da (mit Datum und Knopf &bdquo;Ergebnis verwerfen&ldquo;) – kein erneutes Suchen nötig.",
        "Aus dem Event bzw. der Reservierung heraus <b>&bdquo;Angebot bauen&ldquo;</b> anklicken: Die angedockten "
        "Sets stehen dann samt Bild automatisch als individuelle Seiten im Angebots-Generator "
        "(Bilder werden direkt von Baker Ross geladen, kein manueller Download nötig).",
    ]),
    *shots("angebot", 150, "Angebots-Generator: Marke, Aktionen, individuelle Seiten."),

    PageBreak(),
    Paragraph("15. Was die App automatisch macht", H2),
    Paragraph("Läuft täglich im Hintergrund – niemand muss daran denken:", P),
    tabelle(["Wann", "Was passiert"], [
        ["24 h vor Anfrage-Frist", "Erinnerung an Dienstleister, die noch nicht geantwortet haben"],
        ["Frist abgelaufen", "Anfrage wird als „Abgelaufen“ markiert + Glocke mit Nachbesetzungs-Vorschlag; Wartende rücken automatisch nach"],
        ["3 Wochen vor Event", "Material-Bestell-Erinnerung (wenn Material nötig, noch nicht bestellt)"],
        ["14 Tage vor Event", "Vorkasse-Rechnung senden (nur Privatkunden)"],
        ["1 Woche vor Event", "Info-Mail an den Kunden mit der Teamleitung als Ansprechpartner"],
        ["3 Tage vor Event", "Material-Abhol-Erinnerung an den Logistiker"],
        ["2 Tage vor Event", "Einsatz-Erinnerung an alle Zugesagten"],
        ["2 h nach Event-Ende", "Bericht-Erinnerung an den Teamleiter (danach alle 3 Tage)"],
        ["Tag nach dem Event", "Erinnerung bei spezieller Rechnungs-Mail/Firmierung des Kunden"],
        ["Zahlungsziel überschritten", "Rechnung-überfällig-Meldung, wöchentlich bis „bezahlt“"],
        ["Täglich", "Abgelaufene Reservierungen: Kalender → flamingo; vergangene werden aufgeräumt"],
        ["Wöchentlich", "Gewerbeschein-Erinnerung an neue Dienstleister, bis der Schein hochgeladen ist"],
        ["Bei jeder Zusage", "Automatische „Bestellung“ (PDF nach Anwaltsvorlage) an den Dienstleister – nur wenn Stundensatz/Budget hinterlegt, sonst Hinweis-Glocke"],
        ["Jährlich", "Erinnerung, das Scheinselbstständigkeits-Scoring der Dienstleister zu aktualisieren"],
        ["Am Geburtstag", "Glocke, wenn ein aktiver Dienstleister Geburtstag hat (nur wenn er sein Geburtsdatum angegeben hat)"],
        ["Montags", "Baker-Ross-Katalog aktualisieren + CSV-Backup-Mail (Events, Dienstleister, Rechnungen, Kunden)"],
    ], breiten=[48*mm, None]),
    Spacer(1, 6),
    Paragraph("Alle Meldungen erscheinen als <b>Glocke</b> in der App; die meisten zusätzlich als Mail "
              "(einzeln abschaltbar unter Einstellungen).", P),

    Paragraph("16. Benachrichtigungen &amp; Einstellungen", H2),
    bullets([
        "<b>Benachrichtigungen</b> (Glocke): chronologischer Verlauf aller Ereignisse mit Direktlink zum "
        "betroffenen Event/Bereich.",
        "<b>Einstellungen:</b> E-Mail-Schalter je Meldungstyp, Briefing-Regeln (Seite &bdquo;Allgemeines&ldquo;), "
        "Baker-Ross-Aufschlag, Telegram-Schalter u. a.",
    ]),
    *shots("benachricht", 150, "Benachrichtigungs-Verlauf (Glocke)."),

    PageBreak(),
    Paragraph("17. Weitere Bereiche &amp; Sicherheitsnetz", H2),
    bullets([
        "<b>Wissensdatenbank:</b> interne Wissens-Seiten (hierarchisch, aus Confluence importiert) – "
        "Preise, Abläufe, B2B-Wissen. Auch fürs Portal freigebbare Seiten.",
        "<b>Tickets:</b> internes Aufgaben-Board (Zu erledigen / In Bearbeitung / Erledigt) mit "
        "Wichtigkeit – für alles, was kein Event ist.",
        "<b>Admin-Zugänge:</b> weitere Admins anlegen/deaktivieren; Passwort-Reset per Mail. "
        "Je Zugang wird der <b>Zugriff</b> gewählt: <b>Inhaber</b> (Vollzugriff) oder "
        "<b>Büro / Disposition</b>.",
        "<b>Büro / Disposition</b> darf alles Operative: Events und Reservierungen anlegen und "
        "bearbeiten, Dienstleister anfragen, Briefings und Checklisten verschicken, Kunden pflegen, "
        "Angebote und Bastel-Recherche. Nicht sichtbar sind Buchhaltung, Stundensätze der "
        "Dienstleister, Status-Scoring und Nachweis-PDFs, Papierkorb und die Zugangsverwaltung; "
        "Events, Kunden und Dienstleister löschen geht ebenfalls nicht. Gesperrte Bereiche stehen "
        "gar nicht erst im Menü. Die eigene Rolle kann niemand ändern.",
        "<b>Papierkorb:</b> Gelöschte Events/Kunden landen erst hier – wiederherstellen oder als JSON "
        "sichern. Nichts ist sofort weg.",
        "<b>Backup:</b> jeden Montag kommt automatisch eine CSV-Sicherung der wichtigsten Tabellen per "
        "Mail – unabhängig von der Datenbank.",
    ]),
    Spacer(1, 4),
    hinweis("<b>Die drei goldenen Regeln für den Alltag:</b> 1) Alles läuft über die Event-Seite – der "
            "Workflow-Leiste folgen, dann fehlt nichts. 2) Der Glocke vertrauen: Was wichtig ist, meldet "
            "sich von selbst. 3) Nichts ist verloren – Papierkorb und Montags-Backup sind das Sicherheitsnetz."),
]

doc.build(story)
print("PDF gebaut:", PDF_OUT)
