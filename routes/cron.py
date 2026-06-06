import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from models import Verfuegbarkeitsanfrage, Event, Dienstleister
from config import get_config

# Produkte die 3 Wochen vorher eine Material-Erinnerung brauchen
MATERIAL_PRODUKTE = ["Spezielle Bastelaktionen (Bakerross)", "Bakerross", "B-Cross"]

router = APIRouter(prefix="/cron")


def _check_secret(secret: str = "") -> bool:
    cfg = get_config()
    return secret == cfg.get("cron_secret", "")


@router.get("/erinnerung")
def send_erinnerungen(secret: str = "", db: Session = Depends(get_db)):
    """Wird täglich von Render Cron aufgerufen. Sendet Erinnerungen 24h vor Fristablauf."""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    today = datetime.today()
    morgen = (today + timedelta(days=1)).strftime("%d.%m.%Y")

    offene = db.query(Verfuegbarkeitsanfrage).filter(
        Verfuegbarkeitsanfrage.status == "Ausstehend",
        Verfuegbarkeitsanfrage.frist_datum == morgen,
        Verfuegbarkeitsanfrage.erinnerung_gesendet == False
    ).all()

    from email_service import send_erinnerung
    count = 0
    for a in offene:
        try:
            send_erinnerung(a.dienstleister, a.event)
            a.erinnerung_gesendet = True
            count += 1
        except Exception as e:
            print(f"Erinnerung fehlgeschlagen für {a.dienstleister.email}: {e}")

    db.commit()

    # Material-Erinnerungen: 3 Wochen vor Event wenn Bakerross-Produkt gebucht
    in_3_wochen = (today + timedelta(weeks=3)).strftime("%d.%m.%Y")
    material_events = db.query(Event).filter(Event.datum == in_3_wochen).all()
    material_count = 0
    from email_service import send_material_erinnerung
    cfg = get_config()
    for ev in material_events:
        if ev.produkte:
            braucht_material = any(p.strip() in ev.produkte for p in MATERIAL_PRODUKTE)
            if braucht_material:
                try:
                    send_material_erinnerung(ev, cfg["admin_email"])
                    material_count += 1
                except Exception as e:
                    print(f"Material-Erinnerung fehlgeschlagen: {e}")

    return JSONResponse({"erinnerungen_gesendet": count, "material_erinnerungen": material_count, "datum": morgen})


def _model_to_csv(rows, model) -> bytes:
    """Exportiert alle Zeilen eines Modells als CSV (alle Spalten, ; getrennt, UTF-8 mit BOM für Excel)."""
    cols = [c.name for c in model.__table__.columns]
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([getattr(r, c) for c in cols])
    return buf.getvalue().encode("utf-8-sig")


@router.post("/backup")
def send_backup(secret: str = "", db: Session = Depends(get_db)):
    """Wird wöchentlich (montags) von Render Cron aufgerufen. Schickt einen CSV-Export
    aller Events + Dienstleister als E-Mail-Anhang an den Admin."""
    if not _check_secret(secret):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    events = db.query(Event).all()
    dienstleister = db.query(Dienstleister).all()

    datum = datetime.today().strftime("%Y-%m-%d")
    attachments = [
        (f"events_{datum}.csv", _model_to_csv(events, Event)),
        (f"dienstleister_{datum}.csv", _model_to_csv(dienstleister, Dienstleister)),
    ]

    from email_service import send_backup
    try:
        send_backup(attachments, len(events), len(dienstleister))
    except Exception as e:
        print(f"Backup-E-Mail fehlgeschlagen: {e}")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    return JSONResponse({"status": "ok", "events": len(events), "dienstleister": len(dienstleister)})
