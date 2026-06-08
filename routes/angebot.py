"""Angebots-PDF-Generator.

Ablauf:
  1. Admin wählt Marke (Kindsalabim / Knallfrosch)
  2. Admin wählt Aktionen per Checkbox
  3. Admin fügt optional Custom-Seiten hinzu (Überschrift + Fotos)
  4. POST → PDF wird zusammengebaut und als Download zurückgegeben
"""
import base64
import io
from pypdf import PdfReader, PdfWriter
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from auth import get_admin_user
from config import get_config
from routes.fotos import _r2_client

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


# ── Aktionen-Katalog ────────────────────────────────────────────────────────────
# key = interner Name, label = Anzeigename
# datei_kf = R2-Schlüssel für Knallfrosch, datei_ks = R2-Schlüssel für Kindsalabim

AKTIONEN = [
    {"key": "bastelspass",      "label": "Bastelspaß",           "kf": "1Bastelspass.pdf",              "ks": "1Bastelspass Kindsalabim.pdf"},
    {"key": "prickelaktion",    "label": "Prickelaktion",         "kf": "2Prickelaktion.pdf",            "ks": "2Prickelaktion Kindsalabim.pdf"},
    {"key": "buttonaktion",     "label": "Buttonaktion",          "kf": "3Buttonaktion.pdf",             "ks": "3Buttonaktion Kindsalabim.pdf"},
    {"key": "glitzertattoos",   "label": "Glitzertattoos",        "kf": "4Glitzertattoos.pdf",           "ks": "4Glitzertattoos Kindsalabim.pdf"},
    {"key": "kinderschminken",  "label": "Kinderschminken",       "kf": "5Kinderschminken.pdf",          "ks": "5Kinderschminken Kindsalabim.pdf"},
    {"key": "ballonmodellage",  "label": "Ballonmodellage",       "kf": "6Ballonmodellage.pdf",          "ks": "6Ballonmodellage Kindsalabim.pdf"},
    {"key": "spieleland",       "label": "Spieleland",            "kf": "7Spieleland.pdf",               "ks": "7Spieleland Kindsalabim.pdf"},
    {"key": "minimitmachzirkus","label": "Mini-Mitmachzirkus",    "kf": "8MiniMitmachzirkus.pdf",        "ks": "8MiniMitmachzirkus Kindsalabim.pdf"},
    {"key": "mitmachzirkus",    "label": "Mitmachzirkus",         "kf": "9Mitmachzirkus.pdf",            "ks": "9Mitmachzirkus Kindsalabim.pdf"},
    {"key": "seifenblasen",     "label": "Seifenblasen",          "kf": "10Seifenblasen.pdf",            "ks": "10Seifenblasen Kindsalabim.pdf"},
    {"key": "zaubershow",       "label": "Zaubershow",            "kf": "11Zaubershow.pdf",              "ks": "11Zaubershow Kindsalabim.pdf"},
    {"key": "fotoaktion",       "label": "Fotoaktion",            "kf": "12Fotoaktion.pdf",              "ks": "12Fotoaktion Kindsalabim.pdf"},
    {"key": "u3spieleland",     "label": "U3 Spieleland",         "kf": "13U3Spieleland.pdf",            "ks": None},
    {"key": "team",             "label": "Team-Seite",            "kf": "Z Team.pdf",                    "ks": "Z Team Kindsalabim.pdf"},
]

TITELSEITE = {"kf": "0Titelseite.pdf", "ks": "0 Titelseite Kindsalabim.pdf"}

BRAND_COLOR = {"Kindsalabim": "#1D4E89", "Knallfrosch": "#1a7a1a"}
BRAND_COLOR_RGB = {
    "Kindsalabim": (29/255, 78/255, 137/255),
    "Knallfrosch": (26/255, 122/255, 26/255),
}


def _fetch_r2(key: str) -> bytes | None:
    cfg = get_config()
    client = _r2_client()
    if not client:
        return None
    try:
        resp = client.get_object(Bucket=cfg["r2_bucket"], Key=f"aktionen/{key}")
        return resp["Body"].read()
    except Exception:
        return None


def _logo_bytes(marke: str) -> bytes | None:
    """Gibt das aktuelle Logo als PNG-Bytes zurück."""
    try:
        from logo_b64 import KS_B64, KF_B64
        b64 = KF_B64 if marke == "Knallfrosch" else KS_B64
        return base64.b64decode(b64)
    except Exception:
        return None


BLANKO = {
    "Kindsalabim": "Kindsalabim Blanko.pdf",
    "Knallfrosch":  "Knallfrosch Blanko.pdf",
}


