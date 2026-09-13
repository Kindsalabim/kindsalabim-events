from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case
from sqlalchemy.orm import Session, joinedload
from datetime import date, datetime
import io, csv

from database import get_db
from models import Rechnung
from auth import get_admin_user
from config import get_config
from choices import de_date, de_euro, rechnung_faellig_am, rechnung_ueberfaellig

router = APIRouter(prefix="/admin/buchhaltung")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_euro"] = de_euro
templates.env.globals["rechnung_faellig_am"] = rechnung_faellig_am
templates.env.globals["rechnung_ueberfaellig"] = rechnung_ueberfaellig


def tpl_context(request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
           "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _monat_label(d) -> str:
    return f"{_MONATE[d.month - 1]} {d.year}" if d else "Ohne Datum"


def parse_float(s: str) -> float:
    """Deutsche Zahleneingaben robust parsen: „1.234,56", „1234,56", „1450".
    (Vorher machte ein Tausenderpunkt den Wert stillschweigend zu 0,00.)"""
    t = str(s).strip().replace("€", "").strip()
    if not t:
        return 0.0
    if "," in t:
        t = t.replace(".", "").replace(",", ".")   # 1.234,56 → 1234.56
    try:
        return float(t)
    except Exception:
        return 0.0


def compute(r: Rechnung) -> dict:
    brutto = r.brutto or 0.0
    pk = r.fremdleistungen or 0.0
    mk = r.materialkosten or 0.0
    netto = brutto / 1.19
    mwst = brutto - netto
    gewinn = netto - pk - mk
    return {
        "netto":       round(netto, 2),
        "mwst":        round(mwst, 2),
        "nettogewinn": round(gewinn, 2),
        "steuer":      round(gewinn * 0.40, 2),
        "invest":      round(gewinn * 0.10, 2),
    }


# ── Liste ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def buchhaltung_list(request: Request, jahr: int = 0,
                     db: Session = Depends(get_db),
                     user=Depends(get_admin_user)):
    if not jahr:
        jahr = date.today().year

    # Persönliche Marken-Ansicht: wer Kindsalabim abgewählt hat, sieht diese
    # Rechnungen (und ihre Summen) hier gar nicht erst.
    from marken import admin_marke, query_filter
    mfilter = admin_marke(db, user)
    rechnungen = query_filter(
        db.query(Rechnung).filter(Rechnung.datum >= date(jahr, 1, 1),
                                  Rechnung.datum <= date(jahr, 12, 31)),
        Rechnung.marke, mfilter, neutral_sichtbar=False).all()

    # Nach Monat gruppieren (neuester Monat zuerst), innerhalb nach Rechnungsnummer
    # absteigend (zuletzt gestellte oben). Je Monat: Anzahl offener Rechnungen + Summe.
    from itertools import groupby

    def _ym(r):
        return (r.datum.year, r.datum.month) if r.datum else (0, 0)

    def _summe(rows):
        return {
            "brutto": round(sum(r.brutto or 0 for r in rows), 2),
            "pk":     round(sum(r.fremdleistungen or 0 for r in rows), 2),
            "mk":     round(sum(r.materialkosten or 0 for r in rows), 2),
            "mwst":   round(sum(compute(r)["mwst"] for r in rows), 2),
            "netto":  round(sum(compute(r)["netto"] for r in rows), 2),
            "gewinn": round(sum(compute(r)["nettogewinn"] for r in rows), 2),
            "steuer": round(sum(compute(r)["steuer"] for r in rows), 2),
            "invest": round(sum(compute(r)["invest"] for r in rows), 2),
        }

    sortiert = sorted(rechnungen, key=lambda r: (_ym(r), r.rgnr or ""), reverse=True)
    monatsgruppen = []
    for _, grp in groupby(sortiert, key=_ym):
        grp = list(grp)
        offen = [r for r in grp if not r.bezahlt]
        monatsgruppen.append({
            "label": _monat_label(grp[0].datum),
            "rows": [{"r": r, **compute(r)} for r in grp],
            "offen_count": len(offen),
            "offen_summe": round(sum(r.brutto or 0 for r in offen), 2),
            "summe": _summe(grp),
        })

    totals = {
        "brutto":  round(sum(r.brutto or 0 for r in rechnungen), 2),
        "offen":   round(sum(r.brutto or 0 for r in rechnungen if not r.bezahlt), 2),
        "pk":      round(sum(r.fremdleistungen or 0 for r in rechnungen), 2),
        "mk":      round(sum(r.materialkosten or 0 for r in rechnungen), 2),
        "mwst":    round(sum(compute(r)["mwst"] for r in rechnungen), 2),
        "netto":   round(sum(compute(r)["netto"] for r in rechnungen), 2),
        "gewinn":  round(sum(compute(r)["nettogewinn"] for r in rechnungen), 2),
        "steuer":  round(sum(compute(r)["steuer"] for r in rechnungen), 2),
        "invest":  round(sum(compute(r)["invest"] for r in rechnungen), 2),
    }

    jahre = list(range(date.today().year, 2023, -1))

    event_vorschlaege = _event_vorschlaege(db, mfilter)

    # Für die Liste reichen ZÄHLER je Event (eine Sammelabfrage). Die Zeilen selbst
    # werden erst beim Aufklappen nachgeladen – vorher steckten sie für jede Rechnung
    # im HTML, auch ungeöffnet, und die Seite wurde über ein Megabyte groß.
    zaehler = _honorar_zaehler(db)
    for g in monatsgruppen:
        for row in g["rows"]:
            gesamt, offen = zaehler.get(row["r"].event_id, (0, 0))
            row["hat_honorare"] = gesamt > 0
            row["offen_honorare"] = offen

    today_iso = date.today().strftime("%Y-%m-%d")
    return templates.TemplateResponse("admin/buchhaltung.html", tpl_context(
        request, monatsgruppen=monatsgruppen, anzahl=len(rechnungen),
        jahr=jahr, jahre=jahre, totals=totals, today=today_iso,
        event_vorschlaege=event_vorschlaege, marken_filter=mfilter,
        offen_auto=request.query_params.get("offen", ""),
    ))


