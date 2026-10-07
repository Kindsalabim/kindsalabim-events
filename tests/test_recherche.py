"""Kontakt-Recherche über die Claude-API (Aykut 05.10.2026).

Die API wird hier NIE wirklich gerufen – jeder Test setzt eine feste Antwort ein.
Geprüft wird das, was teuer wäre, wenn es falsch ist: dass nichts ohne Quelle in die
Akquise rutscht, dass die Sperrliste schon beim Anlegen greift und dass der
automatische Nachschub nicht in einer Dauerschleife Läufe stapelt.
"""
import json
from datetime import datetime

import httpx

import recherche
import vertrieb
from database import SessionLocal
from models import Kunde, Rechercheauftrag, VertriebSperre
from notifications import set_setting


def _leeren():
    s = SessionLocal()
    try:
        s.query(VertriebSperre).delete()
        s.query(Kunde).filter(Kunde.herkunft == "akquise").delete()
        # Die Test-DB wird zwischen Tests nicht zurückgesetzt: der Bestandskunde aus
        # dem Doppelten-Test würde sonst die späteren Übernahmen blockieren.
        s.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").delete()
        s.query(Rechercheauftrag).delete()
        s.commit()
        vertrieb.versand_stoppen(s, False)
        set_setting(s, recherche.DAUERAUFTRAG_KEY, "")
        s.commit()
    finally:
        s.close()


def _treffer(**abweichend):
    daten = {"organisation": "Beispiel Wohnbau eG", "art": "Firma", "ort": "Essen",
             "email": "info@beispiel-wohnbau-test.de", "ansprechpartner": "Frau Muster",
             "quelle": "https://beispiel-wohnbau-test.de/mieterfest",
             "anlass": "Mieterfest", "ansprachemonat": 4, "branche": "Wohnungswirtschaft",
             "beleg": "geprüft", "warum": "Richtet jährlich ein Mieterfest aus."}
    daten.update(abweichend)
    return daten


# ── Adressart und Anrede gehören zusammen ───────────────────────────────────

def test_sammelpostfach_bekommt_keinen_namen(db):
    """„Guten Tag Herr Schmidt" an info@ wirkt falsch: dort arbeiten zwanzig Schmidts.
    Der Name wird verworfen, auch wenn das Modell ihn mitliefert (Aykut 07.10.2026)."""
    _leeren()
    recherche.uebernehmen(db, [_treffer(email="info@beispiel-test.de",
                                        ansprechpartner="Herr Schmidt",
                                        mail_art="person")])
    k = db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first()
    assert k.mail_art == "funktion" and not k.ansprechpartner


def test_persoenliche_adresse_behaelt_den_namen(db):
    _leeren()
    recherche.uebernehmen(db, [_treffer(
        email="a.schmidt@beispiel-test.de", ansprechpartner="Herr Schmidt",
        mail_art="person", funktion="Leiter Unternehmenskommunikation",
        quelle_mail="https://beispiel-test.de/ansprechpartner")])
    k = db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first()
    assert k.mail_art == "person" and k.ansprechpartner == "Herr Schmidt"
    # Herkunft der Adresse und Rolle landen in der Notiz, fürs Anschreiben und die Akte
    assert "beispiel-test.de/ansprechpartner" in k.notizen
    assert "Leiter Unternehmenskommunikation" in k.notizen


def test_persoenliche_adresse_ohne_namen_gilt_als_funktion(db):
    """Ohne Namen keine persönliche Anrede, egal was das Modell behauptet."""
    _leeren()
    recherche.uebernehmen(db, [_treffer(email="a.schmidt@beispiel-test.de",
                                        ansprechpartner="", mail_art="person")])
    k = db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first()
    assert k.mail_art == "funktion"


