# -*- coding: utf-8 -*-
"""Erklärseite zur Fremdleistungs-Aufschlüsselung (doku/Fremdleistungen.pdf).

Eine A4-Seite, die zeigt, wie die Honorare der Dienstleister in die Buchhaltung
kommen, obwohl ihre Rechnungen erst nach der Kundenrechnung eintreffen.

Aufruf aus dem Repo-Wurzelverzeichnis:
    PYTHONUTF8=1 python doku/build_fremdleistungen.py
"""
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

DOKU = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DOKU)
sys.path.insert(0, REPO)
OUT = os.path.join(DOKU, "Fremdleistungen.pdf")
LOGO = os.path.join(REPO, "static", "img", "logo-kindsalabim.png")

W, H = A4
MARGE = 16 * mm

NAVY = (0 / 255, 56 / 255, 100 / 255)
INK = (0.09, 0.11, 0.15)
GRAU = (0.42, 0.45, 0.50)
HELL = (0.98, 0.98, 0.99)
RAND = (0.89, 0.90, 0.92)
ORANGE = (0.96, 0.62, 0.10)
GRUEN = (0.13, 0.55, 0.33)
ROT = (0.75, 0.28, 0.25)


def _wrap(c, text, font, size, breite):
    woerter, zeilen, akt = text.split(), [], ""
    for w in woerter:
        probe = (akt + " " + w).strip()
        if stringWidth(probe, font, size) <= breite:
            akt = probe
        else:
            if akt:
                zeilen.append(akt)
            akt = w
    if akt:
        zeilen.append(akt)
    return zeilen


def absatz(c, text, x, y, breite, font="Helvetica", size=9.5, lh=4.6 * mm, farbe=INK):
    c.setFont(font, size)
    c.setFillColorRGB(*farbe)
    for zeile in _wrap(c, text, font, size, breite):
        c.drawString(x, y, zeile)
        y -= lh
    return y


def absatz_hoehe(c, text, breite, font="Helvetica", size=9.5, lh=4.6 * mm):
    """Höhe, die ein Absatz braucht – damit Karten nicht geraten, sondern gemessen
    werden (sonst läuft der Text bei jeder Textänderung wieder heraus)."""
    return len(_wrap(c, text, font, size, breite)) * lh


def karte(c, x, y, breite, hoehe, fuellung=(1, 1, 1)):
    c.setFillColorRGB(0.93, 0.94, 0.95)
    c.roundRect(x + 0.9 * mm, y - 0.9 * mm, breite, hoehe, 2.4 * mm, fill=1, stroke=0)
    c.setFillColorRGB(*fuellung)
    c.setStrokeColorRGB(*RAND)
    c.setLineWidth(0.7)
    c.roundRect(x, y, breite, hoehe, 2.4 * mm, fill=1, stroke=1)


def schritt(c, nr, titel, text, x, y, breite):
    """Nummerierter Ablaufschritt mit Kreis."""
    r = 4.2 * mm
    c.setFillColorRGB(*NAVY)
    c.circle(x + r, y - r, r, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + r, y - r - 1.3 * mm, str(nr))
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x + 2 * r + 2.5 * mm, y - 3.4 * mm, titel)
    absatz(c, text, x + 2 * r + 2.5 * mm, y - 8.6 * mm, breite - 2 * r - 2.5 * mm,
           size=8.5, lh=3.9 * mm, farbe=GRAU)


def pfeil_runter(c, x, y, laenge=5 * mm):
    c.setStrokeColorRGB(*RAND)
    c.setLineWidth(1.2)
    c.line(x, y, x, y - laenge)
    c.setFillColorRGB(*RAND)
    p = c.beginPath()
    p.moveTo(x - 1.4 * mm, y - laenge)
    p.lineTo(x + 1.4 * mm, y - laenge)
    p.lineTo(x, y - laenge - 1.8 * mm)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def offen_marker(c, x, y, zahl):
    """Oranger Punkt + Zahl – im Bildschirm ist das die Sanduhr."""
    c.setFillColorRGB(*ORANGE)
    c.circle(x + 1.1 * mm, y + 1.1 * mm, 1.1 * mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x + 3 * mm, y, str(zahl))


