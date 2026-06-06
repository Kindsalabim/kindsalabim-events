from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base
from routes.admin import router as admin_router
from routes.portal import router as portal_router
from routes.checklist import router as checklist_router
from routes.cron import router as cron_router

def run_migrations():
    """Fügt fehlende Spalten zur bestehenden Datenbank hinzu (SQLite & PostgreSQL)."""
    from sqlalchemy import text

    is_postgres = engine.dialect.name == "postgresql"

    def add_column(table: str, col: str, typedef: str):
        # Postgres kennt kein "BOOLEAN DEFAULT 0" – nur true/false.
        if is_postgres:
            typedef = typedef.replace("DEFAULT 0", "DEFAULT false")
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"
        # Frische Verbindung pro Spalte: ein Fehler bricht so nicht die Folge-ALTERs ab.
        with engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                conn.rollback()  # Spalte existiert bereits (SQLite wirft hier)

    dl_columns = [
        ("magic_token",         "VARCHAR"),
        ("magic_token_expires", "VARCHAR"),
        ("logistiker",          "BOOLEAN DEFAULT 0"),
        ("fuehrerschein",       "BOOLEAN DEFAULT 0"),
    ]
    for col, typedef in dl_columns:
        add_column("dienstleister", col, typedef)

    vf_columns = [
        ("frist_datum",          "VARCHAR"),
        ("frist_verlaengert",    "BOOLEAN DEFAULT 0"),
        ("erinnerung_gesendet",  "BOOLEAN DEFAULT 0"),
    ]
    for col, typedef in vf_columns:
        add_column("verfuegbarkeitsanfragen", col, typedef)

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
    for col, typedef in new_columns:
        add_column("events", col, typedef)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    yield

app = FastAPI(title="Knallfrosch Events", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin_router)
app.include_router(portal_router)
app.include_router(checklist_router)
app.include_router(cron_router)

@app.get("/")
def root():
    return RedirectResponse("/admin/dashboard")
