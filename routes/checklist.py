from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from typing import Optional

from database import get_db
from models import Event
from config import get_config
from choices import ZEITEN, de_date

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.globals["zeiten"] = ZEITEN

# Der Kunden-Link gilt bis 30 Tage nach dem Event – danach ist er abgelaufen (Roadmap 2.4).
CHECKLIST_ABLAUF_TAGE = 30


def _link_abgelaufen(ev, serie=None) -> bool:
    """Bei einer Serie zählt der letzte Termintag, nicht der Tag, an dem der Link hängt."""
    letzter = serie[-1] if serie else ev
    return bool(letzter.datum) and         date.today() > letzter.datum + timedelta(days=CHECKLIST_ABLAUF_TAGE)


def serie_von(db, ev) -> list:
    """Alle Termintage einer Serie, nach Datum. Bei einem einzelnen Tag leer.

    Mehrtägige Aufträge sind einzelne Events mit gemeinsamer serien_id. Die Kunden-
    Checkliste gilt für die ganze Serie: gemeinsame Angaben einmal, Zeiten und
    notfalls die Adresse je Tag (Aykut 29.09.2026, gebaut 10.10.2026)."""
    if not ev.serien_id:
        return []
    tage = (db.query(Event).filter(Event.serien_id == ev.serien_id)
            .order_by(Event.datum, Event.startzeit).all())
    return tage if len(tage) > 1 else []


async def _formular(request: Request):
    """Rohes Formular für die Felder je Termintag (aufbau_von_<id> usw.)."""
    return await request.form()


@router.get("/checklist/{token}", response_class=HTMLResponse)
def checklist_show(token: str, request: Request, db: Session = Depends(get_db)):
    ev = db.query(Event).filter(Event.checklist_token == token).first()
    if not ev:
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Link ungültig oder abgelaufen.</p>", status_code=404)
    if _link_abgelaufen(ev, serie_von(db, ev)):
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Dieser Link ist abgelaufen. Bitte melden Sie sich bei uns, falls Sie noch Angaben machen möchten.</p>", status_code=410)

    already_submitted = bool(ev.cl_eingereicht_am)
    return templates.TemplateResponse("checklist.html", {
        "request": request,
        "ev": ev,
        "serie": serie_von(db, ev),
        "already_submitted": already_submitted,
        "cfg": get_config(),
    })


@router.post("/checklist/{token}", response_class=HTMLResponse)
def checklist_submit(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    ansprechpartner_name:  str = Form(""),
    ansprechpartner_mobil: str = Form(""),
    rechnung_email:        str = Form(""),
    rechnung_firma:        str = Form(""),
    rechnung_strasse:      str = Form(""),
    rechnung_plz_ort:      str = Form(""),
    firma_name:            str = Form(""),
    strasse:               str = Form(""),
    plz_ort:               str = Form(""),
    aufbau_von:            str = Form(""),
    aufbau_bis:            str = Form(""),
    abbau_von:             str = Form(""),
    abbau_bis:             str = Form(""),
    anlieferung_vortag:    str = Form(""),
    anlieferung_von:       str = Form(""),
    anlieferung_bis:       str = Form(""),
    abholung_folgetag:     str = Form(""),
    abholung_von:          str = Form(""),
    abholung_bis:          str = Form(""),
    aufbau_bedingungen:    str = Form(""),
    aufbauort:             list = Form([]),
    verpflegung:           str = Form("Nein"),
    teamkleidung:          str = Form("Nein"),
    parkplatz:             str = Form(""),
    weitere_details:       str = Form(""),
    foto_freigabe:         str = Form(""),
    formular=Depends(_formular),
):
    ev = db.query(Event).filter(Event.checklist_token == token).first()
    if not ev:
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Link ungültig.</p>", status_code=404)
    if _link_abgelaufen(ev, serie_von(db, ev)):
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>Dieser Link ist abgelaufen. Bitte melden Sie sich bei uns, falls Sie noch Angaben machen möchten.</p>", status_code=410)
    if ev.cl_eingereicht_am:
        # Bereits eingereicht → nicht mehr überschreibbar (Roadmap 2.4). Die Danke-Seite
        # erscheint wie gehabt; Korrekturen macht das Büro über „Briefing bearbeiten".
        return templates.TemplateResponse("checklist.html", {
            "request": request,
            "ev": ev,
            "already_submitted": True,
            "cfg": get_config(),
        })

    serie = serie_von(db, ev)
    for tag in (serie or [ev]):
        _antworten_speichern(
            db, tag, ansprechpartner_name, ansprechpartner_mobil, rechnung_email,
            rechnung_firma, rechnung_strasse, rechnung_plz_ort, firma_name, strasse,
            plz_ort, aufbau_von, aufbau_bis, abbau_von, abbau_bis, anlieferung_vortag,
            anlieferung_von, anlieferung_bis, abholung_folgetag, abholung_von,
            abholung_bis, aufbau_bedingungen, aufbauort, verpflegung, teamkleidung,
            parkplatz, weitere_details, foto_freigabe)
        if serie:
            _tag_speichern(tag, formular)
            # Vortag-Anlieferung gehört nur zum ersten, Folgetag-Abholung nur zum
            # letzten Termin. Sonst stünde sie in jedem Tages-Briefing.
            if tag is not serie[0]:
                tag.cl_anlieferung_vortag = False
                tag.cl_anlieferung_von = tag.cl_anlieferung_bis = None
            if tag is not serie[-1]:
                tag.cl_abholung_folgetag = False
                tag.cl_abholung_von = tag.cl_abholung_bis = None
    db.commit()
    # Status automatisch aktualisieren
    from routes.admin import auto_status
    for tag in (serie or [ev]):
        tag.status = auto_status(tag, db)
    db.commit()

    # Glocke + (abschaltbare) Admin-Mail, bei einer Serie einmal für alle Tage
    from notifications import notify, mail_enabled
    termine = (f"{len(serie)} Termine ab {de_date(serie[0].datum)}" if serie
               else f"am {de_date(ev.datum)}")
    notify(db, "checkliste", f"Checkliste zurück: {ev.kunde_firma}",
           f"{ev.kunde_firma} hat die Checkliste für {ev.anlass} {termine} ausgefüllt.",
           f"/admin/events/{ev.id}", marke=ev.marke)
    db.commit()
    if mail_enabled(db, "checkliste"):
        from email_service import send_checklist_notification
        cfg = get_config()
        base_url = str(request.base_url).rstrip("/")
        send_checklist_notification(ev, cfg["admin_email"], base_url)

    return templates.TemplateResponse("checklist.html", {
        "request": request,
        "ev": ev,
        "serie": serie,
        "already_submitted": True,
        "cfg": get_config(),
    })