def _honorar_zaehler(db):
    """{event_id: (anzahl, davon offen)} – eine Abfrage für die ganze Seite."""
    from models import EventHonorar
    from sqlalchemy import func as _f
    rows = db.query(
        EventHonorar.event_id,
        _f.count(EventHonorar.id),
        _f.sum(case((EventHonorar.tatsaechlich == None, 1), else_=0)),   # noqa: E711
    ).group_by(EventHonorar.event_id).all()
    return {eid: (int(n or 0), int(offen or 0)) for eid, n, offen in rows}


def _event_vorschlaege(db, mfilter, aktuelle_rechnung: int = None):
    """Events für „Aus Event übernehmen": Material aus den Bestellungen,
    Fremdleistungen aus den Honorarzeilen.

    Ausgeblendet werden Events, die bereits eine Rechnung haben – an ein
    abgerechnetes Event lässt sich keine zweite Rechnung hängen. Beim Bearbeiten
    bleibt das eigene Event natürlich in der Liste (`aktuelle_rechnung`).
    """
    from models import Event, EventBestellung, EventHonorar
    from marken import query_filter
    from sqlalchemy import func as _f
    from datetime import timedelta
    heute = date.today()
    grenze = heute - timedelta(days=365)
    schon_abgerechnet = {
        r.event_id for r in db.query(Rechnung).filter(Rechnung.event_id != None).all()  # noqa: E711
        if r.id != aktuelle_rechnung}
    # Alle noch nicht abgerechneten Events – auch ohne erfasste Kosten. Die Auswahl
    # stellt die Verknüpfung her (Voraussetzung für die Aufschlüsselung), nicht nur
    # das Vorbefüllen; ein Event ohne Bestellungen braucht sie genauso.
    kandidaten = query_filter(
        db.query(Event).filter(Event.datum >= grenze),
        Event.marke, mfilter, neutral_sichtbar=False).all()
    # Abgerechnet wird nach dem Event: das zuletzt gelaufene zuerst, danach die
    # noch bevorstehenden (aufsteigend) – Vorkasse-Rechnungen bleiben erreichbar.
    kandidaten.sort(key=lambda e: (e.datum > heute,
                                   e.datum if e.datum > heute else -e.datum.toordinal()))
    # Material und Honorare je Event in zwei Sammelabfragen statt drei pro Event
    material_je_event = dict(
        db.query(EventBestellung.event_id, _f.sum(EventBestellung.betrag))
        .group_by(EventBestellung.event_id).all())
    honorare_je_event = {}
    for eid, gesch, ist in db.query(EventHonorar.event_id, EventHonorar.geschaetzt,
                                    EventHonorar.tatsaechlich).all():
        summe, offen = honorare_je_event.get(eid, (0.0, 0))
        honorare_je_event[eid] = (summe + (ist if ist is not None else (gesch or 0.0)),
                                  offen + (1 if ist is None else 0))
    vorschlaege = []
    for e in kandidaten:
        if e.id in schon_abgerechnet:
            continue
        fremd, offen = honorare_je_event.get(e.id, (0.0, 0))
        vorschlaege.append({
            "id": e.id, "datum": e.datum,
            "kunde_firma": e.kunde_firma or e.anlass or "Event",
            "summe": round(material_je_event.get(e.id) or 0, 2),
            "fremd": round(fremd, 2), "marke": e.marke, "offen": offen,
            "kuenftig": e.datum > heute,
        })
        if len(vorschlaege) >= 60:
            break
    return vorschlaege


