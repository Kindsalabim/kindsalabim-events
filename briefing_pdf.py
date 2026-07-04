"""Briefing als PDF (reportlab) – im Stil der bewährten Briefing-2.0-Vorlagen:
Themen-Boxen im Zwei-Spalten-Raster mit den App-Linien-Icons (für Knallfrosch grün
umgefärbt), rote Akzente für das Kritische (Ankunft/Treffpunkt, Teamleitung),
Logo-Wasserzeichen, Fußzeile mit Anschrift + Rechnungs-Mail. Seite „Allgemeines"
rendert die Regeln aus den Einstellungen als Boxen mit Pfeil-Aufzählung
(„## "-Zeilen beginnen eine neue Box, {MARKE} wird ersetzt)."""
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit, ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from choices import de_date, rechnung_anschrift, sparte_label, regeln_abschnitte
import ankunft as _ankunft

_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img")
_ICON_DIR = os.path.join(_IMG_DIR, "icons")
_LOGOS = {
    "Knallfrosch": os.path.join(_IMG_DIR, "logo-knallfrosch.png"),
    "Kindsalabim": os.path.join(_IMG_DIR, "logo-kindsalabim.png"),
}
# Die Icon-SVGs sind in Kindsalabim-Blau angelegt – für Knallfrosch umfärben.
_KF_UMFAERBUNG = {"#1D4E89": "#1a7a1a", "#7FB3D9": "#8FCB8F"}

INK = (0.10, 0.10, 0.12)
GRAU = (0.42, 0.45, 0.50)
ROT = (0.75, 0.28, 0.25)          # Akzent für Kritisches (wie „Eintreffen" in der Vorlage)
RAND = (0.80, 0.83, 0.87)
SCHATTEN = (0.88, 0.90, 0.92)

_icon_cache: dict = {}


def _icon_reader(name, marke):
    """Rastert ein App-Icon-SVG (via pymupdf) zu einem ImageReader; gecacht.
    None, wenn das Icon fehlt oder nicht renderbar ist (Briefing bleibt nutzbar)."""
    key = (name, marke)
    if key not in _icon_cache:
        reader = None
        try:
            with open(os.path.join(_ICON_DIR, f"{name}.svg"), encoding="utf-8") as f:
                svg = f.read()
            if marke == "Knallfrosch":
                for alt, neu in _KF_UMFAERBUNG.items():
                    svg = svg.replace(alt, neu)
            import fitz
            doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
            pix = doc[0].get_pixmap(dpi=192, alpha=True)
            reader = ImageReader(io.BytesIO(pix.tobytes("png")))
            doc.close()
        except Exception:
            reader = None
        _icon_cache[key] = reader
    return _icon_cache[key]


def _brand_rgb(marke):
    return (0.102, 0.478, 0.102) if marke == "Knallfrosch" else (0.0, 0.220, 0.392)


def _clean(x) -> str:
    """Leerstring für None und den (aus dem alten Formular-Bug) gespeicherten Text 'None'."""
    s = x if isinstance(x, str) else ("" if x is None else str(x))
    return "" if s.strip().lower() == "none" else s


# ── Karten-Inhalt: Zeilen-Typen ───────────────────────────────────────────────────
# ("kv", label, wert, rot?)             Label-Wert-Zeile
# ("text", text)                        Fließtext
# ("team", name, tel, tl?, zusatz)      Team-Zeile (Name links, Telefon rechts)
# ("punkt", text)                       Pfeil-Aufzählungspunkt (Regeln)

_KV_LABEL_W = 30 * mm
_LH = 4.9 * mm          # Zeilenhöhe Inhalt
_PUNKT_EINZUG = 6 * mm


def _wrap(text, font, size, width):
    return simpleSplit(_clean(text).strip() or "–", font, size, width) or ["–"]


def _zeilen_hoehe(zeile, inhalt_w):
    typ = zeile[0]
    if typ == "kv":
        n = len(_wrap(zeile[2], "Helvetica-Bold" if zeile[3] else "Helvetica", 9.5,
                      inhalt_w - _KV_LABEL_W))
        return n * _LH + 1.2 * mm
    if typ == "text":
        n = 0
        for absatz in str(zeile[1]).split("\n"):
            n += len(simpleSplit(absatz, "Helvetica", 9.5, inhalt_w) or [""])
        return n * _LH + 1.2 * mm
    if typ == "team":
        return _LH + 1.6 * mm
    if typ == "punkt":
        n = len(simpleSplit(str(zeile[1]), "Helvetica", 9.5, inhalt_w - _PUNKT_EINZUG) or [""])
        return n * _LH + 1.6 * mm
    return _LH


