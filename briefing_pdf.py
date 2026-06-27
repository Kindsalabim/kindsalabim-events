"""Briefing als PDF (reportlab) – zum Ausdrucken/Weitergeben an externe Agentur-Leute.
Inhalt entspricht der Briefing-Mail: Veranstaltung, Ansprechpartner, Team, Hinweis."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas

from choices import de_date
import ankunft as _ankunft


def _brand_rgb(marke):
    return (0.102, 0.478, 0.102) if marke == "Knallfrosch" else (0.0, 0.220, 0.392)


def _clean(x) -> str:
    """Leerstring für None und den (aus dem alten Formular-Bug) gespeicherten Text 'None'."""
    s = x if isinstance(x, str) else ("" if x is None else str(x))
    return "" if s.strip().lower() == "none" else s


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
        lines = simpleSplit(_clean(value).strip() or "–",
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

    def hinweis(text):
        c.setFont("Helvetica-Oblique", 8.5); c.setFillColorRGB(0.55, 0.57, 0.60)
        for ln in simpleSplit(str(text), "Helvetica-Oblique", 8.5, W - 2 * x):
            newpage_if_needed()
            c.drawString(x, state["y"], ln)
            state["y"] -= 4.5 * mm
        state["y"] -= 3 * mm

    def warnung(text):
        # dezenter, voll umrandeter Hinweiskasten (kein breiter Amber-Balken)
        c.setFont("Helvetica-Bold", 9)
        lines = simpleSplit(str(text), "Helvetica-Bold", 9, W - 2 * x - 8 * mm)
        h = len(lines) * 5 * mm + 3 * mm
        newpage_if_needed()
        c.setFillColorRGB(0.969, 0.976, 0.984)
        c.setStrokeColorRGB(0.84, 0.86, 0.89); c.setLineWidth(0.8)
        c.roundRect(x, state["y"] - h + 4 * mm, W - 2 * x, h, 2 * mm, fill=1, stroke=1)
        c.setFillColorRGB(0.20, 0.24, 0.29)
        for ln in lines:
            c.drawString(x + 4 * mm, state["y"], ln)
            state["y"] -= 5 * mm
        state["y"] -= 4 * mm

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
    row("Aktionszeit", f"{ev.startzeit} – {ev.endzeit} Uhr" if ev.endzeit else (ev.startzeit or "–"))
    if ev.cl_aufbauort:
        row("Indoor/Outdoor", ev.cl_aufbauort)
    if ev.cl_parkplatz:
        row("Parkplatzsituation", ev.cl_parkplatz)
    if ev.cl_teamkleidung:
        row("Teamkleidung", ev.cl_teamkleidung)
    if ev.cl_verpflegung:
        row("Verpflegung", ev.cl_verpflegung)
    row("Produkte", ev.produkte)

    # Ankunft & Treffpunkt (prominent fürs Team)
    section("Ankunft & Treffpunkt")
    row("Ankunft", _ankunft.ankunft_anzeige(ev))
    row("Treffpunkt", _ankunft.treffpunkt_anzeige(ev))

    # Veranstaltungsanschrift (Checkliste bevorzugt, sonst grober Event-Ort)
    an_firma = (_clean(getattr(ev, "cl_firma_name", "")) or _clean(ev.kunde_firma)).strip()
    an_strasse = _clean(getattr(ev, "cl_strasse", "")).strip()
    an_plz_ort = _clean(getattr(ev, "cl_plz_ort", "")).strip()
    if not an_strasse and not an_plz_ort:
        an_plz_ort = _clean(ev.veranstaltungsort).strip()
    section("Veranstaltungsanschrift")
    row("Firma / Name", an_firma)
    if an_strasse:
        row("Straße", an_strasse)
    row("PLZ / Ort", an_plz_ort)

    section("Ansprechpartner vor Ort")
    row("Name", (_clean(getattr(ev, "cl_ansprechpartner_name", "")) or _clean(ev.kunde_kontakt)))
    row("Telefon", (_clean(getattr(ev, "cl_ansprechpartner_mobil", "")) or _clean(ev.kunde_telefon)))
    warnung("Nur für den Teamleiter. Alle anderen wenden sich vor Ort an unseren Teamleiter – nicht direkt an den Kunden-Ansprechpartner.")

    def team_row(name, tel, teamleiter=False, extern=False):
        newpage_if_needed()
        tel = _clean(tel).strip() or "–"
        if teamleiter:
            c.setFont("Helvetica-Bold", 11); c.setFillColorRGB(r, g, b)
            lead = f"★ {name}"
            c.drawString(x, state["y"], lead)
            lw = c.stringWidth(lead, "Helvetica-Bold", 11)
            c.setFont("Helvetica-Bold", 7); c.setFillColorRGB(r, g, b)
            c.drawString(x + lw + 3 * mm, state["y"] + 0.3 * mm, "TEAMLEITER")
            c.setFont("Helvetica-Bold", 10)
        else:
            c.setFont("Helvetica", 10); c.setFillColorRGB(0.10, 0.10, 0.12)
            c.drawString(x, state["y"], f"{name}  (extern)" if extern else name)
        c.setFillColorRGB(0.10, 0.10, 0.12)
        fnt = "Helvetica-Bold" if teamleiter else "Helvetica"
        c.setFont(fnt, 10)
        c.drawString(W - x - c.stringWidth(tel, fnt, 10), state["y"], tel)
        state["y"] -= 7 * mm

    section("Team")
    for m in dienstleister:
        is_tl = bool(ev.teamleiter_id and m.id == ev.teamleiter_id)
        team_row(f"{m.vorname} {m.nachname}", m.telefon, teamleiter=is_tl)
    for e in (externe or []):
        team_row(e.name, e.telefon, extern=True)
    if not dienstleister and not (externe or []):
        para("Noch kein Team eingetragen.")

    if ev.hinweise:
        section("Hinweis")
        para(ev.hinweise)

    if getattr(ev, "cl_weitere_details", None):
        section("Weitere Details")
        para(ev.cl_weitere_details)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
