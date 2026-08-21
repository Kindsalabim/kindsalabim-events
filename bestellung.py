# -*- coding: utf-8 -*-
"""Auto-„Bestellung" bei jeder Zusage (Scheinselbstständigkeits-Vorsorge).

Sagt ein Dienstleister im Portal zu, erzeugt die App automatisch eine Bestellung
nach der Anwaltsvorlage (Dr. Grunewald, Stand 03/2025): einzeln beauftragter
Auftrag mit bewusst „vagem" Honorar („ca. X € … zzgl. Nebenkosten nach
tatsächlichem Anfall" – Bestellung und spätere Rechnung müssen nicht
deckungsgleich sein). Versand per Mail an den Dienstleister, Archiv im R2.

SICHERUNG: Ohne hinterlegten Stundensatz (Teamer) bzw. Budget/Stundensatz
(Künstler) wird KEINE Bestellung erzeugt – stattdessen bekommt der Admin eine
Glocke mit Hinweis auf die Datenpflege. So landet nie eine falsche Zahl in
einem Vertragsdokument.
"""
import io
import uuid
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

AGB_STAND = "03.03.2025"
FAHRZEIT_SATZ = 10.0   # €/Std. Nettofahrzeit – wie in „Erläuterung zur Rechnungsstellung"

_FIRMA = {
    "Knallfrosch": ("Knallfrosch Kinderevents – Malca & Akmanoglu GbR", "#1a7a1a"),
    "Kindsalabim": ("Aykut Malca – Kindsalabim Kinderevents", "#003864"),
}
_ANSCHRIFT = "Charlottenweg 55 | 45289 Essen"


def _firma(ev):
    return _FIRMA.get(ev.marke or "Kindsalabim", _FIRMA["Kindsalabim"])


def _de(betrag: float) -> str:
    return f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _stunden(ev):
    """Aktionszeit in Stunden aus den Event-Zeiten (None, wenn nicht berechenbar)."""
    try:
        sh, sm = map(int, (ev.startzeit or "").split(":"))
        eh, em = map(int, (ev.endzeit or "").split(":"))
        h = (eh * 60 + em - sh * 60 - sm) / 60
        return h if h > 0 else None
    except (ValueError, AttributeError):
        return None


def verguetungs_positionen(a, ev, d):
    """Vergütungs-Hauptzeile + zusätzlich abrechenbare Positionen für die Bestellung.

    Rückgabe (haupt, zusatz). haupt=None → keine belastbare Zahl hinterlegt, es wird
    KEINE Bestellung erzeugt (Datenpflege-Sicherung).

    Die Zusatzpositionen sind bewusst als Teil des BESTELLTEN Leistungsumfangs
    formuliert: § 3 Abs. 2 der Einkaufs-AGB macht den vereinbarten Umfang zum
    Maximum – vor Ort vereinbarte Verlängerungen, Fahrzeit und Nebenkosten müssen
    deshalb ausdrücklich mitbestellt sein, damit sie abrechenbar bleiben.
    """
    pauschal = a.rolle_anfrage == "Künstler" and a.budget
    if pauschal:
        haupt = (f"Pauschalhonorar {_de(a.budget)} € netto für die vereinbarte Leistung, "
                 f"inklusive Fahrtkosten und Fahrzeit.")
        zusatz = [
            "Eine vor Ort mit dem Kunden vereinbarte längere Aktionszeit oder zusätzlich "
            "erbrachte Leistungen: nach tatsächlichem Umfang.",
            "Auftragsbezogene Nebenkosten wie Park- und Mautgebühren: nach tatsächlichem Anfall.",
        ]
    else:
        satz = d.stundensatz_kuenstler if a.rolle_anfrage == "Künstler" else d.stundensatz_teamer
        h = _stunden(ev)
        if not satz or not h:
            return None, []
        est = round(h * satz)
        h_txt = f"{h:g}".replace(".", ",")
        haupt = (f"ca. {est} € für die kalkulierte Aktionszeit "
                 f"(ca. {h_txt} Std. à {_de(satz)} €/Std.). Diese Angabe ist eine "
                 f"Kalkulationsgrundlage – abgerechnet wird der tatsächliche Aufwand.")
        zusatz = [
            f"Auf- und Abbauzeiten sowie eine vor Ort mit dem Kunden vereinbarte längere "
            f"Aktionszeit oder frühere Anwesenheit: nach tatsächlichem Aufwand zu "
            f"{_de(satz)} €/Std.",
            f"Fahrzeit: {_de(FAHRZEIT_SATZ)} €/Std. (Nettofahrzeit laut Routenplaner, ohne Stau).",
            "Auftragsbezogene Nebenkosten wie Fahrtkosten, Park- und Mautgebühren: "
            "nach tatsächlichem Anfall.",
        ]
    if a.als_logistiker:
        # Bewusst als eigenständig beauftragte Transportleistung formuliert (nicht als
        # selbstverständliche Nebenpflicht) – der Mehraufwand wird vergütet.
        zusatz.append(
            "Gesondert beauftragte Transportleistung: Abholung des Materials vor dem Einsatz "
            "und Rücklieferung im Anschluss, einschließlich des dafür anfallenden Zeit- und "
            "Fahraufwands – nach tatsächlichem Umfang.")
    return haupt, zusatz


