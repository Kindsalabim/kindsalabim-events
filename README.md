# Knallfrosch / Kindsalabim – Event Manager

Event-Management-App für Kinderevents. Admin-Dashboard + Dienstleister-Portal.

## Setup (einmalig)

```bash
cd knallfrosch-app
pip install -r requirements.txt
python setup.py
```

## Starten

```bash
uvicorn main:app --reload
```

- Admin: http://localhost:8000/admin/login
- Dienstleister-Portal: http://localhost:8000/portal/login

## Zweites Deployment (Knallfrosch)

1. Ordner kopieren
2. `config.yaml` anpassen (app_name, company_name, E-Mail etc.)
3. `python setup.py` ausführen (neues Passwort + Secret Key)
4. Auf anderem Port starten: `uvicorn main:app --port 8001 --reload`

## E-Mail einrichten

In `config.yaml`:
```yaml
smtp_host: "smtp.gmail.com"
smtp_port: 587
smtp_user: "deine@email.de"
smtp_password: "app-passwort"
smtp_from: "info@kindsalabim.de"
```

Solange smtp_host leer ist, werden E-Mails nur in der Konsole ausgegeben (Mock-Modus).
