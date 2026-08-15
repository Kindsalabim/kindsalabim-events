# -*- coding: utf-8 -*-
"""Nachweis-Dossier je Dienstleister (Scheinselbstständigkeits-Vorsorge).

Fasst die dokumentierte Zusammenarbeit als PDF zusammen: Status der Unterlagen,
Selbstauskunft, Statistik der Verfügbarkeitsanfragen (inkl. Ablehnungen!),
vollständige Anfrage-Historie und selbst eingetragene Sperrzeiten. Für den
Prüfungs-/Streitfall per Klick aus der Dienstleisterkarte abrufbar.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle)

_BLAU = colors.HexColor("#003864")
_H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=15, leading=19,
                     textColor=_BLAU, spaceAfter=2)
_H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, leading=15,
                     textColor=_BLAU, spaceBefore=12, spaceAfter=4)
_P = ParagraphStyle("P", fontName="Helvetica", fontSize=9.5, leading=13.5,
                    textColor=colors.HexColor("#1f2937"), spaceAfter=3)
_KLEIN = ParagraphStyle("KLEIN", parent=_P, fontSize=8.5, leading=11.5,
                        textColor=colors.HexColor("#6b7280"))

_TABLE_STYLE = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f6fa")),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])


def _status(d):
    dsgvo = ("online bestätigt am " + d.dsgvo_knallfrosch_am[:10]) if d.dsgvo_knallfrosch_am \
        else ("liegt vor (Papier)" if d.dsgvo_unterzeichnet else "offen")
    agb = ("online bestätigt am " + d.agb_akzeptiert_am[:10]) if d.agb_akzeptiert_am else "offen"
    gs = "im Portal hochgeladen" if d.gewerbeschein_r2_key \
        else ("liegt vor (Papier)" if d.gewerbeschein_vorliegt else "offen")
    return [
        ["Rolle", d.rolle or "—"],
        ["DSGVO-Einwilligung (beide Firmen)", dsgvo],
        ["Einkaufs-AGB (beide Firmen)", agb],
        ["Gewerbeschein", gs],
        ["Weitere Auftraggeber (Selbstauskunft)", "ja" if d.weitere_auftraggeber else "keine Angabe"],
        ["Eigene Website / Profil", d.website or "keine Angabe"],
        ["Eigene Betriebshaftpflicht (Selbstauskunft)", "ja" if d.betriebshaftpflicht else "keine Angabe"],
        ["Stundensatz Teamer / Künstler",
         (f"{d.stundensatz_teamer:.2f} €".replace(".", ",") if d.stundensatz_teamer else "—")
         + " / "
         + (f"{d.stundensatz_kuenstler:.2f} €".replace(".", ",") if d.stundensatz_kuenstler else "—")],
    ]


def build_dossier_pdf(d, anfragen, sperrzeiten) -> bytes:
    """anfragen: Verfuegbarkeitsanfragen (mit .event geladen), sperrzeiten: Liste."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm,
                            title=f"Nachweis-Dossier {d.vorname} {d.nachname}")

    story = [
        Paragraph(f"Nachweis-Dossier: {d.vorname} {d.nachname}", _H1),
        Paragraph(f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} Uhr aus der "
                  "Auftragsverwaltung (Kindsalabim/Knallfrosch Events-App).", _KLEIN),
        Spacer(1, 4),
        Paragraph(
            "Arbeitsweise: Jeder mögliche Einsatz wird dem Auftragnehmer einzeln als "
            "Verfügbarkeitsanfrage mit Antwortfrist angeboten. Der Auftragnehmer entscheidet "
            "frei über Annahme oder Ablehnung; Ablehnungen bleiben folgenlos. Nicht verfügbare "
            "Zeiträume trägt der Auftragnehmer selbst ein. Die Vergütung wird je Auftrag "
            "vereinbart und vom Auftragnehmer in Rechnung gestellt; eine Vergütung erfolgt nur "
            "bei tatsächlicher Leistungserbringung. Der Auftragnehmer ist in kein "
            "Zeiterfassungssystem eingebunden und nutzt keine E-Mail-Adresse des Auftraggebers.", _P),

        Paragraph("Status & Selbstauskunft", _H2),
        Table([[Paragraph(f"<b>{a}</b>", _P), Paragraph(str(b), _P)] for a, b in _status(d)],
              colWidths=[75*mm, None], style=_TABLE_STYLE),
    ]

    # Statistik
    def _n(status):
        return sum(1 for a in anfragen if a.status == status)
    stat = [
        ["Angebotene Anfragen gesamt", str(len(anfragen))],
        ["Angenommen (Zusagen)", str(_n("Ja"))],
        ["Abgelehnt (frei entschieden)", str(_n("Nein"))],
        ["Nicht reagiert / Frist abgelaufen", str(_n("Abgelaufen"))],
        ["Aktuell offen", str(_n("Ausstehend"))],
        ["Fristverlängerungen auf eigenen Wunsch", str(sum(1 for a in anfragen if a.frist_verlaengert))],
        ["Selbst eingetragene Sperrzeiten (Urlaub o. Ä.)", str(len(sperrzeiten))],
    ]
    story += [
        Paragraph("Statistik der Zusammenarbeit", _H2),
        Table([[Paragraph(f"<b>{a}</b>", _P), Paragraph(b, _P)] for a, b in stat],
              colWidths=[75*mm, None], style=_TABLE_STYLE),
    ]

    # Anfrage-Historie
    if anfragen:
        kopf = ["Eventdatum", "Anlass", "Rolle", "Honorar", "Antwort"]
        zeilen = [kopf]
        for a in sorted(anfragen, key=lambda x: (x.event.datum or datetime.min.date())
                        if x.event else datetime.min.date(), reverse=True):
            ev = a.event
            honorar = f"{a.budget:.2f} €".replace(".", ",") + " pauschal" if a.budget else "nach Stundensatz"
            zeilen.append([
                ev.datum.strftime("%d.%m.%Y") if ev and ev.datum else "—",
                Paragraph((ev.anlass or "—") if ev else "—", _KLEIN),
                a.rolle_anfrage or "—",
                honorar,
                a.status or "—",
            ])
        story += [
            Paragraph("Anfrage-Historie (vollständig)", _H2),
            Table(zeilen, colWidths=[22*mm, None, 20*mm, 32*mm, 24*mm],
                  style=_TABLE_STYLE, repeatRows=1),
        ]

    # Sperrzeiten
    if sperrzeiten:
        zeilen = [["Von", "Bis", "Grund"]]
        for s in sperrzeiten:
            zeilen.append([s.von_datum.strftime("%d.%m.%Y"), s.bis_datum.strftime("%d.%m.%Y"),
                           s.grund or "—"])
        story += [
            Paragraph("Selbst eingetragene Sperrzeiten", _H2),
            Table(zeilen, colWidths=[26*mm, 26*mm, None], style=_TABLE_STYLE, repeatRows=1),
        ]

    doc.build(story)
    return buf.getvalue()
