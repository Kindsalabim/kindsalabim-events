"""Briefing als PDF (reportlab) – zum Ausdrucken/Weitergeben an externe Agentur-Leute.
Inhalt entspricht der Briefing-Mail: Veranstaltung, Ansprechpartner, Team, Hinweis."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas

from choices import de_date


def _brand_rgb(marke):
    return (0.102, 0.478, 0.102) if marke == "Knallfrosch" else (0.0, 0.220, 0.392)


def build_briefing_pdf(ev, dienstleister, externe=None) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    r, g, b = _brand_rgb(ev.marke)
    x = 20 * mm
    marke_name = "Knallfrosch Kinderevents" if ev.marke == "Knallfrosch" else "Kindsalabim Kinderevents"

    # Kopfbalken
    c.setFillColorRGB(r, g, b)
    c.rect(0, H - 16 * mm, W, 16 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, H - 11 * mm, f"Briefing · {marke_name}")

    state = {"y": H - 26 * mm}

    def newpage_if_needed():
        if state["y"] < 25 * mm:
            c.showPage()
            c.setFillColorRGB(r, g, b)
            c.rect(0, H - 16 * mm, W, 16 * mm, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica-Bold", 14)
            c.drawString(x, H - 11 * mm, f"Briefing · {marke_name}")
            state["y"] = H - 26 * mm

    def section(title):
        state["y"] -= 3 * mm
        newpage_if_needed()
        c.setFont("Helvetica-Bold", 9); c.setFillColorRGB(r, g, b)
        c.drawString(x, state["y"], title.upper())
        state["y"] -= 6.5 * mm

    def row(label, value):
        newpage_if_needed()
        c.setFont("Helvetica", 10); c.setFillColorRGB(0.42, 0.45, 0.50)
        c.drawString(x, state["y"], label)
        c.setFillColorRGB(0.10, 0.10, 0.12)
        lines = simpleSplit(str(value if value not in (None, "") else "–"),
                            "Helvetica", 10, W - x - 55 * mm)
        for i, ln in enumerate(lines):
            c.drawString(x + 45 * mm, state["y"], ln)
            if i < len(lines) - 1:
                state["y"] -= 5 * mm
        state["y"] -= 6 * mm

    def para(text):
        c.setFont("Helvetica", 10); c.setFillColorRGB(0.10, 0.10, 0.12)
        for ln in simpleSplit(str(text), "Helvetica", 10, W - 2 * x):
            newpage_if_needed()
            c.drawString(x, state["y"], ln)
            state["y"] -= 5 * mm
        state["y"] -= 3 * mm

    # Titel
    c.setFillColorRGB(0.10, 0.10, 0.12); c.setFont("Helvetica-Bold", 16)
    c.drawString(x, state["y"], ev.anlass or "Event")
    state["y"] -= 7 * mm
    c.setFont("Helvetica", 11); c.setFillColorRGB(0.30, 0.30, 0.33)
    c.drawString(x, state["y"], f"{ev.kunde_firma or ''} · {de_date(ev.datum)}")
    state["y"] -= 8 * mm

    section("Veranstaltung")
    row("Anlass", ev.anlass)
    row("Kunde", ev.kunde_firma)
    row("Datum", de_date(ev.datum))
    row("Uhrzeit", f"{ev.startzeit} – {ev.endzeit} Uhr" if ev.endzeit else (ev.startzeit or "–"))
    if ev.cl_aufbau_von:
        row("Aufbau", ev.cl_aufbau_von + (f" – {ev.cl_aufbau_bis}" if ev.cl_aufbau_bis else ""))
    if ev.cl_abbau_von:
        row("Abbau", ev.cl_abbau_von + (f" – {ev.cl_abbau_bis}" if ev.cl_abbau_bis else ""))
    row("Ort", ev.veranstaltungsort)
    if ev.cl_aufbauort:
        row("Indoor/Outdoor", ev.cl_aufbauort)
    if ev.cl_parkplatz:
        row("Parkplatz", ev.cl_parkplatz)
    if ev.cl_teamkleidung:
        row("Teamkleidung", ev.cl_teamkleidung)
    if ev.cl_verpflegung:
        row("Verpflegung", ev.cl_verpflegung)
    row("Produkte", ev.produkte)

    section("Ansprechpartner vor Ort")
    row("Name", ev.kunde_kontakt)
    row("Telefon", ev.kunde_telefon)

    section("Team")
    for m in dienstleister:
        nm = f"{m.vorname} {m.nachname}"
        if ev.teamleiter_id and m.id == ev.teamleiter_id:
            nm += "  (Teamleiter)"
        row(nm, m.telefon or "–")
    for e in (externe or []):
        row(f"{e.name}  (extern)", e.telefon or "–")
    if not dienstleister and not (externe or []):
        para("Noch kein Team eingetragen.")

    if ev.hinweise:
        section("Hinweis")
        para(ev.hinweise)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