def build_bestellung_pdf(a, ev, d, verguetung: str, zusatz=None) -> bytes:
    """Bestellung nach Anwaltsvorlage als PDF (ein Auftrag = eine Bestellung)."""
    firma, farbe = _firma(ev)
    akzent = colors.HexColor(farbe)
    H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16, leading=20,
                        textColor=akzent, spaceBefore=10, spaceAfter=8)
    P = ParagraphStyle("P", fontName="Helvetica", fontSize=10, leading=14.5,
                       textColor=colors.HexColor("#1f2937"), spaceAfter=4)
    KLEIN = ParagraphStyle("KLEIN", parent=P, fontSize=8, leading=11,
                           textColor=colors.HexColor("#6b7280"))

    from choices import anfrage_ort
    leistung = ("Künstlerische Leistung" + (f" ({d.kuenstler_sparte})" if d.kuenstler_sparte else "")
                if a.rolle_anfrage == "Künstler" else "Eventbetreuung als Teamer:in")
    if a.als_logistiker:
        leistung += " inkl. Materialtransport"
    zeilen = [
        ["Projekt", f"{ev.anlass or 'Event'} ({ev.marke})"],
        ["Datum / Zeit", f"{ev.datum.strftime('%d.%m.%Y')} · {ev.startzeit}–{ev.endzeit} Uhr"],
        ["Einsatzort", anfrage_ort(ev.veranstaltungsort, a.rolle_anfrage) or "—"],
        ["Leistung", leistung],
        ["Vergütung", verguetung],
    ]
    tabelle = Table([[Paragraph(f"<b>{k}</b>", P), Paragraph(v, P)] for k, v in zeilen],
                    colWidths=[38*mm, None])
    tabelle.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f6fa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    empfaenger = [f"{d.vorname} {d.nachname}"]
    if d.strasse:
        empfaenger.append(d.strasse)
    if d.plz or d.stadt:
        empfaenger.append(f"{d.plz or ''} {d.stadt or ''}".strip())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22*mm, rightMargin=22*mm,
                            topMargin=20*mm, bottomMargin=18*mm, title="Bestellung")
    story = [
        Paragraph(f"{firma} | {_ANSCHRIFT}", KLEIN),
        Spacer(1, 10),
        Paragraph("<br/>".join(empfaenger), P),
        Spacer(1, 8),
        Paragraph(f"Essen, den {datetime.now().strftime('%d.%m.%Y')}", P),
        Paragraph("Bestellung", H1),
        Paragraph(
            f"wir bestellen hiermit zu unseren aktuellen Einkaufsbedingungen "
            f"(AGB, Stand {AGB_STAND} – jederzeit im Dienstleister-Portal einsehbar) "
            f"die folgende Leistung:", P),
        Spacer(1, 4),
        tabelle,
        Spacer(1, 10),
    ]
    if zusatz:
        story.append(Paragraph(
            "Zum bestellten Leistungsumfang gehören ausdrücklich auch die folgenden Positionen; "
            "sie werden nach tatsächlichem Anfall vergütet:", P))
        story += [Paragraph(t, P, bulletText="•") for t in zusatz]
        story.append(Spacer(1, 6))
    story += [
        Paragraph(
            "<b>Kein Grund zur Rückfrage:</b> Dauert der Einsatz länger als kalkuliert, beginnt "
            "der Aufbau früher oder kommt vor Ort etwas hinzu, notiere den Mehraufwand einfach "
            "auf deiner Rechnung. Du musst dafür vorab nicht nachfragen.",
            ParagraphStyle("HINT", parent=P, backColor=colors.HexColor("#f3f6fa"),
                           borderPadding=6, spaceBefore=2, spaceAfter=8)),
        Paragraph(
            "Abgerechnet wird ausschließlich die tatsächlich erbrachte Leistung per Rechnung "
            "des Auftragnehmers; die endgültige Rechnung kann von den Angaben dieser Bestellung "
            "abweichen. Die Vergütung erfolgt zuzüglich Umsatzsteuer, falls gesetzlich "
            "vorgeschrieben.", P),
        Spacer(1, 4),
        Paragraph(
            "Diese Bestellung wurde automatisch mit deiner Zusage im Dienstleister-Portal "
            "erstellt und bedarf keiner Unterschrift.", KLEIN),
    ]
    doc.build(story)
    return buf.getvalue()