def test_weitere_sammelpostfaecher_werden_erkannt(db):
    for adresse in ("presse@x-test.de", "marketing@x-test.de", "event@x-test.de",
                    "info-ruhr@x-test.de", "kontakt.essen@x-test.de"):
        art, person = recherche._adresse_einordnen(adresse,
                                                   {"ansprechpartner": "Herr Schmidt",
                                                    "mail_art": "person"})
        assert (art, person) == ("funktion", ""), adresse


def test_adressart_geht_an_den_assistenten(db, monkeypatch):
    """Der Assistent baut die Anrede, er muss die Art der Adresse kennen."""
    _leeren()
    recherche.uebernehmen(db, [_treffer(
        email="a.schmidt@beispiel-test.de", ansprechpartner="Herr Schmidt",
        mail_art="person", quelle_mail="https://beispiel-test.de/team")])
    k = db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first()

    import routes.crm as crm
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
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    crm.entwurf_anfordern(k.id)
    assert gesendet["mail_art"] == "person"
    assert gesendet["ansprechpartner"] == "Herr Schmidt"


# ── Übernahme: die Regeln, die Geld oder Ansehen kosten ─────────────────────

def test_treffer_wird_als_akquise_kontakt_angelegt(db):
    _leeren()
    neu, verworfen = recherche.uebernehmen(db, [_treffer()], auftrag_id=7)
    assert (neu, verworfen) == (1, 0)
    k = db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first()
    assert k.herkunft == "akquise" and k.pipeline_status == "lead"
    assert k.quelle.startswith("https://") and k.recherche_id == 7
    assert k.ansprachemonat == 4
    # info@ ist ein Sammelpostfach: kein Name, also auch keine Namensanrede
    assert k.mail_art == "funktion" and not k.ansprechpartner


def test_ohne_quelle_kein_kontakt(db):
    """Ein Modell erfindet plausible Firmen. Ohne Belegseite kommt nichts rein."""
    _leeren()
    neu, verworfen = recherche.uebernehmen(db, [
        _treffer(quelle=""),
        _treffer(organisation="Zweite GmbH", quelle="steht im Internet"),
    ])
    assert (neu, verworfen) == (0, 2)
    assert db.query(Kunde).filter(Kunde.herkunft == "akquise").count() == 0


def test_gesperrte_firma_wird_nicht_wieder_eingesammelt(db):
    """Sonst holt die Recherche einen Widerspruch beim nächsten Lauf zurück."""
    _leeren()
    vertrieb.sperren(db, "unternehmen", "Beispiel Wohnbau eG", "widerspruch")
    neu, verworfen = recherche.uebernehmen(db, [_treffer()])
    assert (neu, verworfen) == (0, 1)


def test_bekannte_organisation_wird_uebersprungen(db):
    _leeren()
    db.add(Kunde(firma="Beispiel Wohnbau eG", herkunft="bestand",
                 erstellt_am=datetime.now().isoformat(timespec="seconds")))
    db.commit()
    neu, verworfen = recherche.uebernehmen(db, [_treffer()])
    assert (neu, verworfen) == (0, 1)


def test_verworfene_zeilen_bekommen_einen_grund(db):
    """„1 verworfen" ohne Grund war nicht zu deuten (Aykut 07.10.2026, Lauf 1)."""
    _leeren()
    vertrieb.sperren(db, "unternehmen", "Gesperrte GmbH", "widerspruch")
    db.add(Kunde(firma="Schon Bekannt GmbH", herkunft="bestand",
                 erstellt_am=datetime.now().isoformat(timespec="seconds")))
    db.commit()
    protokoll = []
    recherche.uebernehmen(db, [
        _treffer(organisation="Ohne Quelle GmbH", quelle=""),
        _treffer(organisation="Ohne Mail GmbH", email="Kontaktformular"),
        _treffer(organisation="Gesperrte GmbH", email="info@gesperrt-test.de"),
        _treffer(organisation="Schon Bekannt GmbH", email="info@bekannt-test.de"),
    ], protokoll=protokoll)
    text = " / ".join(protokoll)
    assert "Ohne Quelle GmbH: kein Quelllink" in text
    assert "Ohne Mail GmbH: keine Mailadresse gefunden" in text
    assert "Kontaktformular" in text          # was das Modell geliefert hat
    assert "Gesperrte GmbH" in text and "gesperrt" in text.lower()
    assert "Schon Bekannt GmbH: steht schon im CRM" in text


