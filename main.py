from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base
from routes.admin import router as admin_router
from routes.portal import router as portal_router
from routes.checklist import router as checklist_router
from routes.cron import router as cron_router
from routes.buchhaltung import router as buchhaltung_router
from routes.import_jira import router as import_router
from routes.fotos import router as fotos_router
from routes.angebot import router as angebot_router
from routes.wissen import admin_router as wissen_admin_router, portal_router as wissen_portal_router
from routes.tickets import router as tickets_router
from routes.crm import router as crm_router

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
        ("magic_token",              "VARCHAR"),
        ("magic_token_expires",      "VARCHAR"),
        ("logistiker",               "BOOLEAN DEFAULT 0"),
        ("fuehrerschein",            "BOOLEAN DEFAULT 0"),
        ("qualitaet",                "INTEGER"),
        ("gebiet",                   "VARCHAR"),
        ("verfuegbarkeit",           "VARCHAR"),
        ("vertragstyp",              "VARCHAR"),
        ("stundensatz_teamer",       "FLOAT"),
        ("stundensatz_kuenstler",    "FLOAT"),
        ("dsgvo_unterzeichnet",      "BOOLEAN DEFAULT 0"),
        ("website",                  "VARCHAR"),
        ("notizen",                  "TEXT"),
    ]
    for col, typedef in dl_columns:
        add_column("dienstleister", col, typedef)

    vf_columns = [
        ("frist_datum",          "VARCHAR"),
        ("frist_verlaengert",    "BOOLEAN DEFAULT 0"),
        ("erinnerung_gesendet",  "BOOLEAN DEFAULT 0"),
        ("einsatz_erinnerung_gesendet", "BOOLEAN DEFAULT 0"),
    ]
    for col, typedef in vf_columns:
        add_column("verfuegbarkeitsanfragen", col, typedef)

    new_columns = [
        ("marke",                    "VARCHAR DEFAULT 'Kindsalabim'"),
        ("material_mitnahme",        "BOOLEAN DEFAULT 0"),
        ("material_bestellt",        "BOOLEAN DEFAULT 0"),
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
        ("rechnung_gestellt",        "BOOLEAN DEFAULT 0"),
        ("bericht_eingereicht_am",   "VARCHAR"),
        ("bericht_anzahl_kinder",    "INTEGER"),
        ("bericht_verlauf",          "TEXT"),
        ("bericht_probleme",         "TEXT"),
        ("bericht_kundenfeedback",   "TEXT"),
    ]
    for col, typedef in new_columns:
        add_column("events", col, typedef)

    rechnungen_columns = [
        ("steuer_erledigt", "BOOLEAN DEFAULT 0"),
    ]
    for col, typedef in rechnungen_columns:
        add_column("rechnungen", col, typedef)

    wissen_columns = [
        ("parent_id",  "INTEGER"),
        ("cover_bild", "VARCHAR"),
    ]
    for col, typedef in wissen_columns:
        add_column("wissensartikel", col, typedef)

    add_column("tickets", "extern_key", "VARCHAR")

    add_column("events", "kunde_id", "INTEGER")
    add_column("events", "kalender_event_id", "VARCHAR")
    add_column("dienstleister", "onboarding_abgeschlossen", "BOOLEAN DEFAULT 0")
    add_column("events", "teamleiter_mail_gesendet", "BOOLEAN DEFAULT 0")

    # Datums-Spalten von Text "TT.MM.JJJJ" auf echten DATE-Typ migrieren
    def convert_date_column(table: str, col: str):
        """VARCHAR 'TT.MM.JJJJ' -> echter DATE-Typ. Idempotent & crash-sicher."""
        with engine.connect() as conn:
            try:
                if is_postgres:
                    dtype = conn.execute(text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name=:t AND column_name=:c"
                    ), {"t": table, "c": col}).scalar()
                    if dtype in ("character varying", "text"):
                        conn.execute(text(
                            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE date USING "
                            f"CASE WHEN {col} ~ '^[0-9]{{2}}\\.[0-9]{{2}}\\.[0-9]{{4}}$' "
                            f"THEN to_date({col}, 'DD.MM.YYYY') ELSE NULL END"
                        ))
                else:
                    # SQLite ist lose typisiert -> Werte auf ISO 'JJJJ-MM-TT' umschreiben
                    conn.execute(text(
                        f"UPDATE {table} SET {col} = "
                        f"substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2) "
                        f"WHERE {col} LIKE '__.__.____'"
                    ))
                    conn.execute(text(f"UPDATE {table} SET {col} = NULL WHERE {col} = ''"))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Datums-Migration {table}.{col} übersprungen: {e}")

    convert_date_column("events", "datum")
    convert_date_column("verfuegbarkeitsanfragen", "frist_datum")

def migrate_kunden():
    """Legt aus den losen Event-Kundendaten echte Kundenprofile an und verknüpft sie.

    Idempotent: verarbeitet nur Events ohne kunde_id. Matching über Firmennamen
    (case-insensitiv); existierende Kunden mit Event-Historie gelten als 'gebucht'.
    """
    from database import SessionLocal
    from models import Event, Kunde
    from datetime import datetime
    db = SessionLocal()
    try:
        events = db.query(Event).filter(Event.kunde_id == None).all()  # noqa: E711
        if not events:
            return
        kunden = {k.firma.strip().lower(): k
                  for k in db.query(Kunde).all() if k.firma}
        jetzt = datetime.now().isoformat(timespec="seconds")
        for ev in events:
            firma = (ev.kunde_firma or "").strip()
            if not firma:
                continue
            k = kunden.get(firma.lower())
            if not k:
                k = Kunde(
                    firma=firma,
                    ansprechpartner=(ev.kunde_kontakt or "").strip() or None,
                    telefon=(ev.kunde_telefon or "").strip() or None,
                    email=(ev.kunde_email or "").strip() or None,
                    marke=ev.marke or "Kindsalabim",
                    pipeline_status="gebucht",
                    erstellt_am=jetzt, aktualisiert_am=jetzt,
                )
                db.add(k); db.flush()
                kunden[firma.lower()] = k
            ev.kunde_id = k.id
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Kunden-Migration übersprungen: {e}")
    finally:
        db.close()


def seed_admin():
    """Übernimmt den bestehenden Config/ENV-Admin einmalig in die admins-Tabelle."""
    from database import SessionLocal
    from models import Admin
    from config import get_config
    from datetime import datetime
    cfg = get_config()
    db = SessionLocal()
    try:
        if db.query(Admin).count() == 0 and cfg.get("admin_email") and cfg.get("admin_password_hash"):
            db.add(Admin(
                email=cfg["admin_email"], name="Admin",
                password_hash=cfg["admin_password_hash"], aktiv=True,
                erstellt_am=datetime.now().isoformat(timespec="seconds"),
            ))
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    migrate_kunden()
    seed_admin()
    yield

app = FastAPI(title="Knallfrosch Events", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin_router)
app.include_router(portal_router)
app.include_router(checklist_router)
app.include_router(cron_router)
app.include_router(buchhaltung_router)
app.include_router(import_router)
app.include_router(fotos_router)
app.include_router(angebot_router)
app.include_router(wissen_admin_router)
app.include_router(wissen_portal_router)
app.include_router(tickets_router)
app.include_router(crm_router)

@app.get("/")
def root():
    return RedirectResponse("/admin/dashboard")
