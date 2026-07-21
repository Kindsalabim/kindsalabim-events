import base64
import json
import os
import re
import urllib.request
import urllib.error
from html import unescape, escape as _esc
from datetime import datetime
from config import get_config
from choices import (de_date, de_euro, plz_ort, rechnung_anschrift, sparte_label,
                     regeln_abschnitte, zeit_bis_text)


def _html_to_text(html: str) -> str:
    """Erzeugt eine lesbare Plain-Text-Version aus dem Mail-HTML. Ein Text-Teil
    neben dem HTML verbessert die Zustellbarkeit (multipart/alternative)."""
    text = re.sub(r'(?is)<(style|script|head)[^>]*>.*?</\1>', '', html)
    text = re.sub(r'(?is)<img[^>]*>', '', text)          # Inline-Logos etc. raus
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</(p|div|tr|h[1-6]|li|table)>', '\n', text)
    text = re.sub(r'(?i)</td>', '  ', text)              # Tabellenzelle -> Abstand
    text = re.sub(r'(?s)<[^>]+>', '', text)              # restliche Tags
    text = unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# Empfänger für den wöchentlichen CSV-Backup-Export
BACKUP_EMPFAENGER = "a.malca@kindsalabim.de"

# Antwortfrist für Verfügbarkeitsanfragen (Tage). EINE Quelle für Mailtext UND das
# in der DB gesetzte frist_datum, damit beide nie auseinanderlaufen. (Review H5)
ANFRAGE_FRIST_TAGE = 3

# Logos als Base64 (inline – funktioniert in allen E-Mail-Clients)
try:
    from logo_b64 import KS_B64, KF_B64, KS_W, KS_H, KF_W, KF_H
except ImportError:
    KS_B64 = KF_B64 = ""
    KS_W = KS_H = KF_W = KF_H = 0


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
        "text": _html_to_text(html),
    }
    reply_to = cfg.get("mail_reply_to")
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = [
            {"filename": fn, "content": base64.b64encode(data).decode()}
            for fn, data in attachments
        ]

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare (vor Resend) blockt den Default-UA von urllib (Fehler 1010)
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Resend HTTP {e.code}: {body}") from None


def _send(to: str, subject: str, body_html: str):
    _deliver(to, subject, body_html)

# Alias für die Test-Route
send_email = _send


def _logo_img(brand_color: str) -> str:
    """Gibt passendes Logo-Tag zurück (Base64 inline, transparent, für weißen Header).
    width/height als HTML-Attribute, damit auch Outlook die Größe respektiert."""
    is_kf = brand_color == "#1a7a1a"
    b64 = KF_B64 if is_kf else KS_B64
    w, h = (KF_W, KF_H) if is_kf else (KS_W, KS_H)
    alt = "Knallfrosch" if is_kf else "KindSalabim"
    if not b64:
        return ""
    return (f'<img src="data:image/png;base64,{b64}" alt="{alt}" width="{w}" height="{h}" '
            f'style="width:{w}px;height:{h}px;display:inline-block;border:0;outline:none;text-decoration:none;">')


def _wrap(content: str, brand_color: str, cfg: dict) -> str:
    """Hüllt E-Mail-Inhalt in ein sauberes HTML-Layout mit Logo.
    Footer/Absender markenabhängig – auf Knallfrosch-Mails wird Kindsalabim nicht erwähnt."""
    logo = _logo_img(brand_color)
    is_kf = brand_color == "#1a7a1a"
    if is_kf:
        foot_title = "Knallfrosch Kinderevents"
        foot_name  = "Malca &amp; Akmanoglu GbR · Knallfrosch Kinderevents"
        foot_addr  = "Charlottenweg 55, 45289 Essen"
        foot_mail  = "info@knallfrosch-kinderevents.de"
    else:
        foot_title = cfg["company_name"]
        foot_name  = cfg["company_name"]
        foot_addr  = cfg["company_address"]
        foot_mail  = cfg["company_email"]
    foot_phone = cfg.get("company_phone")
    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header mit Logo (weiß, dezente Markenlinie als Akzent) -->
        <tr>
          <td align="center" style="background:#ffffff;border-radius:12px 12px 0 0;border-bottom:3px solid {brand_color};padding:28px 36px 24px;text-align:center;">
            {logo if logo else f'<p style="margin:0;font-size:20px;font-weight:700;color:{brand_color};">{foot_title}</p>'}
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#ffffff;padding:36px;border-radius:0 0 12px 12px;">
            {content}
            <hr style="border:none;border-top:1px solid #f0f0f0;margin:32px 0">
            <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
              {foot_name} · {foot_addr}<br>
              <a href="mailto:{foot_mail}" style="color:#9ca3af;">{foot_mail}</a>
              {(' · ' + foot_phone) if foot_phone else ''}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _no_none(x) -> str:
    """Leerstring für None und für den (aus dem alten Formular-Bug) gespeicherten Text 'None'."""
    s = x if isinstance(x, str) else ("" if x is None else str(x))
    return "" if s.strip().lower() == "none" else s


