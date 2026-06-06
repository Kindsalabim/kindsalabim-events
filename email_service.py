import base64
import json
import urllib.request
from datetime import datetime
from config import get_config

# Empfänger für den wöchentlichen CSV-Backup-Export
BACKUP_EMPFAENGER = "a.malca@kindsalabim.de"

# Logos als Base64 (inline – funktioniert in allen E-Mail-Clients)
try:
    from logo_b64 import KS_B64, KF_B64
except ImportError:
    KS_B64 = ""
    KF_B64 = ""


def _deliver(to: str, subject: str, html: str, attachments=None):
    """Verschickt eine E-Mail über die Resend HTTP-API (Render blockt ausgehendes SMTP).
    attachments: optionale Liste von (dateiname, bytes)."""
    cfg = get_config()
    api_key = cfg.get("resend_api_key")
    if not api_key:
        info = f" | Anhänge: {[a[0] for a in attachments]}" if attachments else ""
        print(f"[MOCK E-MAIL] An: {to} | Betreff: {subject}{info}")
        return

    payload = {
        "from": f'{cfg.get("company_name", "Kindsalabim")} <{cfg["mail_from"]}>',
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = [
            {"filename": fn, "content": base64.b64encode(data).decode()}
            for fn, data in attachments
        ]

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def _send(to: str, subject: str, body_html: str):
    _deliver(to, subject, body_html)

# Alias für die Test-Route
send_email = _send


def _logo_img(brand_color: str) -> str:
    """Gibt passendes Logo-Tag zurück (Base64 inline)."""
    is_kf = brand_color == "#1a7a1a"
    b64   = KF_B64 if is_kf else KS_B64
    if not b64:
        return ""
    return f'<img src="data:image/png;base64,{b64}" alt="{"Knallfrosch" if is_kf else "KindSalabim"}" style="height:44px;width:auto;display:block;">'


def _wrap(content: str, brand_color: str, cfg: dict) -> str:
    """Hüllt E-Mail-Inhalt in ein sauberes HTML-Layout mit Logo."""
    logo = _logo_img(brand_color)
    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header mit Logo -->
        <tr>
          <td style="background:{brand_color};border-radius:12px 12px 0 0;padding:24px 36px;">
            {logo if logo else f'<p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;">{cfg["company_name"]}</p>'}
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#ffffff;padding:36px;border-radius:0 0 12px 12px;">
            {content}
            <hr style="border:none;border-top:1px solid #f0f0f0;margin:32px 0">
            <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
              {cfg['company_name']} · {cfg['company_address']}<br>
              <a href="mailto:{cfg['company_email']}" style="color:#9ca3af;">{cfg['company_email']}</a>
              {(' · ' + cfg['company_phone']) if cfg.get('company_phone') else ''}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _info_row(label: str, value: str) -> str:
    return f"""
    <tr>
      <td style="padding:8px 16px 8px 0;font-size:14px;color:#6b7280;white-space:nowrap;vertical-align:top;">{label}</td>
      <td style="padding:8px 0;font-size:14px;color:#111827;font-weight:500;">{value or '–'}</td>
    </tr>"""


def _brand_color(marke: str) -> str:
    return "#1a7a1a" if marke == "Knallfrosch" else "#003864"


def send_magic_link(dienstleister, token: str, base_url: str):
    cfg = get_config()
    url = f"{base_url}/portal/auth/{token}"
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      Klick auf den Button um dich in deinem Portal anzumelden.
      Der Link ist <strong>24 Stunden gültig</strong>.
    </p>
    <a href="{url}"
       style="display:inline-block;background:#003864;color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Jetzt anmelden →
    </a>
    <p style="margin:24px 0 0;font-size:13px;color:#9ca3af;">
      Falls der Button nicht funktioniert:<br>
      <a href="{url}" style="color:#6b7280;">{url}</a>
    </p>
    <p style="margin:16px 0 0;font-size:13px;color:#d1d5db;">
      Falls du diese E-Mail nicht angefordert hast, kannst du sie ignorieren.
    </p>"""
    _send(dienstleister.email, f"Dein Anmelde-Link – {cfg['app_name']}", _wrap(content, "#003864", cfg))


def send_einladung(dienstleister, base_url: str):
    cfg = get_config()
    login_url = f"{base_url}/portal/login"
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      Herzlich willkommen bei {cfg['company_name']}! Du hast jetzt Zugang zu deinem persönlichen
      Dienstleister-Portal. Dort siehst du alle deine Anfragen, kannst zu- oder absagen
      und hast eine Übersicht über deine gebuchten Jobs.
    </p>
    <a href="{login_url}"
       style="display:inline-block;background:#003864;color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Zum Portal →
    </a>
    <p style="margin:24px 0 0;font-size:14px;color:#374151;">
      <strong>So funktioniert der Login:</strong><br>
      E-Mail-Adresse eingeben → du bekommst einen Link → klicken → fertig.<br>
      Kein Passwort nötig.
    </p>
    <p style="margin:16px 0 0;font-size:13px;color:#9ca3af;">
      Tipp: Füge das Portal auf deinem Homescreen hinzu, dann hast du es immer griffbereit.
    </p>"""
    _send(dienstleister.email, f"Willkommen bei {cfg['company_name']} – Dein Portal-Zugang",
          _wrap(content, "#003864", cfg))


def send_erinnerung(dienstleister, event):
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      Du hast noch eine offene Anfrage – die Frist läuft <strong>morgen ab</strong>.
    </p>
    <div style="background:#fffbeb;border-left:3px solid #f59e0b;border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', event.anlass)}
        {_info_row('Datum', event.datum)}
        {_info_row('Ort', event.veranstaltungsort)}
      </table>
    </div>
    <a href="https://kindsalabim-events.onrender.com/portal"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Jetzt antworten →
    </a>"""
    _send(dienstleister.email,
          f"⏰ Erinnerung: Anfrage läuft morgen ab – {event.anlass}",
          _wrap(content, color, cfg))


def send_frist_verlaengerung(dienstleister, event, admin_email: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 16px;font-size:15px;color:#374151;">
      <strong>{dienstleister.vorname} {dienstleister.nachname}</strong> hat für
      <strong>{event.anlass}</strong> ({event.datum}) eine Fristverlängerung angefordert.
    </p>
    <p style="margin:0;font-size:14px;color:#6b7280;">Die Frist wurde automatisch um 2 Tage verlängert.</p>"""
    _send(admin_email,
          f"Fristverlängerung: {dienstleister.vorname} {dienstleister.nachname} – {event.anlass}",
          _wrap(content, color, cfg))


def send_material_erinnerung(event, admin_email: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 16px;font-size:16px;color:#111827;">📦 Material-Erinnerung</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      In <strong>3 Wochen</strong> findet folgendes Event statt, bei dem eine
      <strong>Bakerross-Bastelaktion</strong> gebucht wurde. Bitte Material rechtzeitig bestellen!
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', event.anlass)}
        {_info_row('Datum', event.datum)}
        {_info_row('Kunde', event.kunde_firma)}
        {_info_row('Gebuchte Aktionen', event.produkte)}
      </table>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">
      Diese Erinnerung wird automatisch 3 Wochen vor dem Event-Datum gesendet.
    </p>"""
    _send(admin_email,
          f"📦 Material bestellen: {event.anlass} am {event.datum} – {event.kunde_firma}",
          _wrap(content, color, cfg))


def send_checklist_email(event, base_url: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    url = f"{base_url}/checklist/{event.checklist_token}"
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Guten Tag,</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      vielen Dank für Ihre Buchung. Damit wir Ihr Event optimal vorbereiten können,
      bitten wir Sie, die folgende Checkliste auszufüllen.
    </p>

    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', event.anlass)}
        {_info_row('Datum', event.datum)}
        {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
      </table>
    </div>

    <a href="{url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Checkliste ausfüllen →
    </a>

    <p style="margin:24px 0 0;font-size:13px;color:#9ca3af;">
      Falls der Button nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:<br>
      <a href="{url}" style="color:#6b7280;">{url}</a>
    </p>"""

    subject = f"Checkliste: {event.anlass} am {event.datum} – bitte ausfüllen"
    _send(event.kunde_email, subject, _wrap(content, color, cfg))


def send_checklist_notification(event, admin_email: str, base_url: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    detail_url = f"{base_url}/admin/events/{event.id}"
    content = f"""
    <p style="margin:0 0 16px;font-size:15px;color:#374151;">
      <strong>{event.kunde_firma}</strong> hat die Kunden-Checkliste für
      <strong>{event.anlass}</strong> ({event.datum}) ausgefüllt.
    </p>
    <a href="{detail_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">
      Event ansehen →
    </a>"""

    subject = f"Checkliste eingereicht: {event.anlass} – {event.kunde_firma}"
    _send(admin_email, subject, _wrap(content, color, cfg))


def send_verfuegbarkeitsanfrage(dienstleister, event, anfrage_id: int, base_url: str):
    cfg = get_config()
    color = _brand_color(event.marke)

    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      wir würden dich gerne für folgendes Event anfragen. Bitte melde dich in deinem Portal an
      und bestätige deine Verfügbarkeit.
    </p>

    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', event.anlass)}
        {_info_row('Kunde', event.kunde_firma)}
        {_info_row('Datum', event.datum)}
        {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
        {_info_row('Ort', event.veranstaltungsort)}
        {_info_row('Produkte', event.produkte)}
      </table>
    </div>

    <a href="{base_url}/portal/login"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Zum Portal →
    </a>

    <p style="margin:24px 0 0;font-size:14px;color:#6b7280;">
      Bitte antworte innerhalb von 7 Tagen.
    </p>"""

    subject = f"Anfrage: {event.anlass} bei {event.kunde_firma} am {event.datum}"
    _send(dienstleister.email, subject, _wrap(content, color, cfg))


def send_briefing(dienstleister_list, event, base_url: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    subject = f"Briefing: {event.anlass} bei {event.kunde_firma} am {event.datum}"

    for d in dienstleister_list:
        content = f"""
        <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {d.vorname},</p>
        <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
          hier ist dein Briefing für das bevorstehende Event. Bitte lies es sorgfältig durch.
        </p>

        <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
          <p style="margin:0 0 12px;font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Veranstaltung</p>
          <table cellpadding="0" cellspacing="0" width="100%">
            {_info_row('Anlass', event.anlass)}
            {_info_row('Kunde', event.kunde_firma)}
            {_info_row('Datum', event.datum)}
            {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
            {_info_row('Aufbau ab', event.aufbau_ab)}
            {_info_row('Ort', event.veranstaltungsort)}
            {_info_row('Indoor/Outdoor', event.outdoor_indoor)}
            {_info_row('Parkplatz', event.parkplatz)}
            {_info_row('Teamkleidung', 'Ja' if event.teamkleidung else 'Nein')}
            {_info_row('Verpflegung', 'Ja' if event.verpflegung else 'Nein')}
            {_info_row('Produkte', event.produkte)}
          </table>
        </div>

        <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
          <p style="margin:0 0 12px;font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Ansprechpartner vor Ort</p>
          <table cellpadding="0" cellspacing="0" width="100%">
            {_info_row('Name', event.kunde_kontakt)}
            {_info_row('Telefon', event.kunde_telefon)}
          </table>
        </div>

        {"" if not event.hinweise else f'<div style="background:#fffbeb;border-left:3px solid #f59e0b;border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px;"><p style="margin:0 0 4px;font-size:12px;font-weight:700;color:#92400e;text-transform:uppercase;">Hinweis</p><p style="margin:0;font-size:14px;color:#78350f;">{event.hinweise}</p></div>'}

        <p style="margin:0 0 8px;font-size:14px;color:#374151;">
          Deine Jobs findest du jederzeit in deinem Portal:
        </p>
        <a href="{base_url}/portal"
           style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
                  padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;margin-bottom:24px;">
          Zum Portal →
        </a>

        <div style="background:#f9fafb;border-radius:8px;padding:16px 20px;">
          <p style="margin:0 0 4px;font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;">Rechnung senden an</p>
          <p style="margin:0;font-size:14px;color:#374151;">
            {cfg['company_name']}<br>
            {cfg['company_address']}<br>
            <a href="mailto:personal@knallfrosch-kinderevents.de" style="color:{color};">personal@knallfrosch-kinderevents.de</a>
          </p>
        </div>"""

        _send(d.email, subject, _wrap(content, color, cfg))


def send_backup(attachments, n_events: int, n_dienstleister: int):
    """Schickt die CSV-Dateien (Liste von (dateiname, bytes)) als Anhang an den Admin."""
    cfg = get_config()
    color = "#003864"
    datum = datetime.today().strftime("%d.%m.%Y")
    content = f"""
    <p style="margin:0 0 16px;font-size:16px;color:#111827;">🗄️ Wöchentliches Daten-Backup</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      Im Anhang findest du den aktuellen CSV-Export vom <strong>{datum}</strong>.
      Bewahre die E-Mail auf – sie dient als menschenlesbares Notfall-Backup.
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Events', str(n_events))}
        {_info_row('Dienstleister', str(n_dienstleister))}
      </table>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">
      Tipp: Die CSV-Dateien lassen sich direkt in Excel öffnen (Umlaute inklusive).
    </p>"""

    _deliver(BACKUP_EMPFAENGER, f"🗄️ Backup {datum} – Kindsalabim Events",
             _wrap(content, color, cfg), attachments)
