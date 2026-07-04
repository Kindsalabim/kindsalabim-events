# CLAUDE.md – Kindsalabim Events App (knallfrosch-app)

FastAPI + SQLAlchemy 2.0 + PostgreSQL (Render, Auto-Deploy bei Push auf `master`) /
lokal SQLite-Fallback · Jinja2 SSR · Tailwind per CDN (KEIN Build-Step, kein Node).
Betreiber: Aykut (kein IT-Profi, versiert) – Erklärungen auf Deutsch, für Schritte die
er selbst tun muss (Render/Secrets) Klick-für-Klick-Anleitungen.

**Zuerst lesen:** `HANDOFF_SESSION.md` (granulare Historie) · `BERICHT_UND_ROADMAP.md`
(Audit + Reststand Code-Review 07/2026) · Obsidian: `KINDSALABIM\11 Knallfrosch-Event-App\
Event-App – Entwicklungsdokumentation.md`.

## Sicherheitsregeln (STRIKT)

- **NIE Live-Endpoints auslösen**: kein echtes Mailen/Posten/Kalender-Schreiben/R2-Upload.
  Tests laufen gegen Wegwerf-SQLite mit gemockten Effekten (`tests/conftest.py`).
- ⚠️ **Die lokale `config.yaml` enthält einen ECHTEN Resend-Key.** Ein lokal gestarteter
  Server verschickt also echte Mails! Für Browser-Previews IMMER `email_service._deliver`
  und `calendar_service._service` patchen + `DATABASE_URL` auf eine Wegwerf-SQLite setzen
  (`run_preview_demo.py` mockt die Mails NICHT – eigenen Safe-Launcher bauen).
- Prod-DB / echte `events.db` nie anfassen. Demo-Routen sind gegen PostgreSQL inert
  (`main._demo_on`).
- Vor JEDEM Push: `PYTHONUTF8=1 python -m pytest tests/ -q` – alles grün.
- Commit/Push nur auf explizite Freigabe von Aykut. **Doku-Änderungen (\*.md) nicht
  pushen** – jeder Push löst einen Render-Rebuild aus.
- Keine neuen Dependencies ohne Begründung (müssen auf Render/Py3.13 bauen; pikepdf
  baut dort z. B. NICHT – pypdf/pymupdf nutzen).

## Architektur-Wegweiser

- `routes/admin.py` – Herzstück: `auto_status()` (Status-Automatik; „Abgeschlossen"/
  „Abgesagt" sind final und werden NIE auto-überschrieben), `_workflow_steps()`
  (Chevron-Leiste), `event_gesperrt()`/`GESPERRTE_STATUS`, Anfrage-Versand.
- `routes/cron.py` – Erinnerungen. Konvention: **Zeitfenster statt exakter Stichtage**
  + „gesendet"-Flag + Commit PRO Mail mit Rollback (Review 07/2026). Zeit IMMER über
  `_jetzt()`/`_heute()` (deutsche Ortszeit – Render läuft in UTC!).
- `email_service.py` – alle Mails (Resend HTTP-API; Render blockt SMTP). Nutzereingaben
  IMMER mit `_esc()` escapen (zentral in `_info_row`/`_team_row`, Freitexte einzeln).
- `briefing_pdf.py` – Briefing-PDF im „Briefing 2.0"-Kartenraster (siehe Design-Sprache).
- `choices.py` – geteilte Konstanten: `RECHNUNGS_ANSCHRIFT` (eine Quelle für Portal/
  Mail/PDF), `SPARTE_BRIEFING`, `BRIEFING_REGELN_DEFAULT` + `regeln_abschnitte()`
  (Regeln-Parser: `## ` = neue Box, `{MARKE}` wird ersetzt), `ANFRAGE_FRIST_TAGE`
  (in email_service definiert – Frist-Text UND DB-Frist aus einer Quelle).
- `main.py` – Ad-hoc-Migrationen (`add_column` idempotent, kein Alembic – bewusst),
  Same-Origin-CSRF-Middleware, Demo-Modus.
- Auth: JWT-Cookies (`admin_token`/`portal_token`), Magic-Link fürs Portal.
  Checklisten-Token: 30 Tage nach Event abgelaufen, Einreichung nur einmal.

## Konventionen & Stolperfallen

- **Deutsch überall**: Kommentare, Commit-Messages (kurzer Titel + Stichpunkte),
  Test-Namen (`test_teamleiter_kann_...`), UI-Texte glasklar (Dienstleister = GenZ,
  teils niedrige Lesekompetenz).
- Jede Route braucht `Depends(get_admin_user)` bzw. `get_portal_user` – Portal-Routen
  zusätzlich Ownership-Check (`dienstleister_id == did`). Datei-Routen: `typ`-Check
  (Portal darf NUR `bericht_foto` anfassen – Auftragsbestätigung ist tabu).
- Jedes Router-Modul hat eine EIGENE Jinja2Templates-Instanz → Filter/Globals pro
  Modul registrieren (zentrale Registrierung siehe `main.py` unten).
- `Event.datum` ist echtes `Date`; einige Legacy-Felder sind Strings ("HH:MM",
  `cl_eingereicht_am` deutsch formatiert). `erstellt_am` der Anfragen ist dt. String.
- Serien-Events: jeder Tag = eigenes Event, verknüpft über `serien_id`. Neuer
  nachträglicher Tag startet als „Gebucht". UniqueConstraint (event_id, dienstleister_id)
  verhindert Doppel-Anfragen.
- Beim Testen: `factories.make_event/make_dienstleister/make_anfrage/reload` nutzen;
  Tests gegen geteilte DB → **datensatz-spezifisch asserten**, nie globale Zählungen.
- E-Mail-Design: nur Inline-Styles + Tabellen, Logos Base64, `width`/`height` als
  Attribute (Outlook). Keine `border-left`-Akzentstreifen (Design-No-Go).
- PDF: reportlab; Sonderzeichen wie ▶ haben in Helvetica KEIN Glyph → als Pfad zeichnen.
  App-Icons (`static/img/icons/*.svg`) via pymupdf rastern, für Knallfrosch umfärben.
- **Nur EINE Claude-Session gleichzeitig** an diesem Arbeitsbaum (Bündel-Commits passiert).
- Windows/PowerShell 5.1: kein `&&`, UTF-8 via `PYTHONUTF8=1`.

## Design-Sprache Briefing („Briefing 2.0")

Zwei-Spalten-Kartenraster, zentrierte Box-Titel mit App-Icon + Markenlinie, Schatten;
ROT nur für Kritisches (Ankunft/Treffpunkt, Teamleitung – Teamleitung immer zuerst);
Logo-Wasserzeichen; Fußzeile = Anschrift + „Rechnung per Mail an"; Seite 2 „Allgemeines"
mit Pfeil-Boxen aus den Einstellungen (`briefing_regeln`). Aykut mag: wenig Text,
klare Themen-Boxen („man weiß, wo man hingucken muss"). Vorlagen unter
`Desktop\Kindsalabim 2026\Personal\Briefings\`.