def test_grund_steht_am_auftrag(db, monkeypatch):
    _leeren()
    a = recherche.auftrag_anlegen(db, "Fünf Firmen prüfen")
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: {
        "kontakte": [_treffer(organisation="Ohne Mail GmbH", email="")],
        "nicht_aufgenommen": [{"organisation": "BARMER", "grund": "kein eigenes Fest belegt"}],
        "suchen": 8, "kosten_cent": 30.0, "fehler": False, "meldung": ""})
    recherche.auftrag_ausfuehren(a.id)
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == a.id).first()
    assert a.status == "fertig" and a.verworfen == 1
    assert "Ohne Mail GmbH" in a.meldung and "keine Mailadresse" in a.meldung


def test_nicht_vorgeschlagene_firmen_werden_begruendet(db, monkeypatch):
    """Von fünf genannten Firmen kam nur eine zurück, ohne jede Erklärung."""
    _leeren()
    a = recherche.auftrag_anlegen(db, "Fünf Firmen prüfen")
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: {
        "kontakte": [], "suchen": 9, "kosten_cent": 28.0, "fehler": False,
        "nicht_aufgenommen": [
            {"organisation": "BARMER", "grund": "nur Sponsoring, kein eigenes Fest"},
            {"organisation": "Vonovia SE", "grund": "Fest belegt, keine Adresse gefunden"}],
        "meldung": "Das Modell hat keine Organisation aufgenommen. BARMER: nur Sponsoring, "
                   "kein eigenes Fest; Vonovia SE: Fest belegt, keine Adresse gefunden"})
    recherche.auftrag_ausfuehren(a.id)
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == a.id).first()
    assert "BARMER" in a.meldung and "Vonovia" in a.meldung and a.status == "fertig"


def test_begruendungen_landen_im_ergebnis(monkeypatch):
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    antwort = json.dumps({"kontakte": [],
                          "nicht_aufgenommen": [{"organisation": "TEDi",
                                                 "grund": "kein Fest gefunden"}]})
    monkeypatch.setattr(recherche.httpx, "post",
                        lambda *_a, **_k: _Antwort(_rohantwort(antwort)))
    ergebnis = recherche.suchen("Fünf Firmen")
    assert ergebnis["nicht_aufgenommen"] == ["TEDi: kein Fest gefunden"]
    assert "TEDi" in ergebnis["meldung"] and ergebnis["fehler"] is False


def test_ohne_mailadresse_kein_kontakt(db):
    """Nach dem ersten Lauf (06.10.2026): Firmen ohne Postfach kamen durch, ließen sich
    aber nicht übergeben und hätten als offene Leads den Nachschub blockiert."""
    _leeren()
    neu, verworfen = recherche.uebernehmen(db, [
        _treffer(email=""),
        _treffer(organisation="Nur Formular GmbH", email="Kontaktformular"),
        _treffer(organisation="Kaputt GmbH", email="info(at)kaputt.de"),
    ])
    assert (neu, verworfen) == (0, 3)
    assert db.query(Kunde).filter(Kunde.herkunft == "akquise").count() == 0


def test_mailadresse_wird_aus_dem_text_gezogen(db):
    """Manche Antworten liefern „Kontakt: info@firma.de (Zentrale)"."""
    _leeren()
    neu, _ = recherche.uebernehmen(db, [_treffer(email="Kontakt: info@beispiel-test.de (Zentrale)")])
    assert neu == 1
    assert db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG") \
             .first().email == "info@beispiel-test.de"


