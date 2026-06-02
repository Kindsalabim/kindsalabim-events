import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import get_config

def send_email(to: str, subject: str, body_html: str):
    cfg = get_config()
    if not cfg.get("smtp_host"):
        print(f"[MOCK E-MAIL] An: {to}\nBetreff: {subject}\n{body_html[:200]}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_from"]
    msg["To"] = to
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], to, msg.as_string())


def send_verfuegbarkeitsanfrage(dienstleister, event, anfrage_id: int, base_url: str):
    cfg = get_config()
    subject = f"Anfrage: {event.anlass} bei {event.kunde_firma} am {event.datum}"
    body = f"""
<p>Hallo {dienstleister.vorname},</p>
<p>wir würden dich gerne für folgendes Event anfragen:</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Anlass:</td><td>{event.anlass}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Kunde:</td><td>{event.kunde_firma}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Datum:</td><td>{event.datum}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Uhrzeit:</td><td>{event.startzeit} – {event.endzeit} Uhr</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Ort:</td><td>{event.veranstaltungsort}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Produkte:</td><td>{event.produkte or "–"}</td></tr>
</table>
<p>Bitte melde dich in deinem Portal an und bestätige deine Verfügbarkeit:</p>
<p><a href="{base_url}/portal/login" style="background:#166534;color:white;padding:10px 20px;text-decoration:none;border-radius:6px">Zum Portal</a></p>
<p>Bitte antworte innerhalb von 7 Tagen.<br>
Bei Fragen: <a href="mailto:{cfg['company_email']}">{cfg['company_email']}</a> oder {cfg.get('company_phone','')}</p>
<p>Viele Grüße,<br>{cfg['company_name']}</p>
"""
    send_email(dienstleister.email, subject, body)


def send_briefing(dienstleister_list, event, base_url: str):
    cfg = get_config()
    subject = f"Briefing: {event.anlass} bei {event.kunde_firma} am {event.datum}"
    for d in dienstleister_list:
        body = f"""
<p>Hallo {d.vorname},</p>
<p>hier ist dein Briefing für das bevorstehende Event:</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Anlass:</td><td>{event.anlass}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Kunde:</td><td>{event.kunde_firma}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Datum:</td><td>{event.datum}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Uhrzeit:</td><td>{event.startzeit} – {event.endzeit} Uhr</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Veranstaltungsort:</td><td>{event.veranstaltungsort}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Ansprechpartner vor Ort:</td><td>{event.kunde_kontakt or "–"} ({event.kunde_telefon or "–"})</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Aufbau ab:</td><td>{event.aufbau_ab or "–"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Outdoor/Indoor:</td><td>{event.outdoor_indoor or "–"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Parkplatz:</td><td>{event.parkplatz or "–"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Teamkleidung:</td><td>{"Ja" if event.teamkleidung else "Nein"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Verpflegung:</td><td>{"Ja" if event.verpflegung else "Nein"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Produkte:</td><td>{event.produkte or "–"}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Hinweise:</td><td>{event.hinweise or "–"}</td></tr>
</table>
<p>Deine bestätigten Jobs findest du jederzeit in deinem Portal:<br>
<a href="{base_url}/portal" style="color:#166534">{base_url}/portal</a></p>
<p>Rechnung bitte an:<br>
{cfg['company_name']}<br>
{cfg['company_address']}<br>
<a href="mailto:personal@knallfrosch-kinderevents.de">personal@knallfrosch-kinderevents.de</a></p>
<p>Viele Grüße,<br>{cfg['company_name']}</p>
"""
        send_email(d.email, subject, body)
