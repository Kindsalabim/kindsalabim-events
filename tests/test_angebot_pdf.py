"""Angebots-PDF: die finale Komprimierung (_compress_pdf) macht das PDF mailbar,
ohne Seiten zu verlieren, und fällt bei Problemen sicher auf das Original zurück."""
import io

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageFilter
from pypdf import PdfReader

from routes.angebot import _compress_pdf


def _bloated_pdf(n_pages=2) -> bytes:
    """Erzeugt ein absichtlich schweres PDF: großes, verlustfrei eingebettetes Foto-ähnliches
    Bild (verwischtes Rauschen) pro Seite – so wie die echten Bildmaterial-Vorlagen."""
    W, H = landscape(A4)
    img = Image.effect_noise((2400, 1700), 64).convert("RGB").filter(ImageFilter.GaussianBlur(3))
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))
    for _ in range(n_pages):
        c.drawImage(ImageReader(img), 0, 0, width=W, height=H)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_compress_verkleinert_und_erhaelt_seitenzahl():
    src = _bloated_pdf(2)
    out = _compress_pdf(src)
    assert out[:4] == b"%PDF"
    assert len(out) < len(src)                            # spürbar kleiner
    assert len(PdfReader(io.BytesIO(out)).pages) == 2     # gleiche Seitenzahl


def test_compress_fallback_bei_unlesbaren_bytes():
    assert _compress_pdf(b"kein pdf") == b"kein pdf"


# ── Titel der individuellen Seiten (groß, links, auto-verkleinert) ─────────────

def test_titel_kurz_volle_groesse():
    from routes.angebot import _fit_titel_size, TITEL_SIZE
    assert _fit_titel_size("Glitzertattoos") == TITEL_SIZE


def test_titel_lang_verkleinert_und_passt_ins_banner():
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from routes.angebot import (_fit_titel_size, TITEL_SIZE, TITEL_MIN_SIZE,
                                TITEL_FONT, TITEL_LINKS, TITEL_RECHTS)
    t = "Spezielle Bastelaktionen Bakerross Deluxe Premium"
    size = _fit_titel_size(t)
    assert TITEL_MIN_SIZE <= size < TITEL_SIZE
    if size > TITEL_MIN_SIZE:   # nur wenn nicht auf die Untergrenze geklemmt
        assert stringWidth(t.upper(), TITEL_FONT, size) <= (TITEL_RECHTS - TITEL_LINKS) + 1


def test_custom_page_baut_gueltiges_einseitiges_pdf():
    from routes.angebot import _build_custom_page
    pdf = _build_custom_page("Test-Titel", [], "Kindsalabim")
    assert pdf[:4] == b"%PDF"
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
