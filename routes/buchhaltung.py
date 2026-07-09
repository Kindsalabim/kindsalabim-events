from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date, datetime
import io, csv

from database import get_db
from models import Rechnung
from auth import get_admin_user
from config import get_config
from choices import de_date, de_euro

router = APIRouter(prefix="/admin/buchhaltung")
templates = Jinja2Templates(directory="templates")
templates.env.filters["de_date"] = de_date
templates.env.filters["de_euro"] = de_euro


def tpl_context(request, **kw):
    return {"request": request, "cfg": get_config(), **kw}


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
           "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _monat_label(d) -> str:
    return f"{_MONATE[d.month - 1]} {d.year}" if d else "Ohne Datum"


def parse_float(s: str) -> float:
    try:
        return float(str(s).replace(",", ".").strip()) if str(s).strip() else 0.0
    except Exception:
        return 0.0


def compute(r: Rechnung) -> dict:
    brutto = r.brutto or 0.0
    pk = r.personalkosten or 0.0
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

    rechnungen = (
        db.query(Rechnung)
        .filter(Rechnung.datum >= date(jahr, 1, 1),
                Rechnung.datum <= date(jahr, 12, 31))
        .all()
    )

    # Nach Monat gruppieren (neuester Monat zuerst), innerhalb nach Rechnungsnummer
    # absteigend (zuletzt gestellte oben). Je Monat: Anzahl offener Rechnungen + Summe.
    from itertools import groupby

    def _ym(r):
        return (r.datum.year, r.datum.month) if r.datum else (0, 0)

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
        })

    totals = {
        "brutto":  round(sum(r.brutto or 0 for r in rechnungen), 2),
        "offen":   round(sum(r.brutto or 0 for r in rechnungen if not r.bezahlt), 2),
        "pk":      round(sum(r.personalkosten or 0 for r in rechnungen), 2),
        "mk":      round(sum(r.materialkosten or 0 for r in rechnungen), 2),
        "mwst":    round(sum(compute(r)["mwst"] for r in rechnungen), 2),
        "netto":   round(sum(compute(r)["netto"] for r in rechnungen), 2),
        "gewinn":  round(sum(compute(r)["nettogewinn"] for r in rechnungen), 2),
        "steuer":  round(sum(compute(r)["steuer"] for r in rechnungen), 2),
        "invest":  round(sum(compute(r)["invest"] for r in rechnungen), 2),
    }

    jahre = list(range(date.today().year, 2023, -1))

    today_iso = date.today().strftime("%Y-%m-%d")
    return templates.TemplateResponse("admin/buchhaltung.html", tpl_context(
        request, monatsgruppen=monatsgruppen, anzahl=len(rechnungen),
        jahr=jahr, jahre=jahre, totals=totals, today=today_iso,
    ))


# ── Neue Rechnung ──────────────────────────────────────────────────────────────

def _apply_form(r: Rechnung, datum: str, kunde: str, rgnr: str,
                brutto: str, personalkosten: str, materialkosten: str, notiz: str):
    try:
        r.datum = datetime.strptime(datum, "%Y-%m-%d").date()
    except Exception:
        r.datum = date.today()
    r.kunde = kunde.strip() or None
    r.rgnr = rgnr.strip() or None
    r.brutto = parse_float(brutto)
    r.personalkosten = parse_float(personalkosten)
    r.materialkosten = parse_float(materialkosten)
    r.notiz = notiz.strip() or None


@router.post("/neu")
def buchhaltung_neu(
    datum: str = Form(...),
    kunde: str = Form(""),
    rgnr: str = Form(""),
    brutto: str = Form("0"),
    personalkosten: str = Form("0"),
    materialkosten: str = Form("0"),
    notiz: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    r = Rechnung(bezahlt=False)
    _apply_form(r, datum, kunde, rgnr, brutto, personalkosten, materialkosten, notiz)
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
    return templates.TemplateResponse("admin/buchhaltung_edit.html",
                                      tpl_context(request, r=r))


@router.post("/{rid}/edit")
def buchhaltung_edit_save(
    rid: int,
    datum: str = Form(...),
    kunde: str = Form(""),
    rgnr: str = Form(""),
    brutto: str = Form("0"),
    personalkosten: str = Form("0"),
    materialkosten: str = Form("0"),
    notiz: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    r = db.query(Rechnung).filter(Rechnung.id == rid).first()
    if not r:
        return RedirectResponse("/admin/buchhaltung", status_code=303)
    _apply_form(r, datum, kunde, rgnr, brutto, personalkosten, materialkosten, notiz)
    db.commit()
    return RedirectResponse(f"/admin/buchhaltung?jahr={r.datum.year}", status_code=303)


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

    rechnungen = (
        db.query(Rechnung)
        .filter(Rechnung.datum >= date(jahr, 1, 1),
                Rechnung.datum <= date(jahr, 12, 31))
        .order_by(Rechnung.datum)
        .all()
    )

    out = io.StringIO()
    out.write("sep=;\n")  # Excel-Hint: Semikolon als Trennzeichen
    w = csv.writer(out, delimiter=";")
    w.writerow([
        "Nr", "Datum", "Kunde", "Rgnr", "Brutto", "Noch offen",
        "Personalkosten", "Materialkosten", "MwSt", "Netto",
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
            fmt(r.personalkosten or 0),
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
