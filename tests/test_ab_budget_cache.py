"""AB-Budget-Cache: das AB-PDF wird pro Datei nur EINMAL aus R2 geladen und geparst –
nicht bei jedem Event-Seitenaufruf neu (Render-RAM-Limit 31.07.2026)."""
from datetime import datetime

import routes.fotos as fotos
from database import SessionLocal
from models import EventDatei
from factories import make_event


def _ab_datei(eid, key):
    s = SessionLocal()
    try:
        s.add(EventDatei(event_id=eid, r2_key=key, filename="ab.pdf",
                         typ="auftragsbestaetigung",
                         uploaded_at=datetime.now().isoformat(timespec="seconds")))
        s.commit()
    finally:
        s.close()


def test_ab_pdf_wird_nur_einmal_geladen(admin, monkeypatch):
    calls = []
    monkeypatch.setattr(fotos, "download_file",
                        lambda k: calls.append(k) or b"%PDF-1.4 fake")
    eid = make_event(produkte="Kinderschminken")
    _ab_datei(eid, f"ab/test-cache-{eid}.pdf")

    admin.get(f"/admin/events/{eid}")
    assert len(calls) == 1
    admin.get(f"/admin/events/{eid}")
    admin.get(f"/admin/events/{eid}")
    assert len(calls) == 1   # weitere Aufrufe kommen aus dem Cache
