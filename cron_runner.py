"""
Wird täglich von Render Cron um 8:00 Uhr aufgerufen.
Sendet Erinnerungs-E-Mails an Dienstleister deren Anfrage-Frist morgen abläuft.
"""
import os
import urllib.request

secret = os.environ.get("CRON_SECRET", "")
url = f"https://kindsalabim-events.onrender.com/cron/erinnerung?secret={secret}"

try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read().decode()
        print(f"Cron OK: {body}")
except Exception as e:
    print(f"Cron Fehler: {e}")
    raise