def test_unsinniger_ansprachemonat_wird_verworfen(db):
    _leeren()
    recherche.uebernehmen(db, [_treffer(ansprachemonat="Frühling")])
    assert db.query(Kunde).filter(Kunde.firma == "Beispiel Wohnbau eG").first().ansprachemonat is None


# ── Antwort einlesen ────────────────────────────────────────────────────────

def test_json_auch_im_codeblock_lesbar():
    roh = '```json\n{"kontakte": [{"organisation": "A"}]}\n```'
    assert recherche._json_aus_text(roh)["kontakte"][0]["organisation"] == "A"


def test_text_um_das_json_herum_stoert_nicht():
    roh = 'Ich habe gesucht:\n{"kontakte": []}\nDas war alles.'
    assert recherche._json_aus_text(roh) == {"kontakte": []}


def test_kaputte_antwort_ist_unterscheidbar_von_leer():
    """None heißt „nicht lesbar", {} heißt „gelesen, nichts drin". Vorher sah beides
    gleich aus, deshalb war ein Lauf ohne Treffer nicht zu deuten."""
    assert recherche._json_aus_text("Leider nichts gefunden.") is None
    assert recherche._json_aus_text('{"kontakte": []}') == {"kontakte": []}


def test_ohne_schluessel_kein_api_aufruf(monkeypatch):
    """Ohne Schlüssel darf der Lauf nicht abstürzen, sondern meldet es."""
    monkeypatch.setattr(recherche, "get_config", lambda: {})
    gerufen = []
    monkeypatch.setattr(recherche.httpx, "post", lambda *a, **k: gerufen.append(1))
    ergebnis = recherche.suchen("Egal")
    assert gerufen == [] and "Schlüssel" in ergebnis["meldung"]


def test_antwort_wird_zu_kontakten_und_kosten(monkeypatch):
    """Form der API-Antwort: Textblock mit JSON, usage für die Kostenanzeige."""
    class _Antwort:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "text",
                                 "text": json.dumps({"kontakte": [_treffer()]})}],
                    "usage": {"input_tokens": 20000, "output_tokens": 3000,
                              "server_tool_use": {"web_search_requests": 6}}}

    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post", lambda *a, **k: _Antwort())
    ergebnis = recherche.suchen("Wohnungsgesellschaften im Ruhrgebiet")
    assert len(ergebnis["kontakte"]) == 1 and ergebnis["suchen"] == 6
    # 20.000 Eingabe- und 3.000 Ausgabe-Token bei Sonnet: 4 + 3 Cent
    assert ergebnis["kosten_cent"] == 7.0 and ergebnis["meldung"] == ""


class _Antwort:
    """Minimale Nachbildung einer API-Antwort."""

    def __init__(self, daten):
        self._daten = daten
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._daten


def _rohantwort(text="", stop="end_turn", ein=1000, aus=500, suchen=2, inhalt=None):
    bloecke = list(inhalt or [])
    if text:
        bloecke.append({"type": "text", "text": text})
    return {"content": bloecke, "stop_reason": stop,
            "usage": {"input_tokens": ein, "output_tokens": aus,
                      "server_tool_use": {"web_search_requests": suchen}}}


def test_pausierte_suche_wird_fortgesetzt(monkeypatch):
    """Die Websuche läuft serverseitig und pausiert nach zehn Durchläufen. Ohne
    Fortsetzung kam gar kein Text an: Aykuts Lauf meldete „0 neu, 0 verworfen"."""
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    runden = []

    def _post(*_a, **k):
        runden.append(k["json"]["messages"])
        if len(runden) < 3:
            return _Antwort(_rohantwort(stop="pause_turn", inhalt=[
                {"type": "server_tool_use", "name": "web_search"}]))
        return _Antwort(_rohantwort(json.dumps({"kontakte": [_treffer()]})))

    monkeypatch.setattr(recherche.httpx, "post", _post)
    ergebnis = recherche.suchen("Zehn Firmen prüfen")
    assert len(ergebnis["kontakte"]) == 1 and ergebnis["meldung"] == ""
    # jede Fortsetzung schickt die Antwort zurück, ohne ein zusätzliches „Weiter"
    assert len(runden) == 3 and len(runden[-1]) == 3
    assert [n["role"] for n in runden[-1]] == ["user", "assistant", "assistant"]
    # Kosten und Suchen werden über alle Runden summiert
    assert ergebnis["suchen"] == 6


