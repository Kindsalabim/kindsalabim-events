"""
Wird wöchentlich (montags 8:00 Uhr) von Render Cron aufgerufen.
Stößt den CSV-Backup-Export (Events + Dienstleister) per E-Mail an den Admin an.
"""
import os
import urllib.request

secret = os.environ.get("CRON_SECRET", "")
url = "https://kindsalabim-events.onrender.com/cron/backup"

# Secret per Header statt Query-String – landet so nicht in Server-Logs (Roadmap 2.3).
req = urllib.request.Request(url, method="POST", headers={"X-Cron-Secret": secret})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
        print(f"Backup OK: {body}")
except Exception as e:
    print(f"Backup Fehler: {e}")
    raise