# ── Fremdleistungen: Aufschlüsselung je Dienstleister ─────────────────────────

def _honorar_zeilen(db, event_id):
    """Honorarzeilen eines Events, Teamleitung zuerst wäre hier egal – sortiert
    nach Name, damit die Reihenfolge zwischen zwei Aufrufen stabil bleibt."""
    if not event_id:
        return []
    from models import EventHonorar, Dienstleister
    return (db.query(EventHonorar)
            .options(joinedload(EventHonorar.dienstleister))
            .join(Dienstleister, Dienstleister.id == EventHonorar.dienstleister_id)
            .filter(EventHonorar.event_id == event_id)
            .order_by(Dienstleister.vorname, Dienstleister.nachname).all())


@router.get("/{rid}/honorare", response_class=HTMLResponse)
def honorar_panel(rid: int, request: Request, db: Session = Depends(get_db),
                  user=Depends(get_admin_user)):
    """HTML-Fragment mit der Aufschlüsselung – wird beim Aufklappen nachgeladen."""
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if not r:
        return HTMLResponse("", status_code=404)
    zeilen = _honorar_zeilen(db, r.event_id)
    return templates.TemplateResponse("admin/_honorar_panel.html", tpl_context(
        request, r=r, honorare=zeilen,
        offen_honorare=sum(1 for h in zeilen if h.offen)))


@router.post("/honorar/{hid}")
def honorar_speichern(hid: int, betrag: str = Form(""), db: Session = Depends(get_db),
                      user=Depends(get_admin_user)):
    """Tatsächliches Honorar eintragen. Die Fremdleistungen aller Rechnungen zu
    diesem Event ziehen automatisch nach – auch rückwirkend, denn genau dafür ist
    die Aufschlüsselung da."""
    from models import EventHonorar
    h = db.query(EventHonorar).filter(EventHonorar.id == hid).first()
    if not h:
        return RedirectResponse("/admin/buchhaltung", status_code=303)
    wert = parse_float(betrag)
    if str(betrag).strip() == "":
        h.tatsaechlich = None          # Eingabe geleert → wieder offener Posten
        h.eingegangen_am = None
    else:
        h.tatsaechlich = wert
        h.eingegangen_am = date.today()
    db.commit()
    _fremdleistungen_nachziehen(db, h.event_id)
    return RedirectResponse(_zurueck(db, h.event_id), status_code=303)


@router.post("/honorar/{hid}/loeschen")
def honorar_loeschen(hid: int, db: Session = Depends(get_db),
                     user=Depends(get_admin_user)):
    """Zeile entfernen – z. B. wenn jemand krank abgesagt hat und nie eine
    Rechnung stellt."""
    from models import EventHonorar
    h = db.query(EventHonorar).filter(EventHonorar.id == hid).first()
    if not h:
        return RedirectResponse("/admin/buchhaltung", status_code=303)
    eid = h.event_id
    db.delete(h)
    db.commit()
    _fremdleistungen_nachziehen(db, eid)
    return RedirectResponse(_zurueck(db, eid), status_code=303)


def _fremdleistungen_nachziehen(db, event_id):
    """Summe der Honorarzeilen in die Rechnung(en) dieses Events schreiben."""
    if not event_id:
        return
    import honorare
    neu = honorare.summe(db, event_id)
    for r in db.query(Rechnung).filter(Rechnung.event_id == event_id).all():
        r.fremdleistungen = neu
    db.commit()


