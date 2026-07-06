from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base, SessionLocal
from config import get_config
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
from routes.bakerross import router as bakerross_router
from routes.papierkorb import router as papierkorb_router
from routes.benachrichtigungen import router as benachrichtigungen_router

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
        ("teamshirt_kindsalabim",    "BOOLEAN DEFAULT 0"),
        ("teamshirt_knallfrosch",    "BOOLEAN DEFAULT 0"),
        ("qualitaet",                "INTEGER"),
        ("kuenstler_sparte",         "VARCHAR"),
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
    add_column("events", "serien_id", "VARCHAR")
    add_column("events", "bericht_erinnerung_am", "VARCHAR")
    add_column("events", "bericht_kinder", "VARCHAR")
    add_column("events", "checkliste_uebersprungen", "BOOLEAN DEFAULT 0")
    add_column("events", "zaubershow_event", "BOOLEAN DEFAULT 0")
    add_column("events", "material_info", "TEXT")
    add_column("events", "transporter_angeboten", "BOOLEAN DEFAULT 0")
    add_column("events", "logistiker_id", "INTEGER")
    add_column("events", "material_bereit", "BOOLEAN DEFAULT 0")
    add_column("events", "material_bereit_gesendet", "BOOLEAN DEFAULT 0")
    add_column("events", "material_abhol_erinnerung_gesendet", "BOOLEAN DEFAULT 0")
    add_column("events", "material_erinnerung_gesendet", "BOOLEAN DEFAULT 0")
    add_column("events", "kunde_adresse", "TEXT")
    add_column("events", "vor_ort_name", "VARCHAR")
    add_column("events", "vor_ort_telefon", "VARCHAR")
    add_column("verfuegbarkeitsanfragen", "als_logistiker", "BOOLEAN DEFAULT 0")
    add_column("verfuegbarkeitsanfragen", "logistik_transport", "VARCHAR")
    add_column("events", "cl_weitere_details", "TEXT")
    add_column("events", "ankunft_modus", "VARCHAR DEFAULT 'auto'")
    add_column("events", "ankunft_text", "TEXT")
    add_column("events", "treffpunkt", "VARCHAR")
    add_column("reservierungen", "startzeit", "VARCHAR")
    add_column("reservierungen", "endzeit", "VARCHAR")
    add_column("reservierungen", "art", "VARCHAR DEFAULT 'Div.'")
    add_column("admins", "notifications_gesehen_bis", "VARCHAR")
    add_column("bastel_produkte", "stueckzahl", "INTEGER")
    add_column("bastel_vorschlaege", "stueckzahl", "INTEGER")

    # Status-Modell vereinheitlicht: "Entwurf"/"Bestätigt" gibt es nicht mehr → "Gebucht".
    with engine.connect() as conn:
        try:
            conn.execute(text("UPDATE events SET status='Gebucht' WHERE status IN ('Entwurf','Bestätigt')"))
            conn.commit()
        except Exception:
            conn.rollback()

    # Eindeutigkeit: höchstens eine Anfrage je (Event, Dienstleister). (Review M4)
    # Tolerant: enthält die Prod-DB historische Doppel-Anfragen (genau der alte Bug),
    # schlägt die Index-Erzeugung fehl und wird übersprungen – ohne den Start zu blockieren.
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_anfrage_event_dl "
                              "ON verfuegbarkeitsanfragen (event_id, dienstleister_id)"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[MIGRATION] ux_anfrage_event_dl übersprungen (evtl. Alt-Duplikate): {e}")

    # Indizes auf häufig gefilterten Spalten (Review Gruppe 4). Idempotent + tolerant –
    # bei aktueller Datenmenge kaum spürbar, aber Vorsorge fürs Wachstum.
    def add_index(name: str, table: str, cols: str):
        with engine.connect() as conn:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
                conn.commit()
            except Exception:
                conn.rollback()

    add_index("ix_anfrage_dl_status", "verfuegbarkeitsanfragen", "dienstleister_id, status")
    add_index("ix_anfrage_status",    "verfuegbarkeitsanfragen", "status")
    add_index("ix_events_datum",      "events", "datum")
    add_index("ix_events_status",     "events", "status")
    add_index("ix_events_serien_id",  "events", "serien_id")
    add_index("ix_events_kalender",   "events", "kalender_event_id")
    add_index("ix_dl_magic_token",    "dienstleister", "magic_token")

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
    if get_config().get("demo_mode") and engine.dialect.name != "postgresql":
        from seed_demo import seed_demo_data
        seed_demo_data()  # seedt nur, wenn DB leer (frischer Start)
    yield

app = FastAPI(title="Knallfrosch Events", lifespan=lifespan)