def bestellung_erzeugen_async(anfrage_id: int):
    """Hintergrund-Task nach einer Zusage: Bestellung bauen, mailen, archivieren.
    Fehler brechen NIE die Zusage – schlimmstenfalls gibt es eine Hinweis-Glocke."""
    from database import SessionLocal
    from models import Verfuegbarkeitsanfrage
    from notifications import notify
    db = SessionLocal()
    try:
        a = db.query(Verfuegbarkeitsanfrage).filter(
            Verfuegbarkeitsanfrage.id == anfrage_id).first()
        if not a or a.status != "Ja" or a.bestellung_am:
            return  # keine Zusage (mehr) oder Bestellung existiert schon (idempotent)
        ev, d = a.event, a.dienstleister
        if not ev or not d or not ev.datum:
            return
        name = f"{d.vorname} {d.nachname}"
        datum = ev.datum.strftime("%d.%m.%Y")
        verguetung, zusatz = verguetungs_positionen(a, ev, d)
        if not verguetung:
            # SICHERUNG: keine belastbare Zahl → keine Bestellung, aber Hinweis zur Datenpflege
            feld = "Budget/Stundensatz Künstler" if a.rolle_anfrage == "Künstler" else "Stundensatz Teamer"
            notify(db, "bestellung", f"⚠ Keine Bestellung erzeugt: {name}",
                   f"{name} hat für {ev.anlass or 'das Event'} am {datum} zugesagt, aber es ist "
                   f"kein {feld} hinterlegt. Bitte im Dienstleister-Profil pflegen – "
                   f"die Bestellung wird sonst nicht erzeugt.",
                   f"/admin/dienstleister/{d.id}/edit", marke=ev.marke)
            db.commit()
            return
        pdf = build_bestellung_pdf(a, ev, d, verguetung, zusatz)
        dateiname = f"Bestellung_{(ev.anlass or 'Event').replace(' ', '_')}_{ev.datum.strftime('%Y-%m-%d')}.pdf"
        from email_service import send_bestellung
        send_bestellung(d, ev, pdf, dateiname)
        a.bestellung_am = datetime.now().isoformat(timespec="seconds")
        # Archiv im R2 (Nachweis) – best effort, Mail zählt als Primärbeleg
        try:
            from routes.fotos import _r2_put
            key = f"dienstleister/{d.id}/bestellungen/{uuid.uuid4().hex}.pdf"
            if _r2_put(key, pdf, "application/pdf"):
                a.bestellung_r2_key = key
        except Exception as e:
            print(f"Bestellung-Archiv fehlgeschlagen (Anfrage {anfrage_id}): {e}")
        notify(db, "bestellung", f"Bestellung verschickt: {name}",
               f"Automatische Bestellung für {ev.anlass or 'das Event'} am {datum} an {name} "
               f"verschickt. Vergütung: {verguetung}",
               f"/admin/events/{ev.id}", marke=ev.marke)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Auto-Bestellung fehlgeschlagen (Anfrage {anfrage_id}): {e}")
        try:
            from notifications import notify as _n
            _n(db, "bestellung", "⚠ Bestellung fehlgeschlagen",
               f"Die automatische Bestellung zu Anfrage {anfrage_id} konnte nicht "
               f"verschickt werden ({e}).", "")
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
