# Kindsalabim Events – Technischer Bericht & Entwicklungs-Roadmap

*Ursprünglich: 06.06.2026 (Code-Audit) · **Letztes Update: 11.06.2026***

---

## ⭐ Aktueller Stand (11.06.2026)

Seit dem ursprünglichen Audit wurde die App massiv ausgebaut. Die meisten kritischen und mittleren Punkte sind **erledigt**, dazu kamen mehrere große neue Module.

### Erledigt seit dem Audit
| Thema | Status | Abschnitt |
|-------|--------|-----------|
| Datenpersistenz (PostgreSQL) | ✅ | 1.1 |
| Wöchentliches CSV-Backup (Cron) | ✅ | 1.2 |
| Cookie-Security (`secure`+`samesite`) | ✅ | 2.1 |
| Echter Date-Typ (Event/Frist) | ✅ | 3.1 |
| Single-Admin → **Mehr-Admin-Tabelle + Passwort-Reset** | ✅ | 2.5 |
| E-Mail SMTP → Resend HTTP-API | ✅ | — |
| Logistiker-Pflicht (an `material_mitnahme` gekoppelt) + Warnung | ✅ | 4.1 |
| Dienstleister: Detailansicht, CSV-Export, Sortierung, Lösch-Buttons | ✅ | 6 |
| Nachträgliche Absage im Portal + Admin-Mail | ✅ | — |
| Magic-Link direkt in Anfrage-E-Mail (1-Klick-Login) | ✅ | — |
| Buchhaltungsbereich (Rechnungen, Steuer-/Investrücklage, CSV) | ✅ | — |
| Jira-Import Dienstleister (54 importiert) | ✅ | — |
| Cloudflare R2 Dateiupload (Planung/Eventfotos) | ✅ | — |
| Angebots-PDF-Generator (`/admin/angebot`) | ✅ | — |
| **Wissensdatenbank** (Hierarchie, Karten, WYSIWYG, Sichtbarkeit, Confluence-Import) | ✅ | NEU |
| **Ticket-/Sprint-System** (Kanban, Backlog, Kategorien, Jira-CSV-Import) | ✅ | NEU |