def _info_row(label: str, value: str) -> str:
    # HTML-Escaping des Werts: cl_*-Felder etc. stammen z. T. aus der öffentlichen
    # Kunden-Checkliste und dürfen keinen HTML-Code in die Mail einschleusen.
    return f"""
    <tr>
      <td style="padding:8px 16px 8px 0;font-size:14px;color:#6b7280;white-space:nowrap;vertical-align:top;">{label}</td>
      <td style="padding:8px 0;font-size:14px;color:#111827;font-weight:500;">{_esc(_no_none(value)) or '–'}</td>
    </tr>"""


_ROT = "#c0473f"   # roter Akzent für das Kritische (Ankunft/Treffpunkt) – wie im PDF


def _info_row_rot(label: str, value: str) -> str:
    return f"""
    <tr>
      <td style="padding:8px 16px 8px 0;font-size:14px;font-weight:700;color:{_ROT};white-space:nowrap;vertical-align:top;">{label}</td>
      <td style="padding:8px 0;font-size:15px;color:#111827;font-weight:700;">{_esc(_no_none(value)) or '–'}</td>
    </tr>"""


# App-Linien-Icons als base64-PNG einbetten (Outlook-fest; für Knallfrosch grün umgefärbt).
_ICON_DIR_MAIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img", "icons")
_KF_ICON_UMFAERBUNG = {"#1D4E89": "#1a7a1a", "#7FB3D9": "#8FCB8F"}
_icon_cache_mail: dict = {}


def _icon_b64(name: str, is_kf: bool) -> str:
    """SVG-Icon → base64-PNG-Data-URI (gecacht). '' wenn nicht renderbar (Mail bleibt nutzbar)."""
    key = (name, is_kf)
    if key not in _icon_cache_mail:
        uri = ""
        try:
            with open(os.path.join(_ICON_DIR_MAIL, f"{name}.svg"), encoding="utf-8") as f:
                svg = f.read()
            if is_kf:
                for alt, neu in _KF_ICON_UMFAERBUNG.items():
                    svg = svg.replace(alt, neu)
            import fitz
            doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
            pix = doc[0].get_pixmap(dpi=180, alpha=True)
            uri = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
            doc.close()
        except Exception:
            uri = ""
        _icon_cache_mail[key] = uri
    return _icon_cache_mail[key]


def _mail_card(titel: str, icon_uri: str, inner_html: str, brand: str) -> str:
    """Weiße Themen-Karte im PDF-Stil: zentrierter Titel mit Icon + markenfarbene Linie."""
    icon = (f'<img src="{icon_uri}" width="15" height="15" alt="" '
            f'style="vertical-align:-2px;margin-right:7px;">' if icon_uri else '')
    return f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;margin:0 0 16px;">
          <div style="text-align:center;padding:12px 16px 11px;border-bottom:2px solid {brand};">
            {icon}<span style="font-size:14px;font-weight:700;color:#111827;">{titel}</span>
          </div>
          <div style="padding:14px 20px;">{inner_html}</div>
        </div>"""


def _team_row(name_html: str, telefon, highlight: bool = False, tint: str = "#eef3fb") -> str:
    """Team-Zeile: Name (darf umbrechen) + Telefon rechts, das nie ziffernweise umbricht.
    highlight tönt die Zeile (für den Teamleiter)."""
    tel = _esc(_no_none(telefon).strip()) or "–"
    if highlight:
        cl = f"padding:10px 12px;background:{tint};"
        cr = f"padding:10px 12px;background:{tint};"
    else:
        cl = "padding:8px 12px 8px 0;"
        cr = "padding:8px 0;"
    return f"""
    <tr>
      <td style="{cl}font-size:14px;color:#111827;vertical-align:top;">{name_html}</td>
      <td style="{cr}font-size:14px;color:#111827;font-weight:600;white-space:nowrap;text-align:right;vertical-align:top;">{tel}</td>
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


def send_admin_reset(admin, token: str, base_url: str):
    cfg = get_config()
    url = f"{base_url}/admin/reset/{token}"
    color = "#1D4E89"
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {admin.name or 'Admin'},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      Es wurde ein Zurücksetzen deines Admin-Passworts angefordert.
      Klick auf den Button, um ein neues Passwort zu vergeben. Der Link ist <strong>1 Stunde gültig</strong>.
    </p>
    <a href="{url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Neues Passwort festlegen →
    </a>
    <p style="margin:24px 0 0;font-size:13px;color:#9ca3af;">
      Falls der Button nicht funktioniert:<br>
      <a href="{url}" style="color:#6b7280;">{url}</a>
    </p>
    <p style="margin:16px 0 0;font-size:13px;color:#d1d5db;">
      Falls du das nicht warst, ignoriere diese E-Mail – dein Passwort bleibt unverändert.
    </p>"""
    _send(admin.email, f"Passwort zurücksetzen – {cfg['app_name']}", _wrap(content, color, cfg))


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
        {_info_row('Datum', de_date(event.datum))}
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


def _gross(s: str) -> str:
    """Nur den ersten Buchstaben groß – str.capitalize() würde „in 3 Wochen"
    zu „In 3 wochen" verstümmeln."""
    return s[:1].upper() + s[1:]


def send_einsatz_erinnerung(dienstleister, event):
    cfg = get_config()
    color = _brand_color(event.marke)
    # Versand läuft über ein Fenster [heute, heute+2] – die Restzeit echt ausrechnen
    # statt „In 2 Tagen" fest hinzuschreiben.
    wann = zeit_bis_text(event.datum)
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      kleine Erinnerung: <strong>{wann}</strong> hast du folgenden Einsatz. Wir freuen uns auf dich!
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', event.anlass)}
        {_info_row('Kunde', event.kunde_firma)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
        {_info_row('Ort', event.veranstaltungsort)}
      </table>
    </div>
    <p style="margin:0 0 8px;font-size:14px;color:#374151;">Alle Details findest du in deinem Briefing und im Portal:</p>
    <a href="https://kindsalabim-events.onrender.com/portal"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Zum Portal →
    </a>"""
    _send(dienstleister.email,
          f"📅 {_gross(wann)}: {event.anlass} bei {event.kunde_firma}",
          _wrap(content, color, cfg))


def send_bericht_erinnerung(dienstleister, event, magic_url: str):
    """Erinnert den Teamleiter nach dem Event, den Eventbericht auszufüllen.
    magic_url führt nach dem Login direkt zum Bericht-Formular."""
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      du warst Teamleiter bei diesem Einsatz – wie ist es gelaufen? Bitte fülle kurz den
      <strong>Eventbericht</strong> aus. Erst danach gilt das Event als abgeschlossen.
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', event.anlass)}
        {_info_row('Kunde', event.kunde_firma)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Ort', event.veranstaltungsort)}
      </table>
    </div>
    <a href="{magic_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Bericht ausfüllen →
    </a>
    <p style="margin:16px 0 0;font-size:13px;color:#9ca3af;">Dauert nur 1–2 Minuten. Fotos vom Event kannst du dort optional gleich mit hochladen.</p>"""
    _send(dienstleister.email,
          f"📝 Eventbericht: {event.anlass} bei {event.kunde_firma}",
          _wrap(content, color, cfg))


def send_teamleiter_info(event):
    """Info-Mail an den Kunden ~1 Woche vor dem Event: nennt den Teamleiter
    als Ansprechpartner am Veranstaltungstag (Name + Telefon)."""
    cfg = get_config()
    color = _brand_color(event.marke)
    tl = event.teamleiter
    tl_name = f"{tl.vorname} {tl.nachname}" if tl else ""
    tl_tel = (tl.telefon or "").strip() if tl else ""
    anrede = f"Hallo {event.kunde_kontakt}," if event.kunde_kontakt else "Guten Tag,"

    tel_row = _info_row('Telefon', tl_tel) if tl_tel else ""
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">{anrede}</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      bald ist es so weit – Ihr Event am <strong>{de_date(event.datum)}</strong> steht an.
      Wir freuen uns darauf!
    </p>
    <p style="margin:0 0 12px;font-size:15px;color:#374151;line-height:1.6;">
      Am Veranstaltungstag ist Ihr Ansprechpartner vor Ort:
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Teamleitung', tl_name)}
        {tel_row}
      </table>
    </div>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      Sollten vorab noch Fragen offen sein, kommen Sie gerne auf uns zu. Ansonsten
      wünschen wir Ihnen schon jetzt eine schöne Feier!
    </p>"""
    _send(event.kunde_email,
          f"Ihr Ansprechpartner für {event.anlass} am {de_date(event.datum)}",
          _wrap(content, color, cfg))


def send_frist_verlaengerung(dienstleister, event, admin_email: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 16px;font-size:15px;color:#374151;">
      <strong>{dienstleister.vorname} {dienstleister.nachname}</strong> hat für
      <strong>{event.anlass}</strong> ({de_date(event.datum)}) eine Fristverlängerung angefordert.
    </p>
    <p style="margin:0;font-size:14px;color:#6b7280;">Die Frist wurde automatisch um 2 Tage verlängert.</p>"""
    _send(admin_email,
          f"Fristverlängerung: {dienstleister.vorname} {dienstleister.nachname} – {event.anlass}",
          _wrap(content, color, cfg))


def send_material_erinnerung(event, admin_email: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    # Fenster [heute, heute+3 Wochen] – echte Restzeit statt „In 3 Wochen".
    wann = zeit_bis_text(event.datum)
    content = f"""
    <p style="margin:0 0 16px;font-size:16px;color:#111827;">📦 Material-Erinnerung</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      <strong>{_gross(wann)}</strong> findet folgendes Event statt, bei dem eine
      <strong>Bastelaktion</strong> gebucht wurde. Bitte Material rechtzeitig bestellen!
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', event.anlass)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Kunde', event.kunde_firma)}
        {_info_row('Gebuchte Aktionen', event.produkte)}
      </table>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">
      Diese Erinnerung wird automatisch bis spätestens 3 Wochen vor dem Event-Datum gesendet.
    </p>"""
    _send(admin_email,
          f"📦 Material bestellen: {event.anlass} am {de_date(event.datum)} – {event.kunde_firma}",
          _wrap(content, color, cfg))


_APP_BASE = "https://kindsalabim-events.onrender.com"


def send_admin_notification(to_email: str, titel: str, text: str = "", link: str = ""):
    """Generische Admin-Benachrichtigung – ein Glocken-Ereignis zusätzlich per E-Mail.
    `link` ist ein interner Pfad (z. B. /admin/events/12); wird absolut gemacht."""
    cfg = get_config()
    color = _brand_color("Kindsalabim")  # intern, neutrale Marke
    url = link if link.startswith("http") else (_APP_BASE + link if link else "")
    button = ""
    if url:
        button = (f'<a href="{url}" style="display:inline-block;background:{color};color:#ffffff;'
                  f'text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">'
                  f'In der App öffnen →</a>')
    body = (text or "").replace("\n", "<br>")
    content = f"""
    <p style="margin:0 0 12px;font-size:16px;color:#111827;font-weight:600;">{titel}</p>
    {f'<p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">{body}</p>' if body else ''}
    {button}
    <p style="margin:24px 0 0;font-size:13px;color:#9ca3af;">
      Diese E-Mail-Benachrichtigung kannst du in den App-Einstellungen abschalten.
    </p>"""
    _send(to_email, f"🔔 {titel}", _wrap(content, color, cfg))


LAGER_ADRESSE = "Lager Rüttenscheid"  # fester Abholort; bei Bedarf später pro Event/Konfig


def _transport_text(logistik_transport: str) -> str:
    return {"eigenes_auto": "mit deinem eigenen Auto",
            "transporter": "mit unserem Transporter"}.get(logistik_transport or "", "")


def send_material_abhol_erinnerung(event, logistiker, logistik_transport: str = ""):
    """3 Tage vor dem Event an den zugeteilten Logistiker: Material rechtzeitig abholen."""
    cfg = get_config()
    color = _brand_color(event.marke)
    tt = _transport_text(logistik_transport)
    transp_zeile = f"<br>Du nimmst es <strong>{tt}</strong> mit." if tt else ""
    wann = zeit_bis_text(event.datum)
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {logistiker.vorname},</p>
    <p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">
      kleine Erinnerung: <strong>{wann}</strong> ist dein Einsatz – bitte denk daran, das
      <strong>Material</strong> für das Event mitzunehmen.{transp_zeile}
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:20px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', event.anlass)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
        {_info_row('Abholort', LAGER_ADRESSE)}
        {_info_row('Material', event.material_info or '–')}
      </table>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">Wir melden uns nochmal, sobald das Material im Lager abholbereit ist.</p>"""
    subject = f"🚚 Material mitnehmen: {event.anlass} am {de_date(event.datum)}"
    _send(logistiker.email, subject, _wrap(content, color, cfg))


def send_material_bereit(event, logistiker):
    """Material steht im Lager bereit zur Abholung – an den zugeteilten Logistiker."""
    cfg = get_config()
    color = _brand_color(event.marke)
    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {logistiker.vorname},</p>
    <p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">
      gute Nachricht: Das <strong>Material steht im {LAGER_ADRESSE} bereit zur Abholung</strong>.
      Du kannst es jetzt abholen.
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:20px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', event.anlass)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Abholort', LAGER_ADRESSE)}
        {_info_row('Material', event.material_info or '–')}
      </table>
    </div>"""
    subject = f"📦 Material abholbereit: {event.anlass} am {de_date(event.datum)}"
    _send(logistiker.email, subject, _wrap(content, color, cfg))


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
        {_info_row('Datum', de_date(event.datum))}
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

    subject = f"Checkliste: {event.anlass} am {de_date(event.datum)} – bitte ausfüllen"
    _send(event.kunde_email, subject, _wrap(content, color, cfg))


def send_checklist_notification(event, admin_email: str, base_url: str):
    cfg = get_config()
    color = _brand_color(event.marke)
    detail_url = f"{base_url}/admin/events/{event.id}"
    content = f"""
    <p style="margin:0 0 16px;font-size:15px;color:#374151;">
      <strong>{event.kunde_firma}</strong> hat die Kunden-Checkliste für
      <strong>{event.anlass}</strong> ({de_date(event.datum)}) ausgefüllt.
    </p>
    <a href="{detail_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">
      Event ansehen →
    </a>"""

    subject = f"Checkliste eingereicht: {event.anlass} – {event.kunde_firma}"
    _send(admin_email, subject, _wrap(content, color, cfg))


def send_absage_admin(dienstleister, event, grund: str, base_url: str):
    """Benachrichtigt den Admin wenn ein bestätigter Dienstleister nachträglich absagt."""
    cfg = get_config()
    admin_email = cfg.get("admin_email", BACKUP_EMPFAENGER)
    color = _brand_color(event.marke)
    event_url = f"{base_url}/admin/events/{event.id}"
    grund_html = f"<p style='margin:12px 0 0;font-size:14px;color:#374151;'><strong>Grund:</strong> {_esc(grund)}</p>" if grund else ""

    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#b91c1c;font-weight:600;">⚠️ Nachträgliche Absage</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      <strong>{dienstleister.vorname} {dienstleister.nachname}</strong> hat seinen bestätigten
      Einsatz für <strong>{event.kunde_firma}</strong> abgesagt.
    </p>
    <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Event', f"{event.anlass} – {event.kunde_firma}")}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Dienstleister', f"{dienstleister.vorname} {dienstleister.nachname}")}
        {_info_row('Telefon', dienstleister.telefon or '–')}
      </table>
      {grund_html}
    </div>
    <a href="{event_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">
      Zum Event →
    </a>"""

    subject = f"⚠️ Absage: {dienstleister.vorname} {dienstleister.nachname} – {event.kunde_firma} ({de_date(event.datum)})"
    _send(admin_email, subject, _wrap(content, color, cfg))


def _budget_row(budget):
    """Budget-Zeile für die Anfrage-Mail – nur wenn ein Budget gesetzt ist."""
    if not budget:
        return ""
    return _info_row('Budget', f"{de_euro(budget)} € pauschal (inkl. Fahrtkosten)")


def send_verfuegbarkeitsanfrage(dienstleister, event, anfrage_id: int, base_url: str,
                                magic_url: str = "", als_logistiker: bool = False,
                                budget=None):
    cfg = get_config()
    color = _brand_color(event.marke)
    portal_url = magic_url or f"{base_url}/portal/login"

    logistik_block = ""
    if als_logistiker:
        if event.transporter_angeboten:
            transp = "Unser Transporter steht für dich zur Verfügung."
        else:
            transp = "Es steht kein Transporter zur Verfügung – nur mit eigenem Auto möglich."
        mat = f"<br><strong>Material:</strong> {event.material_info}" if event.material_info else ""
        logistik_block = f"""
    <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#1e40af;">🚚 Du wirst auch als Logistiker angefragt</p>
      <p style="margin:0;font-size:14px;color:#1e40af;line-height:1.6;">Du würdest das Material für dieses Event mitnehmen. {transp}{mat}<br>
      Im Portal wählst du, ob du es mit deinem eigenen Auto{(' oder unserem Transporter' if event.transporter_angeboten else '')} mitnimmst – oder ob du es nicht mitnehmen kannst.</p>
    </div>"""

    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      wir würden dich gerne für folgendes Event anfragen. Klick auf den Button – du bist
      sofort in deinem Portal und kannst deine Verfügbarkeit bestätigen.
    </p>

    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', event.anlass)}
        {_info_row('Datum', de_date(event.datum))}
        {_info_row('Uhrzeit', f"{event.startzeit} – {event.endzeit} Uhr")}
        {_info_row('Ort', plz_ort(event.veranstaltungsort))}
        {_info_row('Produkte', event.produkte)}
        {_budget_row(budget)}
      </table>
    </div>
    {logistik_block}

    <a href="{portal_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Jetzt antworten →
    </a>

    <p style="margin:20px 0 4px;font-size:13px;color:#9ca3af;">
      Der Link ist <strong>36 Stunden gültig</strong>. Danach kannst du dich jederzeit unter
      <a href="{base_url}/portal/login" style="color:#6b7280;">{base_url}/portal/login</a> anmelden.
    </p>
    <p style="margin:0 0 0;font-size:14px;color:#6b7280;">
      Bitte antworte innerhalb von {ANFRAGE_FRIST_TAGE} Tagen.
    </p>"""

    subject = f"Anfrage: {event.anlass} am {de_date(event.datum)}"
    _send(dienstleister.email, subject, _wrap(content, color, cfg))


def send_serie_anfrage(dienstleister, events, base_url: str, magic_url: str = "", budget=None):
    """Kombinierte Anfrage für ein mehrtägiges Event (mehrere Termintage).
    Eine Mail listet alle Tage; der Dienstleister kann im Portal jeden Tag einzeln zusagen."""
    cfg = get_config()
    leit = events[0]
    color = _brand_color(leit.marke)
    portal_url = magic_url or f"{base_url}/portal/login"

    tage_rows = ""
    for ev in events:
        zeit = f"{ev.startzeit} – {ev.endzeit} Uhr" if ev.startzeit and ev.endzeit else ""
        tage_rows += _info_row(de_date(ev.datum), zeit)

    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">Hallo {dienstleister.vorname},</p>
    <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">
      wir haben ein <strong>mehrtägiges Event</strong> und würden dich gerne anfragen.
      Klick auf den Button – in deinem Portal kannst du für <strong>jeden Tag einzeln</strong>
      zu- oder absagen.
    </p>

    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:20px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {_info_row('Anlass', leit.anlass)}
        {_info_row('Ort', plz_ort(leit.veranstaltungsort))}
        {_info_row('Produkte', leit.produkte)}
        {(_info_row('Budget je Tag', f"{de_euro(budget)} € pauschal (inkl. Fahrtkosten)") if budget else "")}
      </table>
    </div>

    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
      <p style="margin:0 0 12px;font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Termine ({len(events)})</p>
      <table cellpadding="0" cellspacing="0" width="100%">
        {tage_rows}
      </table>
    </div>

    <a href="{portal_url}"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Jetzt antworten →
    </a>

    <p style="margin:20px 0 4px;font-size:13px;color:#9ca3af;">
      Der Link ist <strong>36 Stunden gültig</strong>. Danach kannst du dich jederzeit unter
      <a href="{base_url}/portal/login" style="color:#6b7280;">{base_url}/portal/login</a> anmelden.
    </p>
    <p style="margin:0 0 0;font-size:14px;color:#6b7280;">
      Bitte antworte innerhalb von {ANFRAGE_FRIST_TAGE} Tagen.
    </p>"""

    subject = f"Anfrage: {leit.anlass} – {len(events)} Termine"
    _send(dienstleister.email, subject, _wrap(content, color, cfg))


def send_briefing(dienstleister_list, event, base_url: str, anhaenge=None, externe=None,
                  regeln: str = None, pdf_hinweis: bool = False):
    cfg = get_config()
    color = _brand_color(event.marke)
    is_kf = event.marke == "Knallfrosch"
    subject = f"Briefing: {event.anlass} bei {event.kunde_firma} am {de_date(event.datum)}"
    T = 'cellpadding="0" cellspacing="0" width="100%"'

    def ic(name):
        return _icon_b64(name, is_kf)

    # ── Team (Teamleitung zuerst, Künstler mit Sparte) ──
    tl_tint = "#ecf6ec" if is_kf else "#eef3fb"
    team_rows = ""
    sortiert = sorted(dienstleister_list,
                      key=lambda m: 0 if (event.teamleiter_id and m.id == event.teamleiter_id) else 1)
    for m in sortiert:
        is_tl = bool(event.teamleiter_id and m.id == event.teamleiter_id)
        voll_name = _esc(f"{m.vorname} {m.nachname}")
        sparte = sparte_label(m)
        if sparte:
            voll_name += f' <span style="color:#6b7280;font-weight:400;">{_esc(sparte)}</span>'
        if is_tl:
            name = (f'<strong style="color:{_ROT};">Teamleitung:</strong> '
                    f'<strong style="color:#111827;">{voll_name}</strong>')
        else:
            name = voll_name
        team_rows += _team_row(name, m.telefon, highlight=is_tl, tint=tl_tint)
    for e in (externe or []):
        ext_name = f'{_esc(e.name)} <span style="color:#6b7280;font-size:12px;">(extern)</span>'
        team_rows += _team_row(ext_name, e.telefon)

    # ── Veranstaltungsanschrift (Checkliste bevorzugt) ──
    an_firma = (_no_none(getattr(event, "cl_firma_name", "")) or _no_none(event.kunde_firma)).strip()
    an_strasse = _no_none(getattr(event, "cl_strasse", "")).strip()
    an_plz_ort = _no_none(getattr(event, "cl_plz_ort", "")).strip()
    if not an_strasse and not an_plz_ort:
        an_plz_ort = _no_none(event.veranstaltungsort).strip()
    adr = "<br>".join(_esc(x) for x in (an_firma, an_strasse, an_plz_ort) if x) or "–"

    # ── Ansprechpartner vor Ort: Checkliste (Kunde) → Vor-Ort-Felder → alter Buchungskontakt ──
    ap_name = (_no_none(getattr(event, "cl_ansprechpartner_name", ""))
               or _no_none(getattr(event, "vor_ort_name", ""))
               or _no_none(event.kunde_kontakt)).strip()
    ap_tel = (_no_none(getattr(event, "cl_ansprechpartner_mobil", ""))
              or _no_none(getattr(event, "vor_ort_telefon", ""))
              or _no_none(event.kunde_telefon)).strip()

    import ankunft as _ankunft
    ankunft_str = _ankunft.ankunft_anzeige(event)
    treffpunkt_str = _ankunft.treffpunkt_anzeige(event)
    ra = rechnung_anschrift(event.marke)

    # ── Karten (empfängerunabhängig – einmal bauen) ──────────────────────────────
    karten = _mail_card("Datum &amp; Uhrzeit", ic("zeitplan"), f"""<table {T}>
            {_info_row('Datum', de_date(event.datum))}
            {_info_row('Aktionszeit', f"{event.startzeit} – {event.endzeit} Uhr")}
            {_info_row_rot('Ankunft', ankunft_str)}
            {_info_row_rot('Treffpunkt', treffpunkt_str)}
          </table>""", color)

    karten += _mail_card("Veranstaltungsadresse", ic("standort"),
        f'<p style="margin:0;font-size:14px;color:#374151;line-height:1.6;">{adr}</p>', color)

    karten += _mail_card("Ansprechpartner Kunde", ic("nachricht"), f"""<table {T}>
            {_info_row('Name', ap_name)}
            {_info_row('Telefon', ap_tel)}
          </table>
          <p style="margin:12px 0 0;font-size:13px;color:#6b7280;line-height:1.5;">Kontakt zum Kunden läuft <strong>nur über die Teamleitung</strong>.</p>""", color)

    karten += _mail_card("Team", ic("team"), f'<table {T}>{team_rows}</table>', color)

    karten += _mail_card("Aktionen", ic("kreativaktion"),
        f'<p style="margin:0;font-size:14px;color:#111827;">{_esc(_no_none(event.produkte)) or "–"}</p>', color)

    # Standort & Parken – nur wenn Angaben vorhanden
    sp_rows = ""
    if _no_none(getattr(event, "cl_aufbauort", "")):
        sp_rows += _info_row("Aufbauort", event.cl_aufbauort)
    if _no_none(getattr(event, "cl_parkplatz", "")):
        sp_rows += _info_row("Parkplätze", event.cl_parkplatz)
    if sp_rows:
        karten += _mail_card("Standort &amp; Parken", ic("fahrzeug"), f"<table {T}>{sp_rows}</table>", color)

    # Dresscode & Verpflegung (Kleidungs-Hinweis steht immer)
    dc = (f"<table {T}>"
          + (_info_row("Teamkleidung", event.cl_teamkleidung) if _no_none(getattr(event, "cl_teamkleidung", "")) else "")
          + '<tr><td></td><td style="padding:2px 0 8px;font-size:13px;color:#6b7280;line-height:1.5;">Dazu bitte eine zur Familienveranstaltung passende, gepflegte Hose / Rock / Shorts tragen.</td></tr>'
          + (_info_row("Verpflegung", event.cl_verpflegung) if _no_none(getattr(event, "cl_verpflegung", "")) else "")
          + "</table>")
    karten += _mail_card("Dresscode &amp; Verpflegung", ic("einsatz"), dc, color)

    # Besonderes – nur wenn Inhalt
    bes = ""
    if _no_none(event.hinweise):
        bes += f'<p style="margin:0 0 8px;font-size:14px;color:#374151;line-height:1.55;white-space:pre-line;">{_esc(_no_none(event.hinweise).strip())}</p>'
    if _no_none(getattr(event, "cl_weitere_details", "")):
        bes += f'<p style="margin:0;font-size:14px;color:#374151;line-height:1.55;white-space:pre-line;">{_esc(_no_none(event.cl_weitere_details).strip())}</p>'
    if bes:
        karten += _mail_card("Besonderes", ic("kids_corner"), bes, color)

    # Rechnung senden an (je Marke eigene Anschrift + Mail)
    rechnung_inner = (
        f'<p style="margin:0;font-size:14px;color:#374151;line-height:1.6;">{"<br>".join(_esc(z) for z in ra["zeilen"])}</p>'
        f'<p style="margin:10px 0 0;font-size:14px;color:#374151;">Per Mail an: '
        f'<a href="mailto:{ra["mail"]}" style="color:{color};">{ra["mail"]}</a></p>')
    karten += _mail_card("Rechnung senden an", ic("dokument"), rechnung_inner, color)

    pdf_hinweis_html = ""
    if pdf_hinweis:
        pdf_hinweis_html = (
            '<p style="margin:6px 0 14px;font-size:14px;color:#374151;line-height:1.6;">'
            '&#128206; Dein Briefing hängt auch als <strong>PDF an dieser Mail</strong> – '
            'so kannst du es direkt aufs Handy speichern.</p>')

    portal_btn = f"""
        {pdf_hinweis_html}
        <p style="margin:6px 0 8px;font-size:14px;color:#374151;">Deine Jobs findest du jederzeit in deinem Portal:</p>
        <a href="{base_url}/portal" style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;margin-bottom:8px;">Zum Portal →</a>"""

    # Allgemeine Regeln – je „## "-Abschnitt eine eigene Karte
    regeln_html = ""
    for r_titel, r_punkte in regeln_abschnitte(regeln or "", event.marke):
        li = "".join(
            f'<tr><td style="padding:4px 8px 4px 0;color:{color};font-weight:700;vertical-align:top;">&#9656;</td>'
            f'<td style="padding:4px 0;font-size:14px;color:#374151;line-height:1.55;">{_esc(p)}</td></tr>'
            for p in r_punkte)
        regeln_html += _mail_card(_esc(r_titel), ic("checkliste"), f"<table {T}>{li}</table>", color)

    for d in dienstleister_list:
        content = f"""
        <p style="margin:0 0 6px;font-size:16px;color:#111827;">Hallo {_esc(d.vorname)},</p>
        <p style="margin:0 0 22px;font-size:15px;color:#374151;line-height:1.6;">
          hier ist dein Briefing für das bevorstehende Event. Bitte lies es sorgfältig durch.
        </p>
        {karten}
        {portal_btn}
        {regeln_html}"""
        _deliver(d.email, subject, _wrap(content, color, cfg), anhaenge)


