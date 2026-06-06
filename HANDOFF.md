# HANDOFF – Kindsalabim Events App

> **Zweck dieses Dokuments:** Vollständige Übergabe für eine neue Claude-Session.
> Lies dieses Dokument zuerst, dann `BERICHT_UND_ROADMAP.md`. Damit bist du vollständig im Bild.
> *Letzte Aktualisierung: 06.06.2026 (nach PostgreSQL-Migration)*

---

## 0. Sofort-Kontext (in 30 Sekunden)

- **Was:** Web-App für Event-Management von Kinderevents, zwei Marken (Kindsalabim = blau `#003864`, Knallfrosch = grün `#1a7a1a`).
- **Stack:** FastAPI + **PostgreSQL** (SQLAlchemy) + Jinja2 + Tailwind (CDN). Kein Build-Step, kein Node.
- **Betreiber:** Aykut (a.malca@kindsalabim.de). Kein IT-Profi, aber versiert, lernt schnell. Kommuniziert auf Deutsch.
- **Hosting:** Render (Auto-Deploy bei git push auf `master`).
- **AKTUELLE AUFGABE:** Backup-Strategie einrichten (Phase 1.2). Render-Backups bereits aktiv; wöchentlicher CSV-Export per Cron noch offen. Siehe Abschnitt 6.

---

## 1. Projekt-Fakten

| | |
|---|---|
| Projektpfad | `C:\Users\aykut\Documents\Claude\Projects\knallfrosch-app` |
| GitHub | https://github.com/Kindsalabim/kindsalabim-events (Branch `master`) |
| Live-URL | https://kindsalabim-events.onrender.com |
| Admin-Login | a.malca@kindsalabim.de / Nba1987- |
| Lokaler Start | siehe Abschnitt 4 |
| OS | Windows, PowerShell (python3.13) |

---

## 2. Architektur & Dateien

```
knallfrosch-app/
├── main.py              # App-Einstieg, Router-Registrierung, DB-Migrationen (ad-hoc ALTER TABLE)
├── config.py            # Lädt config.yaml; ENV-Variablen überschreiben Werte (für Render)
├── config.yaml          # Secrets lokal (GITIGNORED – nicht im Repo!)
├── database.py          # SQLAlchemy Engine + Session (sqlite:///./events.db)
├── models.py            # Event, Dienstleister, Verfuegbarkeitsanfrage
├── auth.py              # JWT-Tokens, bcrypt, Magic-Link-Funktionen
├── email_service.py     # SMTP-Versand + alle E-Mail-Templates (HTML, mit Logos)
├── distance.py          # PLZ→Koordinaten (hardcoded ~250 PLZ) + rank_contractors()
├── logo_b64.py          # Logos als Base64 (GENERIERT, für E-Mail-Einbettung)
├── cron_runner.py       # Wird von Render-Cron aufgerufen → ruft /cron/erinnerung
├── setup.py             # Einmaliges Admin-Passwort-Setup-Skript
├── render.yaml          # Render-Konfig: Webservice + Cron-Service
├── requirements.txt
├── routes/
│   ├── admin.py         # Admin-Bereich (Events, Dienstleister, Anfragen, Briefing, auto_status())
│   ├── portal.py        # Dienstleister-Portal (Magic Link, Zu-/Absagen, Frist verlängern)
│   ├── checklist.py     # Öffentliche Kunden-Checkliste (Token-basiert, kein Login)
│   └── cron.py          # /cron/erinnerung – Erinnerungen + Material-Reminder
├── templates/
│   ├── base.html        # Basis-Layout + alle CSS-Klassen + Brand-Variablen
│   ├── admin_base.html  # Admin-Layout mit Sidebar (mobile Hamburger)
│   ├── admin/           # login, dashboard, event_detail, event_form, contractors, contractor_form
│   ├── portal/          # login, dashboard
│   └── checklist.html   # Kunden-Formular (branded nach Event-Marke)
└── static/img/          # logo-kindsalabim.png, logo-knallfrosch.png
```

### Datenmodell (models.py)
- **Event:** Stammdaten + Checklisten-Felder (`cl_*`) + `checklist_token` + `marke` + `status`.
- **Dienstleister:** Stammdaten + `logistiker`, `fuehrerschein`, `magic_token`, `password_hash` (Legacy).
- **Verfuegbarkeitsanfrage:** Verknüpft Event↔Dienstleister, `status` (Ausstehend/Ja/Nein), `frist_datum`, `frist_verlaengert`, `erinnerung_gesendet`.

### Wichtige Logik
- **`routes/admin.py → auto_status(ev, db)`**: Berechnet Event-Status automatisch. Wird bei Anfrage-Versand, Checklisten-Versand, Checklisten-Eingang und Dienstleister-Antwort aufgerufen.
- **`distance.py → rank_contractors()`**: Sortiert nach Entfernung, dann Erfahrung, dann Mobilität. (Logistiker-Priorität noch NICHT eingebaut – Roadmap.)

