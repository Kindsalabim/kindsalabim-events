"""
Wird wöchentlich (montags 8:00 Uhr) von Render Cron aufgerufen.
Stößt den CSV-Backup-Export (Events + Dienstleister) per E-Mail an den Admin an.
"""
import os
import urllib.request

secret = os.environ.get("CRON_SECRET", "")
url = f"https://kindsalabim-events.onrender.com/cron/backup?secret={secret}"

req = urllib.request.Request(url, method="POST")
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
        print(f"Backup OK: {body}")
except Exception as e:
    print(f"Backup Fehler: {e}")
    raise
