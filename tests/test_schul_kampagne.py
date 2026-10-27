"""Schul-Kampagne (Aykut 27.10.2026): Essener Grundschulen, die OGS wird angeschrieben.
Schulen, bei denen Aykut schon war, bekommen „Ich war zuletzt …“; die Events-App
schickt dafür `vorlage` und `zuletzt` an den Assistenten (Vertrag 1.2). Kein Test
erreicht das Netz: urlopen ist gemockt."""
import io
import json
import urllib.request

import routes.crm as crm
from models import Kunde

CSV = ("Organisation;Art;Ort;Kontaktweg;Quelle;Veranstaltung;Zuletzt\n"
       "Testschule Bekannt;Grundschule;Essen;111111@schule.nrw.de;https://www.schulministerium.nrw.de/x;"
       "Zaubershow und Zauberworkshop für die OGS;am 23.10.2026 mit unseren Zaubershows bei Ihnen in der OGS\n"
       "Testschule Neu;Grundschule;Essen;222222@schule.nrw.de;https://www.schulministerium.nrw.de/y;"
       "Zaubershow und Zauberworkshop für die OGS;\n")


def _import(admin, text=CSV):
    return admin.post("/admin/crm/akquise/import",
                      files={"datei": ("schulen.csv", io.BytesIO(text.encode("utf-8")), "text/csv")},
                      follow_redirects=False)


def _gesendet(monkeypatch, kid):
    gesendet = {}

    class _Antwort:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        gesendet.update(json.loads(req.data.decode("utf-8")))
        return _Antwort()

    monkeypatch.setattr(crm, "get_config", lambda: {
        "assistent_api_url": "https://assistent.example", "assistent_api_secret": "s"})
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    crm.entwurf_anfordern(kid)
    return gesendet


def test_import_liest_zuletzt_und_uebergabe_schickt_vorlage(admin, db, monkeypatch):
    _import(admin)
    bekannt = db.query(Kunde).filter(Kunde.firma == "Testschule Bekannt").one()
    neu = db.query(Kunde).filter(Kunde.firma == "Testschule Neu").one()
    assert bekannt.zuletzt_bei_uns == "am 23.10.2026 mit unseren Zaubershows bei Ihnen in der OGS"
    assert neu.zuletzt_bei_uns is None
    g = _gesendet(monkeypatch, bekannt.id)
    assert g["vorlage"] == "schule"
    assert g["zuletzt"] == "am 23.10.2026 mit unseren Zaubershows bei Ihnen in der OGS"
    g = _gesendet(monkeypatch, neu.id)
    assert g["vorlage"] == "schule" and g["zuletzt"] == ""


def test_firma_bekommt_keine_schulvorlage(db, monkeypatch):
    k = Kunde(firma="Musikschule Beispiel GmbH", email="info@musik.example", herkunft="akquise",
              akquise_art="Firma", anlass="Sommerfest", pipeline_status="lead")
    db.add(k)
    db.commit()
    g = _gesendet(monkeypatch, k.id)
    assert g["vorlage"] == "" and g["zuletzt"] == ""


def test_zweiter_import_ergaenzt_fehlendes_zuletzt(admin, db):
    _import(admin, CSV.replace("am 23.10.2026", "am 24.10.2026").replace(
        "Testschule Neu;Grundschule;Essen;222222@schule.nrw.de;https://www.schulministerium.nrw.de/y;"
        "Zaubershow und Zauberworkshop für die OGS;",
        "Testschule Neu;Grundschule;Essen;222222@schule.nrw.de;https://www.schulministerium.nrw.de/y;"
        "Zaubershow und Zauberworkshop für die OGS;2023 mit einem Zauberworkshop bei Ihnen"))
    bekannt = db.query(Kunde).filter(Kunde.firma == "Testschule Bekannt").one()
    neu = db.query(Kunde).filter(Kunde.firma == "Testschule Neu").one()
    assert bekannt.zuletzt_bei_uns.startswith("am 23.10.2026")     # Gepflegtes bleibt
    assert neu.zuletzt_bei_uns == "2023 mit einem Zauberworkshop bei Ihnen"


def test_formular_zeigt_und_speichert_zuletzt(admin, db):
    _import(admin)                                   # idempotent, falls einzeln gestartet
    k = db.query(Kunde).filter(Kunde.firma == "Testschule Bekannt").one()
    html = admin.get(f"/admin/crm/{k.id}/edit").text
    assert 'name="zuletzt_bei_uns"' in html
    admin.post(f"/admin/crm/{k.id}/edit",
               data={"firma": k.firma, "email": k.email, "anlass": k.anlass, "ansprachemonat": "",
                     "zuletzt_bei_uns": "im Juli 2026 mit einer Zaubershow bei Ihnen in der OGS",
                     "pipeline_status": "lead"}, follow_redirects=False)
    db.refresh(k)
    assert k.zuletzt_bei_uns == "im Juli 2026 mit einer Zaubershow bei Ihnen in der OGS"
    assert "Ich war zuletzt im Juli 2026" in admin.get("/admin/crm/akquise?ansicht=jetzt").text
