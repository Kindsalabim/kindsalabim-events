"""
Wird täglich von Render Cron um 18:00 Uhr (lokal) aufgerufen.
Erinnert bestätigte Dienstleister 2 Tage vor ihrem Einsatz.
"""
import os
import urllib.request

secret = os.environ.get("CRON_SECRET", "")
url = f"https://kindsalabim-events.onrender.com/cron/einsatz-erinnerung?secret={secret}"

try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read().decode()
        print(f"Cron OK: {body}")
except Exception as e:
    print(f"Cron Fehler: {e}")
    raise
