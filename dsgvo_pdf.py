# -*- coding: utf-8 -*-
"""Nachweis-PDF der Online-DSGVO-Einwilligung eines Dienstleisters.

Wird beim Bestätigen im Portal erzeugt und per Mail ans Büro + als Kopie an den
Dienstleister geschickt; zusätzlich jederzeit aus der Dienstleisterkarte abrufbar
(GET /admin/dienstleister/{id}/dsgvo.pdf). Der Text entspricht der Einwilligungs-
erklärung im Portal (templates/portal/profil.html) – bei Änderungen BEIDE Stellen
anpassen.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

_BLAU = colors.HexColor("#003864")

_H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=15, leading=19,
                     textColor=_BLAU, spaceAfter=10)
_H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                     textColor=_BLAU, spaceBefore=8, spaceAfter=2)
_P = ParagraphStyle("P", fontName="Helvetica", fontSize=9.5, leading=13.5,
                    textColor=colors.HexColor("#1f2937"), spaceAfter=3)

_ABSCHNITTE = [
    ("Verantwortliche",
     "1. Malca &amp; Akmanoglu GbR (Knallfrosch Kinderevents), Charlottenweg 55, 45289 Essen<br/>"
     "2. Aykut Malca (Kindsalabim Kinderevents), Charlottenweg 55, 45289 Essen"),
    ("Zweck der Datenverarbeitung",
     "Die angegebenen personenbezogenen Daten (Name, Adresse, E-Mail-Adresse, Telefonnummer, "
     "Kleidergröße, Angaben zu Mobilität und Gewerbe) werden ausschließlich zur Verwaltung und "
     "Organisation der Teamer-Datenbank sowie zur Kommunikation im Rahmen von Einsätzen und "
     "Projekten gespeichert und verarbeitet."),
    ("Rechtsgrundlage",
     "Freiwillig erteilte Einwilligung gemäß Art. 6 Abs. 1 lit. a DSGVO."),
    ("Speicherdauer",
     "Die Daten werden nur so lange gespeichert, wie es für die genannten Zwecke erforderlich ist "
     "oder bis die Einwilligung widerrufen wird. Danach werden sie unverzüglich gelöscht, sofern "
     "keine gesetzlichen Aufbewahrungspflichten entgegenstehen."),
    ("Weitergabe der Daten",
     "Die Daten werden nicht an Dritte weitergegeben, es sei denn, dies ist zur Durchführung eines "
     "Einsatzes erforderlich (z. B. Kontaktaufnahme mit Teammitgliedern oder Kunden)."),
    ("Rechte der betroffenen Person",
     "Auskunft (Art. 15), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der "
     "Verarbeitung (Art. 18), jederzeitiger Widerruf mit Wirkung für die Zukunft (Art. 7 Abs. 3) "
     "sowie Beschwerde bei einer Datenschutzbehörde (Art. 77 DSGVO)."),
    ("Widerruf",
     "Jederzeit schriftlich oder per E-Mail an die oben genannten Adressen; die personenbezogenen "
     "Daten werden dann unverzüglich gelöscht."),
]


def build_dsgvo_pdf(d) -> bytes:
    """Baut das Nachweis-PDF aus den in der DB gespeicherten Einwilligungsdaten."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=18*mm, bottomMargin=18*mm,
                            title="Einwilligung zur Speicherung personenbezogener Daten")
    story = [
        Paragraph("Einwilligung zur Speicherung personenbezogener Daten gemäß DSGVO", _H1),
    ]
    for titel, text in _ABSCHNITTE:
        story.append(Paragraph(titel, _H2))
        story.append(Paragraph(text, _P))

    story.append(Paragraph("Einwilligungserklärung", _H2))
    story.append(Paragraph(
        "Ich habe die oben stehenden Informationen gelesen und verstanden. Ich erkläre mich damit "
        "einverstanden, dass meine personenbezogenen Daten zum oben genannten Zweck durch die "
        "beiden genannten Verantwortlichen gespeichert und verarbeitet werden.", _P))
    story.append(Spacer(1, 6))

    zeilen = [
        ["Name (eingetippt als Bestätigung)", d.dsgvo_name or "—"],
        ["Dienstleister", f"{d.vorname} {d.nachname} ({d.email})"],
        ["Einwilligung Malca & Akmanoglu GbR (Knallfrosch)", (d.dsgvo_knallfrosch_am or "—").replace("T", " ")],
        ["Einwilligung Aykut Malca (Kindsalabim)", (d.dsgvo_kindsalabim_am or "—").replace("T", " ")],
        ["IP-Adresse bei Abgabe", d.dsgvo_ip or "—"],
        ["Art der Abgabe", "elektronisch bestätigt im Dienstleister-Portal (Checkbox + Name)"],
    ]
    t = Table([[Paragraph(f"<b>{a}</b>", _P), Paragraph(str(b), _P)] for a, b in zeilen],
              colWidths=[75*mm, None])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f6fa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
