from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from database import engine, Base
from routes.admin import router as admin_router
from routes.portal import router as portal_router

def run_migrations():
    """Fügt fehlende Spalten zur bestehenden Datenbank hinzu."""
    from sqlalchemy import text
    with engine.connect() as conn:
        # marke-Spalte hinzufügen falls nicht vorhanden
        try:
            conn.execute(text("ALTER TABLE events ADD COLUMN marke VARCHAR DEFAULT 'Kindsalabim'"))
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

@app.get("/")
def root():
    return RedirectResponse("/admin/dashboard")
