"""Pytest-Setup für die Kindsalabim-Events-App.

SICHERHEIT: läuft ausschließlich gegen eine Wegwerf-SQLite-DB und mockt alle
externen Effekte (Mailversand, Google-Kalender, R2-Uploads) zu No-ops. Es werden
NIE echte Mails/Kalendereinträge/Uploads erzeugt und die Prod-DB nie berührt.
"""
import os
import tempfile

# DB + Secrets VOR dem App-Import setzen (database.py liest DATABASE_URL beim Import)
_DB = os.path.join(tempfile.gettempdir(), "kf_pytest.db")
if os.path.exists(_DB):
    try:
        os.remove(_DB)
    except OSError:
        pass
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ.setdefault("SECRET_KEY", "pytest-secret")
for _k in ("DEMO_MODE", "RESEND_API_KEY", "GOOGLE_CALENDAR_CREDENTIALS"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from main import app  # noqa: E402
from database import SessionLocal, engine, Base  # noqa: E402
import models  # noqa: E402,F401  (Modelle registrieren)
from auth import create_token  # noqa: E402
import calendar_service  # noqa: E402
import email_service  # noqa: E402
import routes.fotos as fotos_routes  # noqa: E402

# ── Externe Effekte hart abschalten ──────────────────────────────────────────
calendar_service._service = lambda: None          # Kalender = No-op
_MAILS = []
email_service._deliver = lambda to, subject, html, anhaenge=None: _MAILS.append((to, subject, html))
_UPLOADS = []
fotos_routes._upload = lambda data, event_id, filename, content_type, typ, db: _UPLOADS.append(filename)

# Schema einmalig anlegen (Tests nutzen auch direkte DB-Sessions)
Base.metadata.create_all(bind=engine)
main.run_migrations()


@pytest.fixture
def client():
    """Frischer TestClient pro Test (eigene Cookies, Lifespan idempotent)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    client.cookies.set("admin_token", create_token({"sub": "a@b.de", "role": "admin"}, expires_minutes=60))
    return client


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def mails():
    """Abgefangene Mails (Liste von (to, subject, html)); pro Test geleert."""
    _MAILS.clear()
    return _MAILS


@pytest.fixture
def uploads():
    _UPLOADS.clear()
    return _UPLOADS


def login_portal(client, dienstleister_id):
    """Setzt den Portal-Login-Cookie für einen Dienstleister."""
    client.cookies.set("portal_token",
                       create_token({"sub": str(dienstleister_id), "role": "dienstleister"}, expires_minutes=60))
    return client