def _tag_speichern(ev, formular):
    """Felder je Termintag einer Serie: Auf-/Abbauzeit und, nur wenn angehakt, eine
    abweichende Adresse. Ohne Häkchen gilt die gemeinsame Adresse von oben."""
    def feld(name):
        return (formular.get(f"{name}_{ev.id}") or "").strip()
    for name in ("aufbau_von", "aufbau_bis", "abbau_von", "abbau_bis"):
        setattr(ev, f"cl_{name}", feld(name))
    if formular.get(f"andere_adresse_{ev.id}") == "Ja":
        for name in ("firma_name", "strasse", "plz_ort"):
            if feld(name):
                setattr(ev, f"cl_{name}", feld(name))


def _antworten_speichern(db, ev, ansprechpartner_name, ansprechpartner_mobil,
                         rechnung_email, rechnung_firma, rechnung_strasse, rechnung_plz_ort,
                         firma_name, strasse, plz_ort, aufbau_von, aufbau_bis, abbau_von,
                         abbau_bis, anlieferung_vortag, anlieferung_von, anlieferung_bis,
                         abholung_folgetag, abholung_von, abholung_bis, aufbau_bedingungen,
                         aufbauort, verpflegung, teamkleidung, parkplatz, weitere_details,
                         foto_freigabe):
    """Die Antworten der Checkliste an EIN Event schreiben (bei einer Serie: je Tag)."""
    ev.cl_ansprechpartner_name  = ansprechpartner_name
    ev.cl_ansprechpartner_mobil = ansprechpartner_mobil
    # „Für die Rechnung": abweichende Firmierung/Adresse/Mail am Event speichern;
    # die Mailadresse zusätzlich in die Kundenkartei übernehmen (nur wenn angegeben;
    # erscheint bewusst NICHT im Briefing).
    ev.cl_rechnung_email   = rechnung_email.strip() or None
    ev.cl_rechnung_firma   = rechnung_firma.strip() or None
    ev.cl_rechnung_strasse = rechnung_strasse.strip() or None
    ev.cl_rechnung_plz_ort = rechnung_plz_ort.strip() or None
    if ev.cl_rechnung_email and ev.kunde_id and ev.kunde:
        ev.kunde.rechnung_email = ev.cl_rechnung_email
    ev.cl_firma_name            = firma_name
    ev.cl_strasse               = strasse
    ev.cl_plz_ort               = plz_ort
    ev.cl_aufbau_von            = aufbau_von
    ev.cl_aufbau_bis            = aufbau_bis
    ev.cl_abbau_von             = abbau_von
    ev.cl_abbau_bis             = abbau_bis
    ev.cl_anlieferung_vortag    = (anlieferung_vortag == "Ja")
    ev.cl_anlieferung_von       = anlieferung_von.strip() or None
    ev.cl_anlieferung_bis       = anlieferung_bis.strip() or None
    ev.cl_abholung_folgetag     = (abholung_folgetag == "Ja")
    ev.cl_abholung_von          = abholung_von.strip() or None
    ev.cl_abholung_bis          = abholung_bis.strip() or None
    ev.cl_aufbau_bedingungen    = aufbau_bedingungen.strip() or None
    ev.cl_aufbauort             = ", ".join(aufbauort)
    ev.cl_verpflegung           = verpflegung
    ev.cl_teamkleidung          = teamkleidung
    ev.cl_parkplatz             = parkplatz
    # „Weitere Details" kann interne Vorab-Notizen des Büros enthalten (fürs Team-
    # Briefing). Die werden dem Kunden nie angezeigt und dürfen durch seine Eingabe
    # nicht verloren gehen → Kunden-Text wird ANGEHÄNGT statt überschrieben.
    neu = weitere_details.strip()
    alt = (ev.cl_weitere_details or "").strip()
    if neu and alt and neu not in alt:
        ev.cl_weitere_details = alt + "\n" + neu
    elif neu and not alt:
        ev.cl_weitere_details = neu
    # neu leer → vorhandene (interne) Notiz bleibt unverändert
    if foto_freigabe in ("Ja", "Nein"):
        ev.cl_foto_freigabe = foto_freigabe
        # Dauerhaft am Kundenprofil merken: Stammkunden füllen keine Checkliste mehr aus
        if ev.kunde_id:
            from models import Kunde
            kunde = db.query(Kunde).filter(Kunde.id == ev.kunde_id).first()
            if kunde:
                kunde.foto_freigabe = foto_freigabe
    ev.cl_eingereicht_am        = datetime.now().strftime("%d.%m.%Y %H:%M")