### Noch offen / als Nächstes
| Priorität | Thema |
|-----------|-------|
| 🔜 **Nächste Session** | **Customer-Management-Tool (CRM)** – Kundenverwaltung |
| 🟡 | Auto-Nachbesetzung bei Absage (Teil der „2.0"-Automatisierung) |
| 🟡 | Abgelaufene Anfragen automatisch markieren (3.3) |
| 🟢 | Material-/Logistik-Cockpit (4.4) |
| 🟢 | Geocoding statt PLZ-Liste (3.4) |
| 🔒 | **R2-Secrets rotieren** (upload_*.py hatten Klartext-Keys, jetzt gitignored) |
| 🔒 | CSRF-Token, Cron-Secret härten, Checklisten-Token-Ablauf (2.2–2.4) |
| 🤖 | KI-Module: BakerRoss-Recherche, KI-Angebots-PDF (5.1/5.2) |

*Die folgenden Abschnitte sind der historische Audit-Stand (06.06.2026) und dienen als Kontext.*

---

## 0. Executive Summary

Die App hat in kurzer Zeit eine beeindruckende Funktionstiefe erreicht: Multi-Brand-Eventverwaltung, Dienstleister-Datenbank mit Entfernungs-Ranking, Magic-Link-Portal, Kunden-Checkliste, automatischer E-Mail-Versand, Frist-System und Status-Automatik. Das Fundament ist solide und sauber strukturiert.

**Es gibt jedoch ein kritisches Problem, das vor dem Echtbetrieb gelöst werden MUSS** (Abschnitt 1.1) – andernfalls droht vollständiger Datenverlust bei jedem Deployment.

Darüber hinaus gibt es mehrere Sicherheits- und Robustheits-Themen mittlerer Priorität sowie erhebliches Potenzial bei der Workflow-Automatisierung.

**Ampel-Bewertung:**

| Bereich | Status |
|---------|--------|
| Funktionsumfang | 🟢 Sehr gut |
| Datensicherheit (Persistenz) | 🟢 Gelöst (PostgreSQL Basic auf Render, 06.06.2026) |
| Zugriffssicherheit | 🟡 Verbesserungswürdig |
| Code-Qualität / Wartbarkeit | 🟢 Gut |
| Design / UX / UI | 🟢 Gut |
| Automatisierungs-Reife | 🟡 Solide Basis, viel Potenzial |

---

## 1. Kritische Schwachstellen (sofort handeln)

### 1.1 ✅ Datenverlust bei jedem Deployment (GELÖST, 06.06.2026)

**Lösung umgesetzt:** Render PostgreSQL Basic-256mb (Virginia) als managed DB. `database.py` liest `DATABASE_URL` aus der Umgebung (psycopg3/`postgresql+psycopg://`), Fallback auf SQLite lokal. Persistenz-Test bestanden: Daten überleben Redeployments.

### 1.2 ⏳ Backup-Mechanismus (NÄCHSTER SCHRITT)

**Render-seitig bereits aktiv:** Basic PostgreSQL enthält tägliche Backups mit 7-Tage-Retention (Point-in-Time-Recovery). Das deckt den Hauptfall (Datenbankfehler, Render-Ausfall) ab.

**Noch offen:** Menschenlesbarer Notfall-Export für den Fall, dass jemand versehentlich Datensätze löscht – Render-Backups sind nur über das Dashboard wiederherstellbar, nicht selbst abrufbar.

**Geplante Lösung:** Wöchentlicher Cron-Job (montags 08:00) → neuer Endpunkt `/cron/backup` → CSV-Export (Events + Dienstleister) per E-Mail an Admin.

---

## 2. Sicherheits-Themen (mittlere Priorität)

### 2.1 Cookies nicht als `secure` / `samesite` markiert
Die Session-Cookies (`admin_token`, `portal_token`) werden ohne `secure=True` und ohne `samesite`-Attribut gesetzt. Auf der HTTPS-Render-Domain sollten beide gesetzt sein.
- `secure=True` → Cookie wird nie über unverschlüsseltes HTTP übertragen.
- `samesite="lax"` → Schutz gegen Cross-Site-Request-Forgery (CSRF).

### 2.2 Kein CSRF-Schutz auf Formularen
Alle Aktionen (Event löschen, Anfrage senden, zu-/absagen) laufen über POST mit Cookie-Authentifizierung. Ohne CSRF-Token könnte eine fremde Website im Namen eines eingeloggten Nutzers Aktionen auslösen. `samesite=lax` entschärft das größtenteils; ein echtes CSRF-Token wäre der saubere Weg.

### 2.3 Schwaches Cron-Secret
`cron_secret: "ks-cron-2026"` ist leicht erratbar und wird als URL-Parameter übergeben (landet im Klartext in Server-Logs). Besser: langer Zufallswert + Übergabe per HTTP-Header statt Query-String.

### 2.4 Checklisten-Token ohne Ablauf & Mehrfach-Überschreibung
Der Kunden-Link (`/checklist/{token}`) läuft nie ab und kann beliebig oft neu abgesendet werden – jede Einreichung überschreibt die vorherige. Ein bereits abgeschickter Kunde könnte (versehentlich oder absichtlich) Daten überschreiben.
**Lösung:** Nach erster Einreichung sperren (read-only) oder Änderungen protokollieren.

### 2.5 Single-Admin mit Passwort in Config
Es gibt genau einen Admin, dessen Passwort-Hash in `config.yaml` / Umgebungsvariable liegt. Für aktuell eine Person ok. Sobald ein zweiter Mitarbeiter (z. B. Büro-Vertretung) Zugang braucht, ist eine echte Nutzer-Tabelle nötig.

---

## 3. Robustheit & Datenmodell

### 3.1 🟡 Datum als Text gespeichert – fragil
Datumswerte werden als String `"TT.MM.JJJJ"` gespeichert. Das verursacht mehrere latente Probleme:

- **Sortierung** funktioniert nur per Umweg (String-Parsing in Python bei jedem Aufruf).
- **Cron-Matching** vergleicht Strings exakt: `frist_datum == "07.06.2026"`. Wäre ein Datum einmal als `"7.6.2026"` gespeichert, schlägt der Vergleich fehl und die Erinnerung wird **nie** gesendet – ohne Fehlermeldung.
- Keine Validierung ungültiger Daten beim Eingeben.

**Lösung:** Umstieg auf echten `Date`-Spaltentyp. Anzeige weiterhin im deutschen Format, aber Speicherung als ISO-Datum. Mittlerer Aufwand, hoher Robustheits-Gewinn.

### 3.2 Migrations sind ad-hoc
Schema-Änderungen laufen über `ALTER TABLE ... ` in `try/except`-Blöcken beim Start. Das funktioniert für additive Änderungen, hat aber keine Versionierung und keine Rollback-Möglichkeit.
**Lösung (später):** Alembic einführen, sobald PostgreSQL steht.

### 3.3 Abgelaufene Anfragen bleiben „Ausstehend“ für immer
Läuft eine Frist ab, ohne dass der Dienstleister antwortet, bleibt der Status dauerhaft „Ausstehend“. Es gibt keinen automatischen Übergang nach „Abgelaufen“.
**Lösung:** Im täglichen Cron abgelaufene Anfragen markieren und Admin benachrichtigen („3 Anfragen für Event X abgelaufen – bitte nachbesetzen“).

### 3.4 PLZ-Koordinaten hartkodiert & lückenhaft
`distance.py` enthält eine manuell gepflegte Liste von ~250 PLZ mit teils geschätzten Koordinaten. Dienstleister mit PLZ außerhalb dieser Liste erhalten Distanz „9999“ und landen im Ranking ganz hinten – unabhängig von ihrer tatsächlichen Nähe.
**Lösung:** Geocoding-Dienst (z. B. OpenPLZ API oder Nominatim) on-demand, Ergebnis cachen. Damit funktioniert das Ranking deutschlandweit ohne Pflegeaufwand.

---

## 4. Workflow-Automatisierung – das große Potenzial

Hier liegt der größte zukünftige Hebel. Die App ist heute ein exzellentes **Verwaltungs-Werkzeug**; sie kann zu einem **mitdenkenden Assistenten** werden.

### 4.1 Intelligente Dienstleister-Auswahl (bereits angedacht)
Aufbauend auf `rank_contractors` und dem neuen Logistiker-Flag:

- **Logistiker-Pflicht automatisch durchsetzen:** Bei jedem Event mit Materialbedarf (= nicht reines Künstler-Event) muss mindestens ein Logistiker im Team sein. Das System sollte Logistiker bei der Vorauswahl priorisieren und warnen, wenn keiner zugesagt hat.
- **Ein-Klick-Anfragewelle:** „Team automatisch zusammenstellen“ – das System schlägt die optimale Kombination vor (nächstgelegene Logistiker + erfahrenste Teamer/Künstler) und verschickt nach Bestätigung alle Anfragen auf einmal.
- **Automatische Nachbesetzung:** Sagt jemand ab, schlägt das System sofort den nächstbesten freien Dienstleister vor (oder fragt automatisch an).

### 4.2 Event-Lebenszyklus vollständig automatisieren
Die `auto_status`-Logik ist der Anfang. Ausbauen zu einer durchgängigen Pipeline:

```
Event eingepflegt
   → [auto] Checkliste an Kunde
   → [Kunde füllt aus] → Checkliste eingegangen
   → [auto] Team-Anfragen raus
   → [alle Zusagen + Logistiker] → Planung fertig
   → [auto] Briefing X Tage vorher
   → [Eventdatum vorbei] → Abgeschlossen
   → [auto] Feedback-/Rechnungs-Erinnerung
```

Jeder `[auto]`-Schritt spart manuelle Klicks und verhindert Vergessen.

### 4.3 Proaktive Erinnerungen ausbauen
Material-Erinnerung (3 Wochen) existiert. Erweitern um:
- Briefing-Erinnerung wenn Event in X Tagen und Status noch nicht „Briefing gesendet“.
- „Event in 14 Tagen, Team noch nicht vollständig“ → tägliche Eskalation ans Büro.
- Rechnungs-Nachverfolgung nach dem Event.

### 4.4 Material-/Logistik-Cockpit
Eine zentrale Wochenansicht: „Welches Material muss diese Woche bestellt werden? Wer transportiert was wohin?“ – löst genau das im Briefing genannte Kernproblem (Wer fährt das Material durch NRW?).

---

## 5. Neue Funktionsmodule (aus dem Briefing)

### 5.1 KI-Angebotsunterstützung (BakerRoss-Recherche)
**Ziel:** Thema eingeben → KI liefert 4–5 passende Bastelaktionen mit Einkaufspreis, berechnetem Verkaufspreis (× 1,8) und Produktbild.

**Machbarkeit:** Realistisch, aber eigenständiges Projekt. Technische Bausteine:
- Claude API für Verständnis & Aufbereitung.
- Produktdaten-Beschaffung von bakerross.de (Web-Recherche/Scraping – rechtliche Rahmenbedingungen prüfen).
- Eigener Reiter „Angebotsunterstützung“ mit Such-/Ergebnis-Ansicht.
- Preis-Logik (Einkauf × Faktor) konfigurierbar.

**Einschätzung:** 2–3 fokussierte Sessions. Sollte erst nach Stabilisierung des Kerns (Abschnitt 1) angegangen werden.

### 5.2 KI-gestützte Angebots-PDF
**Ziel:** Angebot hochladen → KI erkennt gebuchte Produkte → generiert professionelle Bilder-PDF (wie die manuell erstellte „Hydrogenics“-Datei, nur schöner).

**Machbarkeit:** Anspruchsvoll. Bausteine:
- PDF-/Text-Extraktion des hochgeladenen Angebots.
- KI-Erkennung der gebuchten Aktionen.
- Zuordnung zu hinterlegtem Bildmaterial pro Produkt.
- PDF-Generierung mit Layout-Template.

**Einschätzung:** Größtes der neuen Module, eigenständiges Teilprojekt. Voraussetzung: strukturierte Bildmaterial-Bibliothek pro Produkt in der App.

---

## 6. Design / UX / UI

**Stärken:** Konsistentes Markensystem (Blau/Grün), saubere Karten, gute Mobile-Optimierung, klare Status-Sprache, jetzt mit Logos.

**Verbesserungspotenzial:**

| Thema | Vorschlag |
|-------|-----------|
| Dashboard-Skalierung | Bei vielen Events: Such-/Filterleiste (nach Marke, Status, Zeitraum) |
| Datums-Eingabe | Echter Datepicker statt Texteingabe (verhindert Formatfehler, siehe 3.1) |
| Lade-/Erfolgs-Feedback | Toast-Benachrichtigungen statt URL-Parameter-Banner |
| Dienstleister-Detailseite | Eigene Profilansicht mit Einsatzhistorie & Statistik |
| Barrierefreiheit | Kontraste & Fokus-Zustände systematisch prüfen |
| Druckansicht | Briefing/Checkliste als saubere Druck-/PDF-Ansicht |

---

## 7. Empfohlene Roadmap (nächste Tage)

### Phase 1 – Fundament sichern (ZUERST, nicht verhandelbar)
1. ✅ **Datenpersistenz gelöst** (PostgreSQL Basic auf Render, 06.06.2026) — *Abschnitt 1.1*
2. ⏳ **Backup einrichten** (wöchentlicher CSV-Export per Cron) — *1.2*
3. **Cookie-Security** (`secure` + `samesite`) — *2.1*
4. **Datum auf echten Date-Typ** umstellen — *3.1*

→ Ergebnis: produktionssicheres Fundament, keine Datenverlust-Gefahr.

### Phase 2 – Robustheit & Automatisierung
5. Abgelaufene Anfragen automatisch behandeln — *3.3*
6. Logistiker-Pflicht & -Priorisierung im Ranking — *4.1*
7. Automatische Nachbesetzung bei Absage — *4.1*
8. Cron-Secret härten, Checklisten-Token absichern — *2.3, 2.4*
9. Geocoding statt PLZ-Liste — *3.4*

### Phase 3 – Komfort & Skalierung
10. Dashboard-Filter/Suche, Datepicker, Toasts — *Abschnitt 6*
11. Material-/Logistik-Cockpit — *4.4*
12. Mehrbenutzer-Admin (falls Büro wächst) — *2.5*

### Phase 4 – KI-Module (eigenständige Teilprojekte)
13. KI-Angebotsunterstützung (BakerRoss) — *5.1*
14. KI-Angebots-PDF — *5.2*

---

## 8. Fazit

Die App ist funktional bereits sehr weit und gut gebaut. Der **einzige echte Blocker** für den Produktivbetrieb ist die Datenpersistenz (Abschnitt 1.1) – das sollte die allernächste Maßnahme sein, bevor weitere Features entstehen. Danach steht einer schrittweisen Entwicklung zum mitdenkenden Event-Assistenten nichts im Weg.

Die größten Geschäftshebel liegen in der **Workflow-Automatisierung** (Abschnitt 4) und perspektivisch in den **KI-Modulen** (Abschnitt 5), die echte wiederkehrende Handarbeit (Materiallogistik, Angebotsrecherche) automatisieren.