def build():
    c = rl_canvas.Canvas(OUT, pagesize=A4, pageCompression=1)
    c.setTitle("Fremdleistungen – Honorare der Dienstleister in der Buchhaltung")
    inhalt_w = W - 2 * MARGE

    # ── Kopf ──────────────────────────────────────────────────────────────────
    try:
        img = ImageReader(LOGO)
        iw, ih = img.getSize()
        zh = 8.5 * mm
        c.drawImage(img, MARGE, H - 17 * mm, width=zh * iw / ih, height=zh, mask="auto")
    except Exception:
        pass
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 19)
    c.drawRightString(W - MARGE, H - 15.5 * mm, "Fremdleistungen")
    c.setStrokeColorRGB(*NAVY)
    c.setLineWidth(1.1)
    c.line(MARGE, H - 20 * mm, W - MARGE, H - 20 * mm)

    y = H - 26 * mm
    c.setFillColorRGB(*GRAU)
    c.setFont("Helvetica", 10)
    c.drawString(MARGE, y, "Die Honorare der Dienstleister in der Buchhaltung – "
                           "auch wenn ihre Rechnungen erst Wochen später kommen.")
    y -= 8 * mm

    # ── Das Problem ───────────────────────────────────────────────────────────
    problem = ("Die Rechnung an den Kunden ist raus, der Auftrag abgeschlossen – und erst danach "
               "trudeln nach und nach die Rechnungen der sechs Teamer ein. Bis dahin stehen in der "
               "Buchhaltung zu niedrige Kosten, und der Fehler summiert sich über das Jahr.")
    hoehe = 12 * mm + absatz_hoehe(c, problem, inhalt_w - 10 * mm, size=8.5, lh=3.9 * mm)
    karte(c, MARGE, y - hoehe, inhalt_w, hoehe, fuellung=(0.99, 0.96, 0.90))
    c.setFillColorRGB(*ORANGE)
    c.rect(MARGE, y - hoehe, 1.6 * mm, hoehe, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColorRGB(*INK)
    c.drawString(MARGE + 6 * mm, y - 5.5 * mm, "Das Problem")
    absatz(c, problem, MARGE + 6 * mm, y - 9.6 * mm, inhalt_w - 10 * mm,
           size=8.5, lh=3.9 * mm, farbe=GRAU)
    y -= hoehe + 8 * mm

    # ── Drei Schritte ─────────────────────────────────────────────────────────
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGE, y, "So läuft es jetzt")
    y -= 6 * mm

    sp = 5 * mm
    sw = (inhalt_w - 2 * sp) / 3
    schritte = [
        (1, "Zusage → Schätzung",
         "Sagt jemand zu, entsteht automatisch eine Honorarzeile. Geschätzt werden "
         "Aktionszeit, Auf- und Abbau und die Fahrzeit – beim Künstler das Pauschalbudget."),
        (2, "Rechnung eintippen",
         "Trifft die Rechnung ein, den echten Betrag in die Zeile der Person schreiben. "
         "Ein Feld, ein Betrag, fertig."),
        (3, "Summe zieht nach",
         "Die Fremdleistungen der Kundenrechnung aktualisieren sich sofort – auch Wochen "
         "später. Gewinn und Rücklagen rechnen mit."),
    ]
    text_w = sw - 8 * mm - 2 * 4.2 * mm - 2.5 * mm
    hoehe = 13 * mm + max(absatz_hoehe(c, t, text_w, size=8.5, lh=3.9 * mm)
                          for _, _, t in schritte)
    for i, (nr, titel, text) in enumerate(schritte):
        x = MARGE + i * (sw + sp)
        karte(c, x, y - hoehe, sw, hoehe)
        schritt(c, nr, titel, text, x + 4 * mm, y - 3.5 * mm, sw - 8 * mm)
    y -= hoehe + 9 * mm

    # ── Kernbild: die Buchhaltungszeile ───────────────────────────────────────
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGE, y, "In der Buchhaltung bleibt es eine Zeile pro Rechnung")
    y -= 5 * mm
    c.setFont("Helvetica", 8.5)
    c.setFillColorRGB(*GRAU)
    c.drawString(MARGE, y, "Der Klick auf den Fremdleistungs-Betrag klappt die Personen darunter auf.")
    y -= 7 * mm

    # Tabellenkopf – Spalten so gesetzt, dass der Offen-Marker rechts vom
    # Fremdleistungs-Betrag Platz hat, ohne in die Material-Spalte zu laufen
    spalten = [("Kunde", MARGE + 3 * mm, "l"), ("Datum", MARGE + 44 * mm, "l"),
               ("Brutto", MARGE + 82 * mm, "r"), ("Fremdl.", MARGE + 116 * mm, "r"),
               ("Material", MARGE + 148 * mm, "r"), ("Gewinn", inhalt_w + MARGE - 3 * mm, "r")]
    zeile_h = 8 * mm
    karte(c, MARGE, y - zeile_h, inhalt_w, zeile_h, fuellung=HELL)
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColorRGB(*GRAU)
    for label, x, ausr in spalten:
        (c.drawRightString if ausr == "r" else c.drawString)(x, y - 5.2 * mm, label)
    y -= zeile_h

    # Die Rechnungszeile
    karte(c, MARGE, y - zeile_h, inhalt_w, zeile_h)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(*INK)
    c.drawString(MARGE + 3 * mm, y - 5.2 * mm, "Kita Sonnenschein")
    c.setFont("Helvetica", 8.5)
    c.setFillColorRGB(*GRAU)
    c.drawString(MARGE + 44 * mm, y - 5.2 * mm, "03.09.2026")
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(MARGE + 82 * mm, y - 5.2 * mm, "2.400,00 EUR")
    c.setFillColorRGB(*NAVY)
    c.drawRightString(MARGE + 116 * mm, y - 5.2 * mm, "1.225,00 EUR")
    offen_marker(c, MARGE + 118 * mm, y - 5.5 * mm, 2)
    c.setFont("Helvetica", 8.5)
    c.setFillColorRGB(*GRAU)
    c.drawRightString(MARGE + 148 * mm, y - 5.2 * mm, "240,00 EUR")
    c.setFillColorRGB(*GRUEN)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(inhalt_w + MARGE - 3 * mm, y - 5.2 * mm, "551,81 EUR")
    y -= zeile_h

    # Legende zum Marker (unter der Zeile statt daneben – sonst kollidiert sie
    # mit den rechten Spalten)
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColorRGB(*ORANGE)
    c.drawString(MARGE + 118 * mm, y - 3.6 * mm, "= 2 Rechnungen fehlen noch")
    y -= 4 * mm

    pfeil_runter(c, MARGE + 112 * mm, y - 1 * mm)
    y -= 8 * mm

    # Aufgeklappte Aufschlüsselung
    personen = [("Ali Demir", "geschätzt 300,00", "355,00", "eingegangen 03.09."),
                ("Kevin Haller", "geschätzt 340,00", "310,00", "eingegangen 03.09."),
                ("Nicole Bosse", "geschätzt 280,00", "", "offen"),
                ("Zoe Muster", "geschätzt 280,00", "", "offen")]
    panel_h = (len(personen) + 1) * 6.4 * mm + 5 * mm
    karte(c, MARGE + 8 * mm, y - panel_h, inhalt_w - 16 * mm, panel_h, fuellung=HELL)
    py = y - 6 * mm
    for name, gesch, ist, status in personen:
        c.setFont("Helvetica", 8.5)
        c.setFillColorRGB(*INK)
        c.drawString(MARGE + 12 * mm, py, name)
        c.setFillColorRGB(*GRAU)
        c.setFont("Helvetica", 8)
        c.drawString(MARGE + 45 * mm, py, gesch + " EUR")
        # Eingabefeld
        fx = MARGE + 80 * mm
        c.setStrokeColorRGB(*RAND)
        c.setFillColorRGB(1, 1, 1)
        c.setLineWidth(0.7)
        c.roundRect(fx, py - 1.6 * mm, 20 * mm, 5.2 * mm, 1 * mm, fill=1, stroke=1)
        if ist:
            c.setFillColorRGB(*INK)
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(fx + 18 * mm, py, ist)
        else:
            c.setFillColorRGB(0.72, 0.74, 0.77)
            c.setFont("Helvetica-Oblique", 8)
            c.drawRightString(fx + 18 * mm, py, "Betrag")
        # Status
        offen = status == "offen"
        c.setFillColorRGB(*(ORANGE if offen else GRUEN))
        c.circle(MARGE + 106 * mm, py + 1.1 * mm, 1.1 * mm, fill=1, stroke=0)
        c.setFont("Helvetica", 8)
        c.drawString(MARGE + 109 * mm, py, status)
        if offen:
            c.setFillColorRGB(*NAVY)
            c.setFont("Helvetica", 8)
            c.drawString(MARGE + 140 * mm, py, "Erinnerung schicken")
        py -= 6.4 * mm
    # Summenzeile im Panel
    c.setStrokeColorRGB(*RAND)
    c.setLineWidth(0.6)
    c.line(MARGE + 12 * mm, py + 3.4 * mm, inhalt_w + MARGE - 12 * mm, py + 3.4 * mm)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColorRGB(*INK)
    c.drawString(MARGE + 12 * mm, py, "Summe 1.225,00 EUR")
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*GRAU)
    c.drawString(MARGE + 45 * mm, py, "2 Rechnungen ausstehend – der Betrag ist bis dahin geschätzt")
    y -= panel_h + 9 * mm

    # ── Zwei Kästen unten ─────────────────────────────────────────────────────
    sw2 = (inhalt_w - 5 * mm) / 2
    kaesten = [
        ("Nichts geht verloren",
         "Über der Rechnungsliste steht der Block „Ausstehende Dienstleister-Rechnungen“ – "
         "alle offenen Posten über alle Events hinweg, nach Alter sortiert. Von dort lässt sich "
         "pro Person eine Erinnerungsmail schicken. Kommt nie eine Rechnung (z. B. nach einer "
         "kurzfristigen Krankmeldung), entfernt ein Klick auf das ✕ die Zeile."),
        ("Die Schätzung wird besser",
         "30 Tage nach dem Event meldet die Glocke einmalig, welche Rechnungen fehlen. Und sobald "
         "genug Einsätze abgerechnet sind, vergleicht die App Schätzung und Ist und korrigiert "
         "künftige Schätzungen um den durchschnittlichen Versatz – damit die Kosten nicht "
         "dauerhaft zu niedrig mitlaufen."),
    ]
    hoehe = 14 * mm + max(absatz_hoehe(c, t, sw2 - 8 * mm, size=8, lh=3.7 * mm)
                          for _, t in kaesten)
    for i, (titel, text) in enumerate(kaesten):
        x = MARGE + i * (sw2 + 5 * mm)
        karte(c, x, y - hoehe, sw2, hoehe)
        c.setFillColorRGB(*NAVY)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x + 4 * mm, y - 6 * mm, titel)
        absatz(c, text, x + 4 * mm, y - 10.5 * mm, sw2 - 8 * mm, size=8,
               lh=3.7 * mm, farbe=GRAU)
    y -= hoehe + 7 * mm

    # ── Fußnote: die eine Voraussetzung ───────────────────────────────────────
    fuss_text = ("Die Aufschlüsselung erscheint nur, wenn oben „Aus Event übernehmen“ gewählt "
                 "wurde – erst dadurch weiß die Rechnung, zu welchem Event sie gehört. Kunde, "
                 "Material und Fremdleistungen werden dabei gleich mit ausgefüllt.")
    hoehe = 11 * mm + absatz_hoehe(c, fuss_text, inhalt_w - 10 * mm, size=8, lh=3.6 * mm)
    karte(c, MARGE, y - hoehe, inhalt_w, hoehe, fuellung=(0.95, 0.97, 1.0))
    c.setFillColorRGB(*NAVY)
    c.rect(MARGE, y - hoehe, 1.6 * mm, hoehe, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(*INK)
    c.drawString(MARGE + 6 * mm, y - 5 * mm, "Wichtig beim Anlegen der Kundenrechnung")
    absatz(c, fuss_text, MARGE + 6 * mm, y - 8.6 * mm, inhalt_w - 10 * mm,
           size=8, lh=3.6 * mm, farbe=GRAU)

    # Fuß
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(*GRAU)
    c.drawString(MARGE, 10 * mm, "Kindsalabim Events-App")
    c.drawRightString(W - MARGE, 10 * mm, "Fremdleistungen – Stand 03.09.2026")

    c.showPage()
    c.save()
    print("PDF gebaut:", OUT)


if __name__ == "__main__":
    build()