def test_dauerhafte_pause_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post",
                        lambda *_a, **_k: _Antwort(_rohantwort(stop="pause_turn")))
    ergebnis = recherche.suchen("Zu viele Firmen", max_fortsetzungen=2)
    assert ergebnis["fehler"] is True and "weniger Firmen" in ergebnis["meldung"]


def test_abgeschnittene_antwort_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post",
                        lambda *_a, **_k: _Antwort(_rohantwort('{"kontakte": [{"orga',
                                                              stop="max_tokens")))
    ergebnis = recherche.suchen("Egal")
    assert ergebnis["fehler"] is True and "abgeschnitten" in ergebnis["meldung"]


def test_leeres_ergebnis_ist_kein_fehler_aber_bekommt_eine_meldung(monkeypatch):
    """„0 neu, 0 verworfen" ohne jeden Hinweis war der eigentliche Mangel."""
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post",
                        lambda *_a, **_k: _Antwort(_rohantwort('{"kontakte": []}')))
    ergebnis = recherche.suchen("Egal")
    assert ergebnis["fehler"] is False and ergebnis["kontakte"] == []
    assert "keine Organisation aufgenommen" in ergebnis["meldung"]


def test_unlesbare_antwort_zeigt_den_anfang(monkeypatch):
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post", lambda *_a, **_k: _Antwort(
        _rohantwort("Ich konnte zu diesen Firmen nichts Belastbares finden.")))
    ergebnis = recherche.suchen("Egal")
    assert ergebnis["fehler"] is True
    assert "nicht Belastbares" in ergebnis["meldung"] or "nichts Belastbares" in ergebnis["meldung"]


def test_fehler_des_suchwerkzeugs_wird_sichtbar(monkeypatch):
    """Suchfehler kommen mit HTTP 200 als Ergebnisblock, lösen also nichts aus."""
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})
    monkeypatch.setattr(recherche.httpx, "post", lambda *_a, **_k: _Antwort(_rohantwort(
        inhalt=[{"type": "web_search_tool_result",
                 "content": {"error_code": "max_uses_exceeded"}}])))
    ergebnis = recherche.suchen("Egal")
    assert ergebnis["fehler"] is True and "max_uses_exceeded" in ergebnis["meldung"]


def test_leerer_lauf_gilt_nicht_als_fehlgeschlagen(db, monkeypatch):
    """Status „fehler" nur bei echten Fehlern, sonst sieht jeder leere Lauf kaputt aus."""
    _leeren()
    a = recherche.auftrag_anlegen(db, "Lauf ohne Treffer")
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: {
        "kontakte": [], "suchen": 4, "kosten_cent": 12.0, "fehler": False,
        "meldung": "Das Modell hat keine Organisation aufgenommen."})
    recherche.auftrag_ausfuehren(a.id)
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == a.id).first()
    assert a.status == "fertig" and a.meldung and a.kosten_cent == 12.0


def test_api_fehler_wird_gemeldet_statt_geworfen(monkeypatch):
    monkeypatch.setattr(recherche, "get_config", lambda: {"anthropic_api_key": "test"})

    def _krach(*_a, **_k):
        raise httpx.ConnectError("keine Verbindung")

    monkeypatch.setattr(recherche.httpx, "post", _krach)
    ergebnis = recherche.suchen("Egal")
    assert ergebnis["kontakte"] == [] and "fehlgeschlagen" in ergebnis["meldung"]


# ── Lauf und Kostenanzeige ─────────────────────────────────────────────────