def _zurueck(db, event_id) -> str:
    """Zurück in das Jahr der zugehörigen Rechnung (sonst laufendes Jahr).
    `offen` klappt das Panel gleich wieder auf – man trägt meist mehrere
    Beträge nacheinander ein."""
    r = (db.query(Rechnung).filter(Rechnung.event_id == event_id).first()
         if event_id else None)
    jahr = r.datum.year if r and r.datum else date.today().year
    ziel = f"/admin/buchhaltung?jahr={jahr}"
    return f"{ziel}&offen={r.id}" if r else ziel


# ── Neue Rechnung ──────────────────────────────────────────────────────────────

def _apply_form(r: Rechnung, datum: str, kunde: str, rgnr: str,
                brutto: str, fremdleistungen: str, materialkosten: str, notiz: str,
                marke: str = None, event_id: str = ""):
    if marke in ("Kindsalabim", "Knallfrosch"):
        r.marke = marke
    try:
        r.datum = datetime.strptime(datum, "%Y-%m-%d").date()
    except Exception:
        r.datum = date.today()
    r.kunde = kunde.strip() or None
    r.rgnr = rgnr.strip() or None
    r.brutto = parse_float(brutto)
    r.fremdleistungen = parse_float(fremdleistungen)
    r.materialkosten = parse_float(materialkosten)
    r.notiz = notiz.strip() or None
    # "" = Zuordnung unverändert lassen · "0" = Zuordnung entfernen · sonst setzen
    if str(event_id).strip().isdigit():
        r.event_id = int(event_id) or None