# ── CSRF-Schutz: Same-Origin-Check auf allen POSTs (Roadmap 2.2) ─────────────────
# Browser senden bei Formular-POSTs einen Origin- (oder Referer-)Header. Kommt der
# von einem fremden Hostnamen, wird die Anfrage geblockt – eine fremde Website kann
# so keine Aktionen im Namen eines eingeloggten Nutzers auslösen. Ergänzt das
# bestehende samesite=lax auf den Cookies. Anfragen ganz ohne Origin/Referer
# (Cron-Skripte, Nicht-Browser-Clients) bleiben erlaubt.
@app.middleware("http")
async def same_origin_guard(request, call_next):
    if request.method == "POST":
        herkunft = request.headers.get("origin") or request.headers.get("referer") or ""
        if herkunft:
            host = (request.headers.get("host") or "").split(":")[0].lower()
            quell_host = (urlparse(herkunft).hostname or "").lower()
            # Ist ein Origin/Referer gesetzt, MUSS er zum eigenen Host passen.
            # Ein nicht-parsebarer Wert (z. B. "Origin: null" aus einem sandboxed
            # iframe) ergibt quell_host="" → wird nun abgelehnt statt durchgelassen.
            if host and quell_host != host:
                return PlainTextResponse("Anfrage abgelehnt (Cross-Site-Schutz).", status_code=403)
    return await call_next(request)


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
app.include_router(bakerross_router)
app.include_router(papierkorb_router)
app.include_router(benachrichtigungen_router)

# Glocken-Badge (notif_unread) auf allen Admin-Seiten verfügbar machen –
# jede Route hat eine eigene Jinja2Templates-Umgebung, daher zentral registrieren.
from notifications import admin_notif_unread
import routes.admin, routes.crm, routes.buchhaltung, routes.wissen, routes.tickets
import routes.papierkorb, routes.import_jira, routes.angebot, routes.bakerross, routes.benachrichtigungen
for _mod in (routes.admin, routes.crm, routes.buchhaltung, routes.wissen, routes.tickets,
             routes.papierkorb, routes.import_jira, routes.angebot, routes.bakerross,
             routes.benachrichtigungen):
    try:
        _mod.templates.env.globals["notif_unread"] = admin_notif_unread
    except Exception:
        pass

@app.get("/")
def root():
    # In der Demo direkt eingeloggt in die Admin-Ansicht starten (kein Login-Umweg)
    if _demo_on():
        return RedirectResponse("/demo/login/admin")
    return RedirectResponse("/admin/dashboard")


# ── Demo-Umgebung (nur aktiv bei DEMO_MODE) ──────────────────────────────────────

def _demo_on():
    # Sicherheits-Riegel (Review H2): Der Demo-Modus – passwortlose Logins + Daten-Reset –
    # wirkt NIE gegen eine PostgreSQL-DB. Selbst wenn DEMO_MODE versehentlich am Prod-Service
    # (Postgres) gesetzt würde, bleiben alle Demo-Routen inert (404). Die echte Demo läuft
    # bewusst auf SQLite.
    if engine.dialect.name == "postgresql":
        return False
    return bool(get_config().get("demo_mode"))


@app.post("/demo/reset")
def demo_reset():
    """Setzt alle Demo-Daten auf den Ausgangsstand zurück."""
    if not _demo_on():
        raise HTTPException(404)
    from seed_demo import seed_demo_data
    seed_demo_data(reset=True)
    return RedirectResponse("/admin/dashboard?demo_reset=1", status_code=303)


@app.get("/demo/login/admin")
def demo_login_admin():
    """Ein-Klick-Login als Demo-Admin (kein Passwort nötig)."""
    if not _demo_on():
        raise HTTPException(404)
    from auth import create_token, COOKIE_SECURE
    from seed_demo import DEMO_ADMIN_EMAIL
    token = create_token({"role": "admin", "email": DEMO_ADMIN_EMAIL})
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie("admin_token", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60 * 60 * 8)
    return resp


@app.get("/demo/login/portal")
def demo_login_portal():
    """Ein-Klick-Login als Demo-Dienstleister (Portal-Perspektive)."""
    if not _demo_on():
        raise HTTPException(404)
    from auth import create_token, COOKIE_SECURE
    from seed_demo import DEMO_TEAMER_EMAIL, seed_demo_data
    from models import Dienstleister
    db = SessionLocal()
    try:
        d = db.query(Dienstleister).filter(Dienstleister.email == DEMO_TEAMER_EMAIL).first()
        if not d:
            seed_demo_data()
            d = db.query(Dienstleister).filter(Dienstleister.email == DEMO_TEAMER_EMAIL).first()
        did = d.id if d else 0
    finally:
        db.close()
    token = create_token({"sub": str(did), "role": "dienstleister"}, expires_minutes=60 * 24 * 30)
    resp = RedirectResponse("/portal", status_code=303)
    resp.set_cookie("portal_token", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp
