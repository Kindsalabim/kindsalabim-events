"""Aktivitäts-Feed (Glocke) + einstellbare E-Mail-Benachrichtigungen.

- notify(...) schreibt immer eine Glocken-Zeile und schickt – bei den „neuen" Typen –
  zusätzlich eine generische Admin-Mail, sofern der Schalter in den Einstellungen an ist.
- Die bestehenden Mails für 'dl_absage' (send_absage_admin) und 'checkliste'
  (send_checklist_notification) bleiben an ihren Aufrufstellen; dort wird nur noch
  mail_enabled(...) davorgeschaltet. So bleibt das gewohnte (schön formatierte) Mailing
  erhalten, ist aber abschaltbar.
- Gelesen-Status ist PRO ADMIN (admins.notifications_gesehen_bis), ohne Extra-Tabelle.
"""
from datetime import datetime
from sqlalchemy.orm import Session

from models import Benachrichtigung, AppEinstellung, Admin

# typ -> (Anzeigename, generische Mail von notify() verschicken?, Default-Mail-an?)
# generische Mail: True  = notify() versendet die Mail selbst (neue Typen)
#                  False = Mail kommt von der Aufrufstelle (bestehende Spezial-Mail)
NOTIF_TYPEN = [
    ("dl_zusage",  "Dienstleister hat zugesagt",            True,  False),
    ("dl_absage",  "Dienstleister hat abgesagt",            False, True),
    ("dl_urlaub",  "Dienstleister hat Urlaub eingetragen",  True,  False),
    ("checkliste", "Kunde hat Checkliste zurückgeschickt",  False, True),
    ("bericht",    "Eventbericht wurde eingereicht",        True,  False),
]
_TYP_INFO = {t[0]: t for t in NOTIF_TYPEN}


def _mail_default(typ: str) -> bool:
    info = _TYP_INFO.get(typ)
    return bool(info[3]) if info else False


def mail_enabled(db: Session, typ: str) -> bool:
    """Ist die E-Mail-Benachrichtigung für diesen Typ aktiv? (DB-Schalter schlägt Default)."""
    row = db.query(AppEinstellung).filter(AppEinstellung.key == f"mail_{typ}").first()
    if row is None or row.value is None:
        return _mail_default(typ)
    return row.value == "1"


def set_mail_enabled(db: Session, typ: str, on: bool):
    row = db.query(AppEinstellung).filter(AppEinstellung.key == f"mail_{typ}").first()
    if row is None:
        row = AppEinstellung(key=f"mail_{typ}")
        db.add(row)
    row.value = "1" if on else "0"


def _active_admin_emails(db: Session):
    admins = db.query(Admin).filter(Admin.aktiv == True).all()  # noqa: E712
    return [a.email for a in admins if a.email and "@" in a.email]


def notify(db: Session, typ: str, titel: str, text: str = "", link: str = ""):
    """Schreibt eine Glocken-Benachrichtigung (committet NICHT – der Aufrufer committet).
    Verschickt bei den „neuen" Typen zusätzlich eine generische Admin-Mail, wenn aktiviert.
    Robust: Mailfehler werden geschluckt (kein 500 im Portal/Checklist)."""
    b = Benachrichtigung(
        typ=typ, titel=titel, text=text or None, link=link or None,
        erstellt_am=datetime.now().isoformat(timespec="seconds"),
    )
    db.add(b)

    info = _TYP_INFO.get(typ)
    sendet_generische_mail = bool(info and info[2])
    if sendet_generische_mail and mail_enabled(db, typ):
        try:
            from email_service import send_admin_notification
            for email in _active_admin_emails(db):
                send_admin_notification(email, titel, text, link)
        except Exception as e:  # Mail darf den Vorgang nie sprengen
            print(f"Admin-Notify-Mail fehlgeschlagen ({typ}): {e}")
    return b


def unread_count(db: Session, admin_email: str) -> int:
    ad = db.query(Admin).filter(Admin.email == admin_email).first()
    seen = ad.notifications_gesehen_bis if ad else None
    q = db.query(Benachrichtigung)
    if seen:
        q = q.filter(Benachrichtigung.erstellt_am > seen)
    return q.count()


def admin_notif_unread(request) -> int:
    """Jinja-Global für das Glocken-Badge – auf jeder Admin-Seite aufrufbar.
    Öffnet eine eigene DB-Session; schluckt alle Fehler (Badge darf nie eine Seite brechen)."""
    try:
        from auth import decode_token
        from database import SessionLocal
        token = request.cookies.get("admin_token")
        payload = decode_token(token) if token else None
        if not payload or payload.get("role") != "admin":
            return 0
        email = payload.get("sub") or payload.get("email")
        if not email:
            return 0
        db = SessionLocal()
        try:
            return unread_count(db, email)
        finally:
            db.close()
    except Exception:
        return 0