def _karte_hoehe(karte, karten_w):
    inhalt_w = karten_w - 8 * mm
    h = 13.5 * mm                                # Titel + Linie + Abstand zur 1. Zeile
    for z in karte["zeilen"]:
        h += _zeilen_hoehe(z, inhalt_w)
    return h + 2.5 * mm                          # Innenabstand unten


class _Seite:
    """Zeichnet Karten in zwei Spalten (oder voller Breite) mit Kopf, Wasserzeichen
    und Fußzeile."""

    def __init__(self, c, ev):
        self.c = c
        self.ev = ev
        self.W, self.H = A4
        self.marge = 15 * mm
        self.spalt = 6 * mm
        self.karten_w = (self.W - 2 * self.marge - self.spalt) / 2
        self.brand = _brand_rgb(ev.marke)
        self.fuss_h = 24 * mm
        self.col_y = [0.0, 0.0]
        self.titel = "Briefing"

    # Kopf / Fuß / Wasserzeichen ---------------------------------------------------

    def _wasserzeichen(self):
        try:
            img = ImageReader(_LOGOS.get(self.ev.marke, _LOGOS["Kindsalabim"]))
            iw, ih = img.getSize()
            zw = self.W * 0.75
            zh = zw * ih / iw
            self.c.saveState()
            self.c.setFillAlpha(0.05)
            self.c.drawImage(img, (self.W - zw) / 2, (self.H - zh) / 2, width=zw, height=zh,
                             mask="auto")
            self.c.restoreState()
        except Exception:
            pass

    def _kopf(self):
        c = self.c
        self._wasserzeichen()
        try:
            img = ImageReader(_LOGOS.get(self.ev.marke, _LOGOS["Kindsalabim"]))
            iw, ih = img.getSize()
            zh = 9 * mm
            c.drawImage(img, self.marge, self.H - 15 * mm, width=zh * iw / ih, height=zh,
                        mask="auto")
        except Exception:
            pass
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(self.W / 2, self.H - 14.5 * mm, self.titel)
        c.setFillColorRGB(*self.brand)
        c.rect(0, self.H - 19.5 * mm, self.W, 1.2 * mm, fill=1, stroke=0)
        start = self.H - 26 * mm
        self.col_y = [start, start]

    def _fuss(self):
        c = self.c
        ra = rechnung_anschrift(self.ev.marke)
        c.setStrokeColorRGB(*RAND)
        c.setLineWidth(0.6)
        c.line(self.marge, self.fuss_h - 4 * mm, self.W - self.marge, self.fuss_h - 4 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(*GRAU)
        y = self.fuss_h - 8 * mm
        for zeile in ra["zeilen"]:
            c.drawString(self.marge, y, zeile)
            y -= 3.4 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(self.W - self.marge, self.fuss_h - 8 * mm, "Rechnung per Mail an:")
        c.setFont("Helvetica", 7.5)
        c.drawRightString(self.W - self.marge, self.fuss_h - 11.4 * mm, ra["mail"])
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(self.W / 2, self.fuss_h - 11.4 * mm, f"Seite {c.getPageNumber()}")

    def neue_seite(self, titel):
        self.titel = titel
        self._kopf()

    def seite_abschliessen(self):
        self._fuss()
        self.c.showPage()

    # Karten -----------------------------------------------------------------------

    def _zeile_zeichnen(self, zeile, x, y, inhalt_w):
        c = self.c
        typ = zeile[0]
        if typ == "kv":
            _, label, wert, rot = zeile
            c.setFont("Helvetica-Bold" if rot else "Helvetica", 9.5)
            c.setFillColorRGB(*(ROT if rot else GRAU))
            c.drawString(x, y, label + ":")
            c.setFillColorRGB(*INK)
            fnt = "Helvetica-Bold" if rot else "Helvetica"
            c.setFont(fnt, 9.5)
            for ln in _wrap(wert, fnt, 9.5, inhalt_w - _KV_LABEL_W):
                c.drawString(x + _KV_LABEL_W, y, ln)
                y -= _LH
            return y - 1.2 * mm
        if typ == "text":
            c.setFont("Helvetica", 9.5)
            c.setFillColorRGB(*INK)
            for absatz in str(zeile[1]).split("\n"):
                for ln in simpleSplit(absatz, "Helvetica", 9.5, inhalt_w) or [""]:
                    c.drawString(x, y, ln)
                    y -= _LH
            return y - 1.2 * mm
        if typ == "team":
            _, name, tel, is_tl, zusatz = zeile
            if is_tl:
                c.setFont("Helvetica-Bold", 10)
                c.setFillColorRGB(*ROT)
                c.drawString(x, y, "Teamleitung:")
                c.setFillColorRGB(*INK)
                c.drawString(x + 26 * mm, y, name)
                cursor = x + 26 * mm + c.stringWidth(name, "Helvetica-Bold", 10) + 2.5 * mm
            else:
                c.setFont("Helvetica", 9.5)
                c.setFillColorRGB(*INK)
                c.drawString(x, y, name)
                cursor = x + c.stringWidth(name, "Helvetica", 9.5) + 2.5 * mm
            if zusatz:
                c.setFont("Helvetica", 8)
                c.setFillColorRGB(*GRAU)
                c.drawString(cursor, y, zusatz)
            c.setFillColorRGB(*INK)
            fnt = "Helvetica-Bold" if is_tl else "Helvetica"
            c.setFont(fnt, 9.5)
            c.drawRightString(x + inhalt_w, y, _clean(tel).strip() or "–")
            return y - _LH - 1.6 * mm
        if typ == "punkt":
            # Pfeil-Dreieck wie in der Vorlage (als Pfad – Helvetica hat kein ▶-Glyph)
            c.setFillColorRGB(*self.brand)
            pf = c.beginPath()
            pf.moveTo(x + 0.5 * mm, y + 2.9 * mm)
            pf.lineTo(x + 0.5 * mm, y - 0.4 * mm)
            pf.lineTo(x + 3.1 * mm, y + 1.25 * mm)
            pf.close()
            c.drawPath(pf, fill=1, stroke=0)
            c.setFillColorRGB(*INK)
            c.setFont("Helvetica", 9.5)
            for ln in simpleSplit(str(zeile[1]), "Helvetica", 9.5, inhalt_w - _PUNKT_EINZUG) or [""]:
                c.drawString(x + _PUNKT_EINZUG, y, ln)
                y -= _LH
            return y - 1.6 * mm
        return y - _LH

    def karte(self, spalte, karte, voll=False):
        """Zeichnet eine Themen-Box (spalte 0=links, 1=rechts; voll=volle Breite);
        bricht bei Platzmangel auf eine neue Seite um."""
        c = self.c
        w = (self.W - 2 * self.marge) if voll else self.karten_w
        h = _karte_hoehe(karte, w)
        top = min(self.col_y) if voll else self.col_y[spalte]
        if top - h < self.fuss_h:
            self.seite_abschliessen()
            self._kopf()
            top = self.col_y[0]
        x = self.marge if voll else self.marge + spalte * (self.karten_w + self.spalt)
        # Schatten + Box
        c.setFillColorRGB(*SCHATTEN)
        c.roundRect(x + 1.1 * mm, top - h - 1.1 * mm, w, h, 2 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(*RAND)
        c.setLineWidth(0.8)
        c.roundRect(x, top - h, w, h, 2 * mm, fill=1, stroke=1)
        # Titelzeile: App-Icon + zentrierter Titel, darunter Markenlinie
        titel = karte["titel"]
        c.setFont("Helvetica-Bold", 11)
        titel_w = c.stringWidth(titel, "Helvetica-Bold", 11)
        icon = _icon_reader(karte.get("icon"), self.ev.marke) if karte.get("icon") else None
        ih = 5.2 * mm
        gesamt = titel_w + (ih + 2 * mm if icon else 0)
        sx = x + (w - gesamt) / 2
        if icon:
            c.drawImage(icon, sx, top - 7.6 * mm, width=ih, height=ih, mask="auto")
            sx += ih + 2 * mm
        c.setFillColorRGB(*INK)
        c.drawString(sx, top - 6 * mm, titel)
        c.setStrokeColorRGB(*self.brand)
        c.setLineWidth(0.9)
        c.line(x + 3 * mm, top - 8.6 * mm, x + w - 3 * mm, top - 8.6 * mm)
        # Inhalt
        ix = x + 4 * mm
        iy = top - 13.5 * mm
        inhalt_w = w - 8 * mm
        for z in karte["zeilen"]:
            iy = self._zeile_zeichnen(z, ix, iy, inhalt_w)
        neu_y = top - h - 5 * mm
        if voll:
            self.col_y = [neu_y, neu_y]
        else:
            self.col_y[spalte] = neu_y


def build_briefing_pdf(ev, dienstleister, externe=None, regeln=None) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    seite = _Seite(c, ev)
    seite.neue_seite("Briefing")

    # ── Karten links ────────────────────────────────────────────────────────────
    datum_zeit = {
        "titel": "Datum & Uhrzeit", "icon": "zeitplan",
        "zeilen": [
            ("kv", "Datum", de_date(ev.datum), False),
            ("kv", "Aktionszeit",
             f"{ev.startzeit} – {ev.endzeit} Uhr" if ev.endzeit else (ev.startzeit or "–"), False),
            ("kv", "Ankunft", _ankunft.ankunft_anzeige(ev), True),
            ("kv", "Treffpunkt", _ankunft.treffpunkt_anzeige(ev), True),
        ],
    }

    ap_name = (_clean(getattr(ev, "cl_ansprechpartner_name", "")) or _clean(ev.kunde_kontakt))
    ap_tel = (_clean(getattr(ev, "cl_ansprechpartner_mobil", "")) or _clean(ev.kunde_telefon))
    ansprechpartner = {
        "titel": "Ansprechpartner Kunde", "icon": "nachricht",
        "zeilen": [
            ("kv", "Name", ap_name, False),
            ("kv", "Telefon", ap_tel, False),
            ("text", "Kontakt zum Kunden läuft NUR über die Teamleitung."),
        ],
    }

    team_zeilen = []
    sortiert = sorted(dienstleister,
                      key=lambda m: 0 if (ev.teamleiter_id and m.id == ev.teamleiter_id) else 1)
    for m in sortiert:
        is_tl = bool(ev.teamleiter_id and m.id == ev.teamleiter_id)
        team_zeilen.append(("team", f"{m.vorname} {m.nachname}", m.telefon, is_tl,
                            sparte_label(m)))
    for e in (externe or []):
        team_zeilen.append(("team", e.name, e.telefon, False, "(extern)"))
    if not team_zeilen:
        team_zeilen.append(("text", "Noch kein Team eingetragen."))
    team = {"titel": "Team", "icon": "team", "zeilen": team_zeilen}

    aktionen = {"titel": "Aktionen", "icon": "kreativaktion",
                "zeilen": [("text", _clean(ev.produkte) or "–")]}

    # ── Karten rechts ───────────────────────────────────────────────────────────
    an_firma = (_clean(getattr(ev, "cl_firma_name", "")) or _clean(ev.kunde_firma)).strip()
    an_strasse = _clean(getattr(ev, "cl_strasse", "")).strip()
    an_plz_ort = _clean(getattr(ev, "cl_plz_ort", "")).strip()
    if not an_strasse and not an_plz_ort:
        an_plz_ort = _clean(ev.veranstaltungsort).strip()
    adresse = {
        "titel": "Veranstaltungsadresse", "icon": "standort",
        "zeilen": [("text", "\n".join(z for z in (an_firma, an_strasse, an_plz_ort) if z) or "–")],
    }

    standort_zeilen = []
    if _clean(ev.cl_aufbauort):
        standort_zeilen.append(("kv", "Aufbauort", ev.cl_aufbauort, False))
    if _clean(ev.cl_parkplatz):
        standort_zeilen.append(("kv", "Parkplätze", ev.cl_parkplatz, False))
    standort = ({"titel": "Standort & Parken", "icon": "fahrzeug", "zeilen": standort_zeilen}
                if standort_zeilen else None)

    rahmen_zeilen = []
    if _clean(ev.cl_teamkleidung):
        rahmen_zeilen.append(("kv", "Teamkleidung", ev.cl_teamkleidung, False))
    # Steht immer im Briefing: angemessene Kleidung zur Familienveranstaltung
    rahmen_zeilen.append(("text", "Dazu bitte eine zur Familienveranstaltung passende, "
                                  "gepflegte Hose / Rock / Shorts tragen."))
    if _clean(ev.cl_verpflegung):
        rahmen_zeilen.append(("kv", "Verpflegung", ev.cl_verpflegung, False))
    rahmen = {"titel": "Dresscode & Verpflegung", "icon": "einsatz", "zeilen": rahmen_zeilen}

    besonderes_text = "\n\n".join(t for t in (
        _clean(ev.hinweise).strip(),
        _clean(getattr(ev, "cl_weitere_details", "")).strip()) if t)
    besonderes = ({"titel": "Besonderes", "icon": "dokument",
                   "zeilen": [("text", besonderes_text)]} if besonderes_text else None)

    # ── Zeichnen: links dann rechts (Lesereihenfolge der Textextraktion bleibt so) ──
    for k in (datum_zeit, ansprechpartner, team, aktionen):
        seite.karte(0, k)
    for k in (adresse, standort, rahmen, besonderes):
        if k:
            seite.karte(1, k)
    seite.seite_abschliessen()

    # ── Seite „Allgemeines": Regeln-Boxen (nur wenn Regeln gepflegt) ──────────────
    abschnitte = regeln_abschnitte(regeln or "", ev.marke)
    if abschnitte:
        seite.neue_seite("Allgemeines")
        for titel, punkte in abschnitte:
            seite.karte(0, {"titel": titel, "icon": "checkliste",
                            "zeilen": [("punkt", p) for p in punkte]}, voll=True)
        # Freundlicher Abschluss (wie in der bisherigen Vorlage)
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(seite.W / 2, seite.col_y[0] - 8 * mm,
                            "Wir danken für euren Einsatz und wünschen viel Spaß!")
        seite.seite_abschliessen()

    c.save()
    buf.seek(0)
    return buf.read()