def test_auftrag_laeuft_durch_und_haelt_kosten_fest(db, monkeypatch):
    _leeren()
    a = recherche.auftrag_anlegen(db, "Wohnungsgesellschaften im Ruhrgebiet")
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: {
        "kontakte": [_treffer(), _treffer(organisation="Ohne Beleg", quelle="")],
        "suchen": 5, "kosten_cent": 18.4, "meldung": ""})
    recherche.auftrag_ausfuehren(a.id)
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == a.id).first()
    assert a.status == "fertig" and a.anzahl == 1 and a.verworfen == 1
    assert a.suchen == 5 and a.kosten_cent == 18.4 and a.fertig_am


def test_fehler_wird_am_auftrag_vermerkt(db, monkeypatch):
    _leeren()
    a = recherche.auftrag_anlegen(db, "Irgendwas suchen")
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: {
        "kontakte": [], "suchen": 0, "kosten_cent": 0.0, "fehler": True,
        "meldung": "Recherche fehlgeschlagen: 529"})
    recherche.auftrag_ausfuehren(a.id)
    db.expire_all()
    a = db.query(Rechercheauftrag).filter(Rechercheauftrag.id == a.id).first()
    assert a.status == "fehler" and "529" in a.meldung


def test_fertiger_auftrag_laeuft_nicht_doppelt(db, monkeypatch):
    """Sonst kostet ein versehentlicher zweiter Aufruf echtes Geld."""
    _leeren()
    a = recherche.auftrag_anlegen(db, "Nur einmal bitte")
    a.status = "fertig"
    db.commit()
    gerufen = []
    monkeypatch.setattr(recherche, "suchen", lambda *_a, **_k: gerufen.append(1) or {
        "kontakte": [], "suchen": 0, "kosten_cent": 0.0, "meldung": ""})
    recherche.auftrag_ausfuehren(a.id)
    assert gerufen == []


# ── Automatischer Nachschub ────────────────────────────────────────────────

def test_ohne_dauerauftrag_kein_automatischer_lauf(db):
    _leeren()
    assert recherche.nachschub_pruefen(db) is None


def test_nachschub_startet_erst_unter_der_grenze(db):
    _leeren()
    set_setting(db, recherche.DAUERAUFTRAG_KEY, "Veranstalter von Familienfesten")
    db.commit()
    for i in range(recherche.NACHSCHUB_GRENZE):
        db.add(Kunde(firma=f"Vorrat {i}", herkunft="akquise", pipeline_status="lead",
                     erstellt_am=datetime.now().isoformat(timespec="seconds")))
    db.commit()
    assert recherche.nachschub_pruefen(db) is None
    db.query(Kunde).filter(Kunde.firma == "Vorrat 0").delete()
    db.commit()
    auftrag = recherche.nachschub_pruefen(db)
    assert auftrag and auftrag.automatisch is True


def test_nachschub_stapelt_keine_laeufe(db):
    """Ein hängender oder fehlgeschlagener Lauf darf nicht täglich einen neuen anlegen."""
    _leeren()
    set_setting(db, recherche.DAUERAUFTRAG_KEY, "Veranstalter von Familienfesten")
    db.commit()
    erster = recherche.nachschub_pruefen(db)
    assert erster is not None
    assert recherche.nachschub_pruefen(db) is None
    assert db.query(Rechercheauftrag).count() == 1


# ── Oberfläche und Cron ────────────────────────────────────────────────────

def test_recherche_starten_ueber_die_seite(admin, db, monkeypatch):
    _leeren()
    gerufen = []
    monkeypatch.setattr(recherche, "auftrag_ausfuehren", lambda aid: gerufen.append(aid))
    r = admin.post("/admin/crm/akquise/recherche",
                   data={"auftrag": "Stadtwerke im Ruhrgebiet mit Familienfest",
                         "modell": recherche.MODELL_RECHERCHE}, follow_redirects=False)
    assert r.status_code == 303 and "gestartet=1" in r.headers["location"]
    a = db.query(Rechercheauftrag).order_by(Rechercheauftrag.id.desc()).first()
    assert a.auftrag.startswith("Stadtwerke") and gerufen == [a.id]


