from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from database import engine, Base
from routes.admin import router as admin_router
from routes.portal import router as portal_router
from routes.checklist import router as checklist_router
from routes.cron import router as cron_router

def run_migrations():
    """Fügt fehlende Spalten zur bestehenden Datenbank hinzu."""
    from sqlalchemy import text
    # Neue Spalten in Dienstleister
    dl_columns = [
        ("magic_token",         "VARCHAR"),
        ("magic_token_expires", "VARCHAR"),
    ]
    with engine.connect() as conn:
        for col, typedef in dl_columns:
            try:
                conn.execute(text(f"ALTER TABLE dienstleister ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass

    # Neue Spalten in Verfuegbarkeitsanfragen
    vf_columns = [
        ("frist_datum",          "VARCHAR"),
        ("frist_verlaengert",    "BOOLEAN DEFAULT 0"),
        ("erinnerung_gesendet",  "BOOLEAN DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for col, typedef in vf_columns:
            try:
                conn.execute(text(f"ALTER TABLE verfuegbarkeitsanfragen ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass

    new_columns = [
        ("marke",                    "VARCHAR DEFAULT 'Kindsalabim'"),
        ("checklist_token",          "VARCHAR"),
        ("cl_ansprechpartner_name",  "VARCHAR"),
        ("cl_ansprechpartner_mobil", "VARCHAR"),
        ("cl_firma_name",            "VARCHAR"),
        ("cl_strasse",               "VARCHAR"),
        ("cl_plz_ort",               "VARCHAR"),
        ("cl_aufbau_von",            "VARCHAR"),
        ("cl_aufbau_bis",            "VARCHAR"),
        ("cl_abbau_von",             "VARCHAR"),
        ("cl_abbau_bis",             "VARCHAR"),
        ("cl_aufbauort",             "VARCHAR"),
        ("cl_verpflegung",           "VARCHAR"),
        ("cl_teamkleidung",          "VARCHAR"),
        ("cl_parkplatz",             "TEXT"),
        ("cl_eingereicht_am",        "VARCHAR"),
    ]
    with engine.connect() as conn:
        for col, typedef in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE events ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass  # Spalte existiert bereits

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    yield

app = FastAPI(title="Knallfrosch Events", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(portal_router)
app.include_router(checklist_router)
app.include_router(cron_router)

@app.get("/")
def root():
    return RedirectResponse("/admin/dashboard")