def _build_custom_page(titel: str, foto_bytes_list: list[bytes], marke: str) -> bytes:
    """Custom-Seite: Blanko-Template aus R2 + Titel/Fotos als Overlay.

    Koordinaten der weißen Quadrate (gemessen via PyMuPDF, konvertiert in
    Reportlab-Koordinaten, Ursprung unten-links):
      Links:  x=55.5,  y=138.55, w=321.5, h=288.0
      Rechts: x=464.9, y=138.55, w=321.5, h=288.0
    """
    W, H = landscape(A4)  # 841.89 x 595.28 pt

    PAD = 8  # Innenabstand vom Rahmen
    SLOTS = [
        (55.5  + PAD, 138.55 + PAD, 321.5 - PAD * 2, 288.0 - PAD * 2),  # links
        (464.9 + PAD, 138.55 + PAD, 321.5 - PAD * 2, 288.0 - PAD * 2),  # rechts
    ]

    # Titelbereich: oberhalb der Fotos (y=426.5 bis y=595.28 in Reportlab)
    # Mitte dieses Bereichs ≈ y=500; weiße Schrift auf dem Pinselstrich-Hintergrund
    TITEL_Y = 490

    overlay_buf = io.BytesIO()
    c = rl_canvas.Canvas(overlay_buf, pagesize=(W, H))

    # Titel
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 30)
    text_w = c.stringWidth(titel, "Helvetica-Bold", 30)
    c.drawString((W - text_w) / 2, TITEL_Y, titel)

    fotos = foto_bytes_list[:2]
    for i, fb in enumerate(fotos):
        x, y, w, h = SLOTS[i]
        _draw_foto(c, fb, x, y, w, h)

    c.save()
    overlay_buf.seek(0)

    # ── Template + Overlay zusammenführen ─────────────────────────────────────
    template_bytes = _fetch_r2(BLANKO[marke])
    if template_bytes:
        try:
            template_reader = PdfReader(io.BytesIO(template_bytes))
            overlay_reader  = PdfReader(overlay_buf)
            page = template_reader.pages[0]
            page.merge_page(overlay_reader.pages[0])
            writer = PdfWriter()
            writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            return out.read()
        except Exception as e:
            print(f"Template-Merge Fehler: {e}")

    # Fallback: nur Overlay ohne Template
    overlay_buf.seek(0)
    return overlay_buf.read()


MAX_PX = 1200  # Maximale Pixelbreite/-höhe für eingebettete Fotos


def _draw_foto(c, foto_bytes: bytes, x: float, y: float, w: float, h: float):
    try:
        img = Image.open(io.BytesIO(foto_bytes)).convert("RGB")
        # Auf MAX_PX verkleinern, falls größer
        if img.width > MAX_PX or img.height > MAX_PX:
            img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        buf.seek(0)
        reader = ImageReader(buf)
        iw, ih = reader.getSize()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        dx = x + (w - dw) / 2
        dy = y + (h - dh) / 2
        c.drawImage(reader, dx, dy, width=dw, height=dh)
    except Exception as e:
        print(f"Foto-Fehler: {e}")


# ── Routes ──────────────────────────────────────────────────────────────────────

@router.get("/angebot", response_class=HTMLResponse)
def angebot_form(request: Request, _=Depends(get_admin_user)):
    return templates.TemplateResponse("admin/angebot.html", {
        "request": request,
        "aktionen": AKTIONEN,
        "cfg": get_config(),
    })


@router.post("/angebot/erstellen")
async def angebot_erstellen(request: Request, _=Depends(get_admin_user)):
    import json
    form = await request.form()

    marke = form.get("marke", "Kindsalabim")
    kundenname = form.get("kundenname", "").strip()
    aktionen_keys = form.getlist("aktionen_keys")
    custom_titel = form.getlist("custom_titel")

    # foto_index: Liste mit Seitenindex pro Foto (z.B. [0,0,1] = 2 Fotos für Seite 0, 1 für Seite 1)
    try:
        foto_index = json.loads(form.get("foto_index", "[]"))
    except Exception:
        foto_index = []

    # Alle hochgeladenen Fotos lesen und nach Seite gruppieren
    foto_gruppen: dict[int, list[bytes]] = {}
    all_uploads = form.getlist("custom_fotos")
    for i, upload in enumerate(all_uploads):
        if not hasattr(upload, "read"):
            continue
        data = await upload.read()
        if not data:
            continue
        page_idx = foto_index[i] if i < len(foto_index) else 0
        foto_gruppen.setdefault(page_idx, []).append(data)

    pages_data: list[bytes] = []

    # 1. Titelseite
    tk = TITELSEITE["ks"] if marke == "Kindsalabim" else TITELSEITE["kf"]
    titel_bytes = _fetch_r2(tk)
    if titel_bytes:
        pages_data.append(titel_bytes)

    # 2. Gewählte Aktionen
    aktion_map = {a["key"]: a for a in AKTIONEN}
    for key in aktionen_keys:
        a = aktion_map.get(key)
        if not a:
            continue
        datei = a["ks"] if marke == "Kindsalabim" else a["kf"]
        if not datei:
            continue
        pdf_bytes = _fetch_r2(datei)
        if pdf_bytes:
            pages_data.append(pdf_bytes)

    # 3. Custom-Seiten
    for i, titel in enumerate(custom_titel):
        if not titel.strip():
            continue
        fotos = foto_gruppen.get(i, [])
        custom_pdf = _build_custom_page(titel.strip(), fotos, marke)
        pages_data.append(custom_pdf)

    # 4. Alle Seiten zusammenkleben
    if not pages_data:
        return HTMLResponse("<p>Keine Seiten ausgewählt.</p>", status_code=400)

    writer = PdfWriter()
    for pdf_bytes in pages_data:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        except Exception:
            continue

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)

    import re
    safe_name = re.sub(r'[^\w\-]', '_', kundenname) if kundenname else marke
    filename = f"{safe_name}_Bildmaterial_Angebot.pdf"
    return StreamingResponse(
        out_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