---

## 3. Konfiguration & Secrets

### config.yaml (lokal, GITIGNORED)
```yaml
smtp_host: "secure.emailsrvr.com"   # Jimdo
smtp_port: 465                       # SSL (SMTP_SSL, nicht STARTTLS)
smtp_user: "info@kindsalabim.de"
smtp_password: "!819gtIt&Owc6TPg-+"
smtp_from: "info@kindsalabim.de"
cron_secret: "ks-cron-2026"          # SCHWACH – Roadmap: härten
admin_email: "a.malca@kindsalabim.de"
admin_password_hash: "$2b$12$qbYxmQYGFjfKPO5v9pVZxOWarR9JwypoTtDYNqgCtZtC65X75mCi6"
secret_key: "cbc98c08464b3ed76ac7e0acf2804bf38da3464f909872b4b7c45595c199da20"
```

### Render Environment Variables (bereits gesetzt)
`SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SECRET_KEY, ADMIN_PASSWORD_HASH, CRON_SECRET`
→ `config.py` mappt ENV → config-Keys. Bei neuen Secrets (z. B. `DATABASE_URL`) hier ergänzen.

### E-Mail
- Jimdo SMTP, Port 465 = `smtplib.SMTP_SSL`. Funktioniert & getestet.
- Test-Route: `GET /admin/test-email` (eingeloggt) sendet Test-Mail an Admin.
- Logos sind als Base64 in jede Mail eingebettet (`logo_b64.py`), Knallfrosch-Logo bei Knallfrosch-Events.

---

## 4. Lokaler Entwicklungs-Workflow

**Server starten (PowerShell, bindet an alle Interfaces für Handy-Zugriff):**
```powershell
Get-Process | Where-Object { $_.Name -match "python" } | Stop-Process -Force
Set-Location "C:\Users\aykut\Documents\Claude\Projects\knallfrosch-app"
Start-Process python3.13 -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8001" -WindowStyle Normal
```
- Lokal: http://127.0.0.1:8001
- Vom Handy (gleiches WLAN): http://192.168.0.147:8001 (IP kann wechseln: `Get-NetIPAddress -AddressFamily IPv4`)
- Port 8001 ist Konvention in diesem Projekt.

**Deployen:**
```bash
git add . && git commit -m "..." && git push origin master
```
→ Render deployt automatisch. Commit-Messages auf Deutsch, mit `Co-Authored-By: Claude ...`.

---

## 5. Was bereits FERTIG ist (✅)

**Kern:**
- Admin-Login (JWT, 8h), Event CRUD, Dienstleister CRUD
- Multi-Brand (Kindsalabim/Knallfrosch pro Event), durchgängige Brand-Farben
- Entfernungs-Ranking der Dienstleister (PLZ-basiert)

**Design/UX:**
- Mobile-first, Hamburger-Sidebar mit Slide-in-Overlay
- Event-Karten mit Status-Farbbalken, Stats-Row, Info-Pills mit Icons
- Logos überall (App, Login, Portal, Checkliste, E-Mails)

**E-Mail (SMTP Jimdo, live):**
- Verfügbarkeitsanfrage, Briefing, Magic Link, Einladung, Erinnerung, Material-Erinnerung, Checklisten-Mail + Admin-Benachrichtigung
- Alle mit HTML-Layout + Logo im Header

**Dienstleister-Portal:**
- Magic-Link-Login (KEIN Passwort): E-Mail → Link (24h gültig) → 30-Tage-Session
- Anfragen mit Countdown, "Ich kann"/"Nicht da", "Frist verlängern" (+2 Tage)
- Meine Jobs / Abgesagt / Vergangene Jobs

**Kunden-Checkliste:**
- `/checklist/{token}` öffentlich, branded nach Marke, kein Login
- Felder exakt wie alte PDF-Checkliste; Admin sieht Eingaben im Event-Detail
- Admin bekommt Benachrichtigungs-Mail bei Eingang

**Frist-System & Status-Automatik:**
- 3-Tage-Frist pro Anfrage, Erinnerung 24h vorher (Cron)
- Material-Erinnerung 3 Wochen vorher bei Bakerross-Produkten
- Status: Event eingepflegt → DL angefragt → Checkliste geschickt/eingegangen → Planung fertig → Briefing gesendet → Abgeschlossen
- Logistiker-Feld + Führerschein-Feld beim Dienstleister (LKW-Icon)

**Infrastruktur:**
- Render Auto-Deploy + Cron-Service (täglich 08:00 → /cron/erinnerung)
- `.gitignore` schützt config.yaml + *.db

---

