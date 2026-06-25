# Tests

Schlanke Regressions-Suite für die kritischen Abläufe. Läuft **nur lokal** gegen eine
Wegwerf-SQLite-DB; alle externen Effekte (Mailversand, Google-Kalender, R2-Uploads)
sind zu No-ops gemockt. **Die Prod-DB wird nie berührt, es gehen nie echte Mails/Kalendereinträge raus.**

## Ausführen

```bash
pip install -r requirements-dev.txt    # einmalig
python -m pytest tests/ -q             # alle Tests
python -m pytest tests/test_events.py  # einzelne Datei
```

Unter Windows ggf. `PYTHONUTF8=1` voranstellen (Umlaute in Testdaten).

## Was abgedeckt ist (Kern-Invarianten)

- **Events** – Validierung, Pflichtfeld-Entschärfung, „Abgesagt" frei speicherbar, keine `None`-Vorbelegung, Material-Info (Auswahl/Sonstige)
- **Logistik** – Anfrage-Flag, Portal-Transportantwort, Logistiker-Zuweisung, `auto_status`, „Material bereit", 3-Tage-Cron
- **Briefing** – PDF-Download (gültiges PDF, Team + Externe), Einmal-Teamer anlegen/löschen, Rechnung/Footer je Marke, Maske-Vorbelegung aus dem Event
- **Reservierungen** – zeitgebundener Kalendereintrag, Wunschformat, Ganztags-Fallback, Liste mit Uhrzeit
- **Eventbericht** – „Wie gelaufen" Mehrfachauswahl, Foto-Feld (Galerie/Mehrfach)
- **Dienstleister** – Team-Shirt-Häkchen
- **Kalender-Helfer** – Titelformat, Stadt-Extraktion, +1 h

## Prinzip

Nur **stabile Invarianten** testen (Daten, Validierung, Format, Geld/PDF), nicht volatile
UI-Details – damit die Suite bei normaler Weiterentwicklung nicht ständig „failt".