def send_wiedervorlage_digest(to_email, wvs, heute):
    """Tägliche Sammel-Erinnerung an einen Admin: alle offenen Wiedervorlagen,
    die heute fällig oder überfällig sind. `wvs` = Liste von KundeWiedervorlage."""
    cfg = get_config()
    color = "#1D4E89"
    prio_dot = {"hoch": "#c0473f", "mittel": "#b07d1a", "niedrig": "#9ca3af"}
    anzahl = len(wvs)
    n_ueber = sum(1 for w in wvs if w.faellig and w.faellig < heute)

    rows = ""
    for w in wvs:
        ist_ueber = w.faellig and w.faellig < heute
        label = "überfällig" if ist_ueber else "heute fällig"
        label_color = "#b91c1c" if ist_ueber else "#b07d1a"
        dot = prio_dot.get(w.prioritaet, "#9ca3af")
        firma = w.kunde.firma if w.kunde else "—"
        rows += f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #f0f0f0;">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot};margin-right:8px;vertical-align:middle;"></span>
            <span style="font-size:14px;color:#111827;font-weight:500;">{w.titel}</span><br>
            <span style="font-size:13px;color:#6b7280;margin-left:16px;">{firma}</span>
          </td>
          <td style="padding:10px 0;border-bottom:1px solid #f0f0f0;text-align:right;white-space:nowrap;vertical-align:top;">
            <span style="font-size:13px;font-weight:600;color:{label_color};">{label}</span><br>
            <span style="font-size:12px;color:#9ca3af;">{de_date(w.faellig)}</span>
          </td>
        </tr>"""

    intro = f"{anzahl} Wiedervorlage{'n' if anzahl != 1 else ''} {'brauchen' if anzahl != 1 else 'braucht'} Aufmerksamkeit"
    if n_ueber:
        intro += f" – davon {n_ueber} überfällig"

    content = f"""
    <p style="margin:0 0 8px;font-size:16px;color:#111827;">🔔 Guten Morgen,</p>
    <p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">{intro}.</p>
    <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:24px;">{rows}</table>
    <a href="https://kindsalabim-events.onrender.com/admin/crm/dashboard"
       style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">
      Zum CRM-Dashboard →
    </a>
    <p style="margin:20px 0 0;font-size:13px;color:#9ca3af;">
      Diese Erinnerung kommt täglich, solange offene Wiedervorlagen fällig oder überfällig sind.
    </p>"""

    subject = f"🔔 {anzahl} Wiedervorlage{'n' if anzahl != 1 else ''} fällig"
    if n_ueber:
        subject += f" ({n_ueber} überfällig)"
    _send(to_email, subject, _wrap(content, color, cfg))


def send_backup(attachments, counts: dict):
    """Schickt die CSV-Dateien (Liste von (dateiname, bytes)) als Anhang an den Admin.
    counts: Beschriftung -> Anzahl (z. B. {'Events': 42, 'Rechnungen': 47, ...})."""
    cfg = get_config()
    color = "#003864"
    datum = datetime.today().strftime("%d.%m.%Y")
    zeilen = "".join(_info_row(label, str(n)) for label, n in counts.items())
    content = f"""
    <p style="margin:0 0 16px;font-size:16px;color:#111827;">🗄️ Wöchentliches Daten-Backup</p>
    <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
      Im Anhang findest du den aktuellen CSV-Export vom <strong>{datum}</strong>.
      Bewahre die E-Mail auf – sie dient als menschenlesbares Notfall-Backup.
    </p>
    <div style="background:#f9fafb;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
      <table cellpadding="0" cellspacing="0" width="100%">{zeilen}</table>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">
      Tipp: Die CSV-Dateien lassen sich direkt in Excel öffnen (Umlaute inklusive).
    </p>"""

    _deliver(BACKUP_EMPFAENGER, f"🗄️ Backup {datum} – Kindsalabim Events",
             _wrap(content, color, cfg), attachments)
