"""Wöchentliches CSV-Backup deckt jetzt auch Rechnungen + Kunden ab (nicht nur
Events + Dienstleister). Login-Geheimnisse bleiben ausgeschlossen (Review H1)."""
from datetime import date

import routes.cron as cron
import email_service
from database import SessionLocal
from models import Rechnung, Kunde

CRON_CFG = {"cron_secret": "bk-secret", "admin_email": "a@b.de"}


def test_backup_enthaelt_rechnungen_und_kunden(client, monkeypatch):
    s = SessionLocal()
    try:
        s.add(Rechnung(datum=date.today(), kunde="Backup-Kunde", rgnr="RE-BK-1", brutto=100.0))
        s.add(Kunde(firma="Backup CRM GmbH"))
        s.commit()
    finally:
        s.close()

    monkeypatch.setattr(cron, "get_config", lambda: CRON_CFG)
    captured = {}
    monkeypatch.setattr(email_service, "send_backup",
                        lambda attachments, counts: captured.update(a=attachments, c=counts))

    r = client.post("/cron/backup", headers={"X-Cron-Secret": "bk-secret"})
    assert r.status_code == 200

    fnames = [fn for fn, _ in captured["a"]]
    assert any(f.startswith("events_") for f in fnames)
    assert any(f.startswith("dienstleister_") for f in fnames)
    assert any(f.startswith("rechnungen_") for f in fnames)     # NEU
    assert any(f.startswith("kunden_") for f in fnames)         # NEU
    assert captured["c"]["Rechnungen"] >= 1 and captured["c"]["Kunden"] >= 1


def test_backup_ohne_secret_gesperrt(client, monkeypatch):
    monkeypatch.setattr(cron, "get_config", lambda: CRON_CFG)
    assert client.post("/cron/backup").status_code == 401
