"""
Wird täglich von Render Cron um 18:00 Uhr (lokal) aufgerufen.
Erinnert bestätigte Dienstleister 2 Tage vor ihrem Einsatz.
"""
import os
import urllib.request

secret = os.environ.get("CRON_SECRET", "")
url = "https://kindsalabim-events.onrender.com/cron/einsatz-erinnerung"

# Secret per Header statt Query-String – landet so nicht in Server-Logs (Roadmap 2.3).
req = urllib.request.Request(url, headers={"X-Cron-Secret": secret})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
        print(f"Cron OK: {body}")
except Exception as e:
    print(f"Cron Fehler: {e}")
    raise