def test_leerer_auftrag_startet_nichts(admin, db):
    _leeren()
    r = admin.post("/admin/crm/akquise/recherche", data={"auftrag": "kurz"},
                   follow_redirects=False)
    assert r.status_code == 303 and "rfehler" in r.headers["location"]
    assert db.query(Rechercheauftrag).count() == 0


def test_fremdes_modell_wird_nicht_uebernommen(admin, db):
    """Sonst könnte ein manipuliertes Formular ein beliebig teures Modell wählen."""
    _leeren()
    admin.post("/admin/crm/akquise/recherche",
               data={"auftrag": "Veranstalter von Stadtfesten", "modell": "teuer-gpt"},
               follow_redirects=False)
    a = db.query(Rechercheauftrag).order_by(Rechercheauftrag.id.desc()).first()
    assert a.modell == recherche.MODELL_RECHERCHE


def test_seite_zeigt_auftraege_und_kosten(admin, db):
    _leeren()
    a = recherche.auftrag_anlegen(db, "Wohnungsgesellschaften mit Mieterfest")
    a.status, a.anzahl, a.kosten_cent = "fertig", 12, 23.0
    db.commit()
    html = admin.get("/admin/crm/akquise").text
    assert "Wohnungsgesellschaften mit Mieterfest" in html
    assert "12 neu" in html and "0,23" in html


def test_lauf_ansicht_zeigt_nur_die_kontakte_dieses_laufs(admin, db):
    """Ohne diese Ansicht war nach einem Lauf nicht zu sehen, was er gebracht hat."""
    _leeren()
    a = recherche.auftrag_anlegen(db, "Wohnungsgesellschaften mit Mieterfest")
    recherche.uebernehmen(db, [_treffer()], auftrag_id=a.id)
    recherche.uebernehmen(db, [_treffer(organisation="Aus anderem Lauf GmbH",
                                       email="info@anderer-lauf.example")], auftrag_id=a.id + 99)
    html = admin.get(f"/admin/crm/akquise?lauf={a.id}").text
    assert "Beispiel Wohnbau eG" in html
    assert "Aus anderem Lauf GmbH" not in html
    assert "Gefiltert auf Lauf" in html
    # ohne Filter stehen beide da
    alle = admin.get("/admin/crm/akquise").text
    assert "Beispiel Wohnbau eG" in alle and "Aus anderem Lauf GmbH" in alle


def test_fertiger_lauf_verlinkt_seine_treffer(admin, db):
    _leeren()
    a = recherche.auftrag_anlegen(db, "Verlinkungstest")
    a.status, a.anzahl = "fertig", 4
    db.commit()
    assert f'href="/admin/crm/akquise?lauf={a.id}"' in admin.get("/admin/crm/akquise").text


def test_dauerauftrag_speichern(admin, db):
    _leeren()
    admin.post("/admin/crm/akquise/dauerauftrag",
               data={"auftrag": "Aussteller auf Familienfesten im Ruhrgebiet"},
               follow_redirects=False)
    from notifications import get_setting
    assert "Aussteller" in get_setting(db, recherche.DAUERAUFTRAG_KEY, "")


def test_cron_nachschub_braucht_secret(client):
    assert client.get("/cron/recherche-nachschub").status_code == 401


def test_cron_nachschub_startet_lauf(client, db, monkeypatch):
    _leeren()
    set_setting(db, recherche.DAUERAUFTRAG_KEY, "Veranstalter von Familienfesten")
    db.commit()
    monkeypatch.setattr(recherche, "auftrag_ausfuehren", lambda aid: None)
    from config import get_config
    r = client.get("/cron/recherche-nachschub",
                   headers={"X-Cron-Secret": get_config().get("cron_secret", "")})
    assert r.status_code == 200 and r.json()["gestartet"] is True