## 6. AKTUELLE AUFGABE: Backup-Strategie (Phase 1, Schritt 2)

### ✅ Phase 1.1 – PostgreSQL-Migration (ERLEDIGT, 06.06.2026)
- Render PostgreSQL Basic-256mb (Virginia) angelegt.
- `database.py`: `DATABASE_URL` aus ENV, Fallback auf SQLite für lokal.
  - Dialekt-Fix: `postgres://` → `postgresql://` → `postgresql+psycopg://` (psycopg3).
- `requirements.txt`: `psycopg[binary]>=3.1` (psycopg3, Python 3.14-kompatibel).
- `main.py`: Migrationen Postgres-sicher (`DEFAULT false`, `ADD COLUMN IF NOT EXISTS`).
- `render.yaml`: `DATABASE_URL` bei Web- und Cron-Service.
- Persistenz-Test ✅: Event überlebt Redeploy.

### Phase 1.2 – Backup-Strategie (JETZT)
**Was bereits aktiv ist:** Render Basic PostgreSQL enthält automatische tägliche Backups (Point-in-Time-Recovery, 7-Tage-Retention). Das ist der Hauptschutz.

**Was noch fehlt:** Menschenlesbarer Notfall-Export — falls Render komplett ausfällt oder jemand versehentlich alle Events löscht, will Aykut eine CSV in seiner E-Mail haben.

**Plan:**
1. Neuen Cron-Endpunkt `/cron/backup` (in `routes/cron.py`) bauen.
2. Exportiert alle Events + Dienstleister als CSV.
3. Schickt CSV per E-Mail an Admin (`a.malca@kindsalabim.de`) — wöchentlich, montags 08:00.
4. Render-Cron-Service (`render.yaml`) um einen zweiten Cron-Job erweitern.

---

## 7. Roadmap (Kurzfassung – Details in BERICHT_UND_ROADMAP.md)

**Phase 1 – Fundament (JETZT):**
1. ✅ PostgreSQL (erledigt 06.06.2026) · 2. ⏳ Backups (aktuelle Aufgabe) · 3. Cookie-Security (`secure`+`samesite`) · 4. Datum→Date-Typ

**Phase 2 – Robustheit & Automatisierung:**
5. Abgelaufene Anfragen auto-behandeln · 6. Logistiker-Pflicht & -Priorität im Ranking ·
7. Auto-Nachbesetzung bei Absage · 8. Cron-Secret härten + Checklisten-Token absichern · 9. Geocoding statt PLZ-Liste

**Phase 3 – Komfort:**
10. Dashboard-Filter/Suche, Datepicker, Toasts · 11. Material-/Logistik-Cockpit · 12. Mehrbenutzer-Admin

**Phase 4 – KI-Module (eigene Teilprojekte):**
13. KI-Angebotsunterstützung (BakerRoss: Thema→4-5 Vorschläge mit EK/VK×1,8/Bild) ·
14. KI-Angebots-PDF (Angebot hochladen → KI erkennt Produkte → schöne Bilder-PDF)
    - Referenz-Beispiel der manuellen PDF: `C:\Users\aykut\Desktop\Bildmaterial Erstellung Angebot\output\Hydrogenics GmbH.pdf`

---

## 8. Arbeitsweise mit Aykut (wichtig)

- **Sprache:** Deutsch.
- **Stil:** Proaktiv auf bessere Wege / Risiken hinweisen (steht so in seiner CLAUDE.md). Nicht um Erlaubnis fragen bei Offensichtlichem – kurz hinweisen und machen.
- **Er ist kein Entwickler:** Bei Schritten, die er selbst tun muss (Render, Dateien), konkrete Klick-für-Klick-Anleitungen geben. Bei config-Dateien anbieten, es selbst einzutragen.
- **Er testet gern live** auf PC und Handy – nach Änderungen Server neu starten und URL nennen.
- **Commit & Push** nur Teil des Flows, wenn Feature fertig & getestet. Immer config.yaml/DB aus Commits raushalten (ist gitignored).
- Er arbeitet auch spät/lange – pragmatisch weitermachen, wenn er "weiter" sagt.

---

## 9. Bekannte Stolpersteine

- **Server-Neustart:** Mehrere python-Prozesse können hängen → erst alle killen (`Stop-Process`), dann starten. Port 8001 sonst belegt.
- **Bash-Tool auf Windows:** Pfade mit Spaces/Quotes machen im Bash-Tool Probleme → PowerShell-Tool nutzen für Prozess-/Datei-Operationen.
- **LF→CRLF-Warnungen** bei git add sind harmlos (Windows).
- **logo_b64.py** ist generiert – bei Logo-Änderung neu erzeugen (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes(...))`).
- **config.py cached** die Config in `_cfg` (Modul-global). Bei config-Änderungen Server neu starten.