@router.post("/neu")
def buchhaltung_neu(
    datum: str = Form(...),
    kunde: str = Form(""),
    rgnr: str = Form(""),
    brutto: str = Form("0"),
    fremdleistungen: str = Form("0"),
    materialkosten: str = Form("0"),
    notiz: str = Form(""),
    marke: str = Form(""),
    event_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    from marken import admin_marke, BEIDE
    r = Rechnung(bezahlt=False)
    # Ohne Auswahl: eigene Marken-Ansicht übernehmen (bei „beide" bleibt Kindsalabim)
    eigene = admin_marke(db, user)
    r.marke = "Kindsalabim" if eigene == BEIDE else eigene
    _apply_form(r, datum, kunde, rgnr, brutto, fremdleistungen, materialkosten, notiz,
                marke, event_id)
    db.add(r)
    db.commit()
    return RedirectResponse(f"/admin/buchhaltung?jahr={r.datum.year}", status_code=303)


# ── Bearbeiten ─────────────────────────────────────────────────────────────────

@router.get("/{rid}/edit", response_class=HTMLResponse)
def buchhaltung_edit_form(rid: int, request: Request,
                          db: Session = Depends(get_db),
                          user=Depends(get_admin_user)):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if not r:
        return RedirectResponse("/admin/buchhaltung", status_code=303)
    # Event nachträglich zuordnen – Bestandsrechnungen haben noch keine Verknüpfung,
    # ohne sie gibt es keine Fremdleistungs-Aufschlüsselung.
    from marken import admin_marke
    from models import Event
    zugeordnet = (db.query(Event).filter(Event.id == r.event_id).first()
                  if r.event_id else None)
    return templates.TemplateResponse("admin/buchhaltung_edit.html",
        tpl_context(request, r=r, zugeordnet=zugeordnet,
                    event_vorschlaege=_event_vorschlaege(db, admin_marke(db, user), rid)))


@router.post("/{rid}/edit")
def buchhaltung_edit_save(
    rid: int,
    datum: str = Form(...),
    kunde: str = Form(""),
    rgnr: str = Form(""),
    brutto: str = Form("0"),
    fremdleistungen: str = Form("0"),
    materialkosten: str = Form("0"),
    notiz: str = Form(""),
    marke: str = Form(""),
    event_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if not r:
        return RedirectResponse("/admin/buchhaltung", status_code=303)
    _apply_form(r, datum, kunde, rgnr, brutto, fremdleistungen, materialkosten, notiz,
                marke, event_id)
    db.commit()
    # Hängen am zugeordneten Event Honorarzeilen, sind sie die verlässlichere Quelle
    # als ein von Hand getippter Sammelbetrag – Summe daraus übernehmen.
    if r.event_id:
        from models import EventHonorar
        if db.query(EventHonorar).filter(EventHonorar.event_id == r.event_id).first():
            _fremdleistungen_nachziehen(db, r.event_id)
    return RedirectResponse(f"/admin/buchhaltung?jahr={r.datum.year}", status_code=303)


# ── Inline-Editieren (Excel-artig: Klick auf den Wert in der Liste) ─────────────

_INLINE_FELDER = {"brutto", "fremdleistungen", "materialkosten"}


@router.post("/{rid}/feld")
def buchhaltung_feld(rid: int, feld: str = Form(...), wert: str = Form(""),
                     db: Session = Depends(get_db), user=Depends(get_admin_user)):
    """Einzelnes Zahlenfeld direkt aus der Liste ändern (Whitelist – die berechneten
    Spalten wie MwSt/Netto/Gewinn sind bewusst nicht änderbar)."""
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if r and feld in _INLINE_FELDER:
        setattr(r, feld, parse_float(wert))
        db.commit()
    jahr = r.datum.year if r and r.datum else date.today().year
    return RedirectResponse(f"/admin/buchhaltung?jahr={jahr}", status_code=303)


# ── Bezahlt-Toggle ─────────────────────────────────────────────────────────────

@router.post("/{rid}/bezahlt")
def buchhaltung_bezahlt(rid: int, db: Session = Depends(get_db),
                        user=Depends(get_admin_user)):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if r:
        r.bezahlt = not r.bezahlt
        db.commit()
    jahr = r.datum.year if r else date.today().year
    return RedirectResponse(f"/admin/buchhaltung?jahr={jahr}", status_code=303)


# ── Steuerrücklage erledigt-Toggle ────────────────────────────────────────────

@router.post("/{rid}/steuer")
def buchhaltung_steuer(rid: int, db: Session = Depends(get_db),
                       user=Depends(get_admin_user)):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if r:
        r.steuer_erledigt = not r.steuer_erledigt
        db.commit()
    jahr = r.datum.year if r else date.today().year
    return RedirectResponse(f"/admin/buchhaltung?jahr={jahr}", status_code=303)


# ── Löschen ────────────────────────────────────────────────────────────────────

@router.post("/{rid}/loeschen")
def buchhaltung_loeschen(rid: int, db: Session = Depends(get_db),
                         user=Depends(get_admin_user)):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    jahr = r.datum.year if r else date.today().year
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse(f"/admin/buchhaltung?jahr={jahr}", status_code=303)


# ── CSV-Export ─────────────────────────────────────────────────────────────────

@router.get("/export.csv")
def buchhaltung_export(jahr: int = 0, db: Session = Depends(get_db),
                       user=Depends(get_admin_user)):
    if not jahr:
        jahr = date.today().year

    # Export folgt derselben Marken-Ansicht wie die Liste (sonst wären ausgeblendete
    # Rechnungen über den Export doch wieder sichtbar).
    from marken import admin_marke, query_filter
    rechnungen = query_filter(
        db.query(Rechnung).filter(Rechnung.datum >= date(jahr, 1, 1),
                                  Rechnung.datum <= date(jahr, 12, 31)),
        Rechnung.marke, admin_marke(db, user), neutral_sichtbar=False
    ).order_by(Rechnung.datum).all()

    out = io.StringIO()
    out.write("sep=;\n")  # Excel-Hint: Semikolon als Trennzeichen
    w = csv.writer(out, delimiter=";")
    w.writerow([
        "Nr", "Datum", "Kunde", "Rgnr", "Brutto", "Noch offen",
        "Fremdleistungen", "Materialkosten", "MwSt", "Netto",
        "Nettogewinn ca", "Steuerrücklage 40% UK1", "Invest-Rücklage 10% UK2",
    ])

    for i, r in enumerate(rechnungen, 1):
        c = compute(r)
        noch_offen = 0.0 if r.bezahlt else (r.brutto or 0.0)

        def fmt(v):
            return f"{v:.2f}".replace(".", ",")

        w.writerow([
            i,
            r.datum.strftime("%d.%m.%Y") if r.datum else "",
            r.kunde or "",
            r.rgnr or "",
            fmt(r.brutto or 0),
            fmt(noch_offen),
            fmt(r.fremdleistungen or 0),
            fmt(r.materialkosten or 0),
            fmt(c["mwst"]),
            fmt(c["netto"]),
            fmt(c["nettogewinn"]),
            fmt(c["steuer"]),
            fmt(c["invest"]),
        ])

    content = "﻿" + out.getvalue()   # UTF-8 BOM → Excel öffnet direkt korrekt
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=buchhaltung_{jahr}.csv"},
    )
