"""Baker-Ross-Katalog-Ingest.

Liest die offizielle Produkt-Sitemap (robots-konform freigegeben) und pflegt daraus
die lokale Tabelle `BastelProdukt`. Kein KI-Live-Scraping; die Preise werden separat
und nur für kuratierte Treffer von der Produktseite nachgeladen (bakerross_service).

Aufruf:
    python ingest_bakerross.py            # lädt die Sitemap und aktualisiert den Katalog
    python ingest_bakerross.py --file x.xml   # nutzt eine lokal gespeicherte Sitemap
Die DB-Verbindung folgt der App (DATABASE_URL / lokale events.db).
"""
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx

PRODUCT_SITEMAP = "https://www.bakerross.de/media/feeds/br_sitemaps/DE/DE_sitemap_product.xml"
# Eigener User-Agent (kein KI-Crawler), respektvoller First-Party-Abruf.
USER_AGENT = "KindsalabimKatalog/1.0 (+https://kindsalabim-events.onrender.com; Bastelset-Recherche)"

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
IMG = "{http://www.google.com/schemas/sitemap-image/1.1}"


def _load_sitemap(file: str | None) -> bytes:
    if file:
        with open(file, "rb") as f:
            return f.read()
    resp = httpx.get(PRODUCT_SITEMAP, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.content


def parse_sitemap(xml_bytes: bytes) -> list[dict]:
    """Sitemap -> Liste {url, name, beschreibung, bild_url, lastmod}."""
    root = ET.fromstring(xml_bytes)
    produkte = []
    for url_el in root.findall(f"{SM}url"):
        loc = url_el.findtext(f"{SM}loc")
        if not loc:
            continue
        lastmod = url_el.findtext(f"{SM}lastmod")
        name = None
        beschreibung = ""
        bild_url = None
        for img in url_el.findall(f"{IMG}image"):
            img_loc = img.findtext(f"{IMG}loc") or ""
            title = (img.findtext(f"{IMG}title") or "").strip()
            caption = (img.findtext(f"{IMG}caption") or "").strip()
            if title and not name:
                name = title
            # Längste Caption = beste Beschreibung
            if len(caption) > len(beschreibung):
                beschreibung = caption
            # Erstes echtes Produktbild (YouTube-Vorschaubilder überspringen)
            if not bild_url and img_loc and "youtube" not in img_loc.lower():
                bild_url = img_loc
        if not name:
            # Fallback: Name aus dem Slug ableiten
            name = loc.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        produkte.append({
            "url": loc, "name": name, "beschreibung": beschreibung,
            "bild_url": bild_url, "lastmod": lastmod,
        })
    return produkte


def ingest_catalog(db, file: str | None = None) -> dict:
    """Upsert in BastelProdukt. Vorhandene Preise bleiben erhalten."""
    from models import BastelProdukt
    produkte = parse_sitemap(_load_sitemap(file))
    jetzt = datetime.now().isoformat(timespec="seconds")
    vorhandene = {p.url: p for p in db.query(BastelProdukt).all()}
    neu = aktualisiert = 0
    for p in produkte:
        bestehend = vorhandene.get(p["url"])
        if bestehend:
            bestehend.name = p["name"]
            bestehend.beschreibung = p["beschreibung"]
            bestehend.bild_url = p["bild_url"]
            bestehend.lastmod = p["lastmod"]
            bestehend.aktiv = True
            bestehend.aktualisiert_am = jetzt
            aktualisiert += 1
        else:
            db.add(BastelProdukt(
                url=p["url"], name=p["name"], beschreibung=p["beschreibung"],
                bild_url=p["bild_url"], lastmod=p["lastmod"], aktiv=True,
                erstellt_am=jetzt, aktualisiert_am=jetzt,
            ))
            neu += 1
    db.commit()
    return {"gesamt": len(produkte), "neu": neu, "aktualisiert": aktualisiert,
            "datum": date.today().isoformat()}


if __name__ == "__main__":
    from database import SessionLocal, engine, Base
    import models  # registriert alle Tabellen an Base.metadata
    Base.metadata.create_all(bind=engine)
    file = None
    if "--file" in sys.argv:
        file = sys.argv[sys.argv.index("--file") + 1]
    db = SessionLocal()
    try:
        result = ingest_catalog(db, file=file)
        print("Katalog aktualisiert:", result)
    finally:
        db.close()
