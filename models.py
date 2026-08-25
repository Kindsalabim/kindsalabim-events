from sqlalchemy import Column, Integer, String, Text, Date, Time, ForeignKey, Boolean, Float, Table, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    anlass = Column(String, nullable=False)
    datum = Column(Date, nullable=False)         # echtes Datum (Anzeige TT.MM.JJJJ)
    startzeit = Column(String, nullable=False)   # HH:MM
    endzeit = Column(String, nullable=False)
    veranstaltungsort = Column(Text, nullable=False)
    kunde_firma = Column(String, nullable=False)
    kunde_adresse = Column(Text)                 # Firmenadresse des Kunden (intern, NICHT im Briefing)
    kunde_kontakt = Column(String)               # Buchungs-/E-Mail-Kontakt beim Kunden (intern)
    kunde_telefon = Column(String)
    kunde_email = Column(String)
    # Ansprechpartner vor Ort (fürs Team-Briefing) – kann vom Buchungskontakt abweichen.
    # Briefing-Priorität: Checkliste (cl_ansprechpartner_*) → vor_ort_* → alter kunde_kontakt.
    vor_ort_name = Column(String)
    weitere_ansprechpartner = Column(Text)  # JSON [{"name","telefon"}] – zusätzliche Ansprechpartner (Formular + Briefing)
    privatkunde = Column(Boolean, default=False)  # Vorkasse: Rechnung soll 14 Tage VOR dem Event raus (Cron-Erinnerung)
    vorkasse_erinnert = Column(Boolean, default=False)       # Vorkasse-Erinnerung schon gesendet? (Idempotenz)
    rechnung_mail_erinnert = Column(Boolean, default=False)  # Hinweis auf spezielle Rechnungs-Mail nach dem Event gesendet?
    vor_ort_telefon = Column(String)
    produkte = Column(Text)                      # kommagetrennt
    anzahl_teamer = Column(Integer, default=0)
    anzahl_kuenstler = Column(Integer, default=0)
    hinweise = Column(Text)
    aufbau_ab = Column(String)
    parkplatz = Column(String)
    outdoor_indoor = Column(String)
    verpflegung = Column(Boolean, default=False)     # Legacy: kommt jetzt aus der Checkliste (cl_verpflegung)
    teamkleidung = Column(Boolean, default=True)     # Legacy: kommt jetzt aus der Checkliste (cl_teamkleidung)
    material_mitnahme = Column(Boolean, default=False)  # Materialtransport nötig? steuert Logistik-Bedarf + 3-Wochen-Erinnerung
    material_bestellt = Column(Boolean, default=False)  # Material wurde bestellt – Bedingung für "Planung fertig"
    # Logistik / Materialtransport
    material_info = Column(Text)                         # Admin-Hinweis zur Menge/zum Transport (für Logistiker sichtbar)
    transporter_angeboten = Column(Boolean, default=False)  # Firmen-Transporter steht für dieses Event zur Verfügung
    logistiker_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=True)  # zugewiesener Material-Fahrer
    ankunft_modus = Column(String, default="auto")  # auto|30|45|60|90|eigen|sonderfall (Vorlauf vor Aktionsbeginn)
    ankunft_text  = Column(Text)                     # Freitext für Sonderfall (z. B. "Aufbau am Vortag bis 14 Uhr")
    treffpunkt    = Column(String)                   # Treffpunkt-Text fürs Team (Default "vor dem Haupteingang")
    material_bereit = Column(Boolean, default=False)     # Material im Lager abholbereit
    material_bereit_gesendet = Column(Boolean, default=False)        # "bereit zur Abholung"-Mail verschickt?
    material_abhol_erinnerung_gesendet = Column(Boolean, default=False)  # 3-Tage-Abhol-Erinnerung verschickt?
    material_erinnerung_gesendet = Column(Boolean, default=False)    # 3-Wochen-Bestell-Erinnerung verschickt?
    status = Column(String, default="Gebucht")   # Gebucht → Dienstleister angefragt → Checkliste geschickt/eingegangen → Planung fertig → Briefing gesendet → Abgeschlossen · Abgesagt
    marke = Column(String, default="Kindsalabim")  # Kindsalabim, Knallfrosch
    teamleiter_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=True)
    kunde_id = Column(Integer, ForeignKey("kunden.id"), nullable=True)  # CRM-Verknüpfung (optional)
    kalender_event_id = Column(String, nullable=True)  # Google-Kalender-Event-ID (Sync)
    serien_id = Column(String, nullable=True, index=True)  # mehrtägiges Event: gemeinsamer Token aller Termintage (None = einzelner Tag)
    rechnung_gestellt = Column(Boolean, default=False)  # Bedingung für "Abgeschlossen"
    teamleiter_mail_gesendet = Column(Boolean, default=False)  # Info-Mail an Kunden (1 Woche vorher) versendet?
    bericht_erinnerung_am = Column(String)  # ISO-Datetime der letzten Bericht-Erinnerung an den Teamleiter (None = nie)
    briefing_gesendet_am = Column(String)   # ISO-Datetime des (letzten) Briefing-Versands – schaltet den Portal-Download frei

    @property
    def briefing_verfuegbar(self):
        """Portal-Download erst nach dem Briefing-Versand (vorher wäre die PDF
        unvollständig und sorgt für Rückfragen). Status-Fallback deckt Events ab,
        deren Briefing vor Einführung des Zeitstempels verschickt wurde."""
        return bool(self.briefing_gesendet_am) or self.status in ("Briefing gesendet", "Abgeschlossen")

    # Eventbericht (vom Teamleiter nach dem Event im Portal ausgefüllt)
    bericht_eingereicht_am = Column(String)
    bericht_anzahl_kinder  = Column(Integer)   # Legacy (Freitext-Zahl); neu: bericht_kinder (Bucket)
    bericht_kinder         = Column(String)    # Multiple-Choice-Bucket, z. B. "20–50" (+ optional angehängter Text)
    bericht_verlauf        = Column(Text)
    bericht_probleme       = Column(Text)
    bericht_kundenfeedback = Column(Text)

    # Kunden-Checkliste
    checklist_token = Column(String, unique=True, nullable=True)
    cl_ansprechpartner_name  = Column(String)
    cl_ansprechpartner_mobil = Column(String)
    cl_rechnung_email = Column(String)  # aus der Kunden-Checkliste: Mailadresse für den Rechnungsversand (NICHT fürs Briefing)
    cl_anlieferung_vortag = Column(Boolean, default=False)  # Anlieferung am Vortag möglich?
    cl_anlieferung_von    = Column(String)                   # HH:MM
    cl_anlieferung_bis    = Column(String)
    cl_abholung_folgetag  = Column(Boolean, default=False)   # Abholung am Folgetag/Montag möglich?
    cl_abholung_von       = Column(String)
    cl_abholung_bis       = Column(String)
    cl_aufbau_bedingungen = Column(Text)                     # z. B. "Aufbau muss am Vortag erfolgen"
    cl_rechnung_firma   = Column(String)  # abweichende Firmierung / Rechnungsempfänger (Checkliste, "Für die Rechnung")
    cl_rechnung_strasse = Column(String)
    cl_rechnung_plz_ort = Column(String)
    cl_firma_name            = Column(String)
    cl_strasse               = Column(String)
    cl_plz_ort               = Column(String)
    cl_aufbau_von            = Column(String)
    cl_aufbau_bis            = Column(String)
    cl_abbau_von             = Column(String)
    cl_abbau_bis             = Column(String)
    cl_aufbauort             = Column(String)   # kommagetrennt: Indoor, Outdoor, …
    cl_verpflegung           = Column(String)   # "Ja" / "Nein"
    cl_teamkleidung          = Column(String)   # "Ja" / "Nein"
    cl_parkplatz             = Column(Text)
    cl_weitere_details       = Column(Text)     # Freitext „Weitere Details" (Kunde-Checkliste / Briefing)
    cl_eingereicht_am        = Column(String)
    checkliste_uebersprungen = Column(Boolean, default=False)  # Stammkunde: keine Kunden-Checkliste nötig
    zaubershow_event = Column(Boolean, default=False)  # Reines Zaubershow-Event: Firma/Ort/Aktion optional, kein Checkliste/Briefing/Bericht

    teamleiter = relationship("Dienstleister", foreign_keys=[teamleiter_id])
    logistiker = relationship("Dienstleister", foreign_keys=[logistiker_id])
    kunde = relationship("Kunde", back_populates="events", foreign_keys=[kunde_id])
    anfragen = relationship("Verfuegbarkeitsanfrage", back_populates="event", cascade="all, delete-orphan")
    dateien  = relationship("EventDatei", back_populates="event", cascade="all, delete-orphan")
    bastelvorschlaege = relationship("Bastelvorschlag", cascade="all, delete-orphan")
    externe_teamer = relationship("ExternerTeamer", cascade="all, delete-orphan")
    bestellungen   = relationship("EventBestellung", cascade="all, delete-orphan")


class ExternerTeamer(Base):
    """Einmaliges Team-Mitglied für genau ein Event (z. B. von einer externen Agentur),
    das nicht im Dienstleister-Stamm steht. Erscheint nur in der Team-Liste des Briefings."""
    __tablename__ = "externe_teamer"
    id       = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    name     = Column(String, nullable=False)
    telefon  = Column(String)


class Dienstleister(Base):
    __tablename__ = "dienstleister"

    id = Column(Integer, primary_key=True, index=True)
    vorname = Column(String, nullable=False)
    nachname = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    telefon = Column(String)
    strasse = Column(String)
    plz = Column(String)
    stadt = Column(String)
    rolle = Column(String, default="Teamer")     # Teamer, Künstler, Beides
    kuenstler_sparte = Column(String)            # Kinderschminke, Ballonkünstler, Schminke + Ballon, Showact, Walkact, Sonstiges (None = reiner Teamer)
    erfahrungspunkte = Column(Integer, default=0)  # LEGACY (seit 08/2026 ohne Funktion, Daten bleiben erhalten)
    qualitaet = Column(Integer)                   # LEGACY 1–5 ⭐ (ersetzt durch lieferantenbewertung, Migration ×2)
    lieferantenbewertung = Column(Integer)        # Interne Lieferantenbewertung 1–10 (None = noch nicht bewertet)
    mobilitaet = Column(String, default="Auto")  # Auto, ÖPNV, Beides
    kleidergroesse = Column(String)
    aktiv = Column(Boolean, default=True)
    logistiker = Column(Boolean, default=False)  # Kann Material transportieren
    fuehrerschein = Column(Boolean, default=False)
    teamshirt_kindsalabim = Column(Boolean, default=False)  # hat ein Kindsalabim-Team-Shirt
    teamshirt_knallfrosch = Column(Boolean, default=False)  # hat ein Knallfrosch-Team-Shirt
    password_hash = Column(String)               # für Portal-Login (Legacy)
    magic_token = Column(String)                 # Magic-Link-Token
    magic_token_expires = Column(String)         # ISO-Datetime
    onboarding_abgeschlossen = Column(Boolean, default=False)

    # Erweiterte Felder (aus Jira-Import)
    gebiet           = Column(String)            # Ruhrgebiet, Rheinland, …
    verfuegbarkeit   = Column(String)            # Flexibel, Nur Wochenende, …
    vertragstyp      = Column(String)            # Freelancer, Selbstständig
    stundensatz_teamer   = Column(Float)
    stundensatz_kuenstler = Column(Float)
    dsgvo_unterzeichnet  = Column(Boolean, default=False)
    website          = Column(String)
    notizen          = Column(Text)

    # Portal-Selbstauskunft (Onboarding/Profil)
    dsgvo_name           = Column(String)   # eingetippter Name bei der Online-Einwilligung
    dsgvo_knallfrosch_am = Column(String)   # ISO-Datetime der Einwilligung (Malca & Akmanoglu GbR)
    dsgvo_kindsalabim_am = Column(String)   # ISO-Datetime der Einwilligung (Aykut Malca | Kindsalabim)
    dsgvo_ip             = Column(String)   # IP bei der Online-Einwilligung (Nachweis)
    lager_transport_bereit = Column(Boolean, default=False)  # würde Material vom Lager (Essen-Rüttenscheid) mitnehmen
    kastenwagen_ok         = Column(Boolean, default=False)  # traut sich zu, einen Kastenwagen zu fahren

    # Scheinselbstständigkeits-Vorsorge (Selbstauskunft + AGB + Anwalts-Scoring)
    agb_akzeptiert_am    = Column(String)   # ISO-Datetime der Online-AGB-Bestätigung (beide Firmen)
    agb_ip               = Column(String)   # IP bei der AGB-Bestätigung (Nachweis)
    weitere_auftraggeber = Column(Boolean, default=False)  # Selbstauskunft: arbeitet auch für andere Auftraggeber
    betriebshaftpflicht  = Column(Boolean, default=False)  # Selbstauskunft: eigene Betriebshaftpflicht vorhanden
    scoring_json         = Column(Text)     # Anwalts-Scoring V7: {"kriterium_key": 0-3, ...}
    scoring_datum        = Column(String)   # ISO-Datum der letzten Scoring-Bewertung
    scoring_erinnert_am  = Column(Date)     # letzte Jahres-Erinnerung zur Scoring-Aktualisierung
    gewerbeschein_r2_key         = Column(String)   # hochgeladener Gewerbeschein (R2)
    gewerbeschein_filename       = Column(String)
    gewerbeschein_hochgeladen_am = Column(String)   # ISO-Datetime
    gewerbeschein_vorliegt       = Column(Boolean, default=False)  # Admin: liegt (auf Papier) vor
    gewerbeschein_erinnert_am    = Column(Date)     # letzte 7-Tage-Erinnerung (Start = Einladung)

    anfragen = relationship("Verfuegbarkeitsanfrage", back_populates="dienstleister")
    sperrzeiten = relationship("DienstleisterSperrzeit", back_populates="dienstleister", cascade="all, delete-orphan")

    @property
    def gewerbeschein_ok(self):
        return bool(self.gewerbeschein_vorliegt or self.gewerbeschein_r2_key)

    @property
    def dsgvo_ok(self):
        return bool(self.dsgvo_unterzeichnet
                    or (self.dsgvo_knallfrosch_am and self.dsgvo_kindsalabim_am))

    @property
    def unterlagen_ok(self):
        """Alles da, um Jobs anzunehmen? (Zusage-Sperre im Portal)"""
        return self.gewerbeschein_ok and self.dsgvo_ok


class Reservierung(Base):
    """Unverbindlicher Termin-Hold vor der Buchung (eigener Bereich, getrennt von Events).
    Wird per Klick zur Buchung (Event) umgewandelt oder freigegeben."""
    __tablename__ = "reservierungen"

    id                = Column(Integer, primary_key=True, index=True)
    datum             = Column(Date, nullable=False)     # angefragter Termin
    startzeit         = Column(String)                   # HH:MM (für zeitgebundenen Kalendereintrag)
    endzeit           = Column(String)                   # HH:MM (optional; sonst Start + 1 h)
    art               = Column(String, default="Div.")   # Z | B | ZB | Div. (Kalender-Präfix)
    anlass            = Column(String)
    veranstaltungsort = Column(String)
    kunde_firma       = Column(String, nullable=False)
    kunde_kontakt     = Column(String)
    kunde_telefon     = Column(String)
    kunde_email       = Column(String)
    marke             = Column(String, default="Kindsalabim")
    frist             = Column(Date)                      # bis wann der Kunde sich melden muss
    notiz             = Column(Text)
    kalender_event_id = Column(String)                    # anthrazitfarbener Block im Google-Kalender
    kalender_abgelaufen_markiert = Column(Boolean, default=False)  # Kalender-Block nach Fristablauf auf Flamingo umgefärbt (Cron-Idempotenz)
    serien_id         = Column(String)                    # verknüpft mehrtägige Reservierungen (wie Event.serien_id)
    erstellt_am       = Column(String)


class DienstleisterSperrzeit(Base):
    __tablename__ = "dienstleister_sperrzeiten"

    id               = Column(Integer, primary_key=True, index=True)
    dienstleister_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=False)
    von_datum        = Column(Date, nullable=False)
    bis_datum        = Column(Date, nullable=False)
    grund            = Column(String)   # z. B. "Urlaub", "Prüfungsphase", "Privat"

    dienstleister = relationship("Dienstleister", back_populates="sperrzeiten")


class Verfuegbarkeitsanfrage(Base):
    __tablename__ = "verfuegbarkeitsanfragen"
    # Pro Event höchstens eine Anfrage je Dienstleister (verhindert Doppel-Anfragen
    # durch Doppelklick/Race). (Review M4)
    __table_args__ = (UniqueConstraint("event_id", "dienstleister_id",
                                       name="ux_anfrage_event_dl"),)

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    dienstleister_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=False)
    rolle_anfrage = Column(String, default="Teamer")   # Teamer oder Künstler
    status = Column(String, default="Ausstehend")      # Ausstehend, Ja, Nein
    notiz = Column(Text)
    erstellt_am = Column(String)
    frist_datum = Column(Date)          # echtes Datum – wann die Anfrage abläuft
    frist_verlaengert = Column(Boolean, default=False)
    erinnerung_gesendet = Column(Boolean, default=False)
    einsatz_erinnerung_gesendet = Column(Boolean, default=False)  # Einsatz-Erinnerung 2 Tage vorher
    als_logistiker = Column(Boolean, default=False)  # auch als Logistiker (Materialtransport) angefragt
    logistik_transport = Column(String)  # Antwort des Logistikers: eigenes_auto | transporter | ohne (None = offen)
    budget = Column(Float)  # Künstler-Budget (pauschal, netto, inkl. Fahrtkosten) – None = keine Angabe
    bestellung_am = Column(String)      # ISO-Datetime der Auto-Bestellung bei Zusage (None = keine)
    bestellung_r2_key = Column(String)  # archivierte Bestellungs-PDF im R2 (Nachweis)
    # Warteliste: verspätete Zusage, während die Stelle noch fristgerecht bei jemand
    # anderem läuft. Wird ein Platz frei (Absage/Fristablauf), rückt der Älteste
    # automatisch nach und bekommt die Anfrage erneut.
    warteliste_seit = Column(String)    # ISO-Datetime (None = nicht auf der Warteliste)

    event = relationship("Event", back_populates="anfragen")
    dienstleister = relationship("Dienstleister", back_populates="anfragen")


class EventBestellung(Base):
    """Material-Bestellung zu einem Event (Bezeichnung + Betrag). Die Summe wird beim
    Eintragen der Rechnung in der Buchhaltung als Materialkosten-Vorschlag angeboten –
    erspart das Zusammensuchen der Bestell-Mails."""
    __tablename__ = "event_bestellungen"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    bezeichnung = Column(String, nullable=False)
    betrag      = Column(Float, default=0.0)
    erstellt_am = Column(String)


class EventDatei(Base):
    __tablename__ = "event_dateien"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    r2_key      = Column(String, nullable=False)   # Pfad im R2-Bucket
    filename    = Column(String, nullable=False)   # Originaldateiname
    typ         = Column(String, nullable=False)   # "planung" oder "bericht_foto"
    uploaded_at = Column(String, nullable=False)   # ISO-Datetime

    event = relationship("Event", back_populates="dateien")


class TicketKategorie(Base):
    __tablename__ = "ticket_kategorien"
    id    = Column(Integer, primary_key=True, index=True)
    name  = Column(String, nullable=False)
    farbe = Column(String, default="#1D4E89")


class Sprint(Base):
    __tablename__ = "sprints"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    start_datum = Column(Date)
    end_datum   = Column(Date)
    status      = Column(String, default="geplant")   # geplant | aktiv | abgeschlossen
    erstellt_am = Column(String)


class Ticket(Base):
    __tablename__ = "tickets"
    id              = Column(Integer, primary_key=True, index=True)
    titel           = Column(String, nullable=False)
    beschreibung    = Column(Text, default="")
    kategorie_id    = Column(Integer, ForeignKey("ticket_kategorien.id"), nullable=True)
    wichtigkeit     = Column(String, default="mittel")  # niedrig | mittel | hoch | kritisch
    aufwand         = Column(String)                     # S | M | L | XL
    status          = Column(String, default="todo")     # todo | doing | done
    sprint_id       = Column(Integer, ForeignKey("sprints.id"), nullable=True)  # None = Backlog
    admin_id        = Column(Integer, ForeignKey("admins.id"), nullable=True)
    faellig         = Column(Date, nullable=True)
    reihenfolge     = Column(Integer, default=0)
    extern_key      = Column(String)   # z.B. Jira-Vorgangsschlüssel – verhindert Doppel-Import
    erstellt_am     = Column(String)
    aktualisiert_am = Column(String)

    kategorie = relationship("TicketKategorie")
    sprint    = relationship("Sprint")
    admin     = relationship("Admin")
    subtasks  = relationship("TicketSubtask", back_populates="ticket",
                             cascade="all, delete-orphan", order_by="TicketSubtask.reihenfolge")
    kommentare = relationship("TicketKommentar", back_populates="ticket",
                             cascade="all, delete-orphan", order_by="TicketKommentar.erstellt_am")


class TicketSubtask(Base):
    __tablename__ = "ticket_subtasks"
    id          = Column(Integer, primary_key=True, index=True)
    ticket_id   = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    text        = Column(String, nullable=False)
    erledigt    = Column(Boolean, default=False)
    reihenfolge = Column(Integer, default=0)
    ticket = relationship("Ticket", back_populates="subtasks")


class TicketKommentar(Base):
    __tablename__ = "ticket_kommentare"
    id          = Column(Integer, primary_key=True, index=True)
    ticket_id   = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    text        = Column(Text, nullable=False)
    autor       = Column(String)
    erstellt_am = Column(String)
    ticket = relationship("Ticket", back_populates="kommentare")


class Admin(Base):
    __tablename__ = "admins"

    id                  = Column(Integer, primary_key=True, index=True)
    email               = Column(String, unique=True, nullable=False)
    name                = Column(String)
    password_hash       = Column(String, nullable=False)
    reset_token         = Column(String)
    reset_token_expires = Column(String)   # ISO-Datetime
    aktiv               = Column(Boolean, default=True)
    erstellt_am         = Column(String)
    notifications_gesehen_bis = Column(String)  # ISO-Datetime: bis hierhin Benachrichtigungen gesehen (None = nie)
    # Persönliche Marken-Ansicht: "beide" | "Kindsalabim" | "Knallfrosch".
    # Wirkt auf Dashboard, Reservierungen, Buchhaltung, Glocke UND den Mailversand –
    # jeder Admin stellt sie für sich selbst ein (keine Rechtevergabe, nur Ansicht).
    marken_filter       = Column(String, default="beide")


class Benachrichtigung(Base):
    """Aktivitäts-Feed für Admins (Glocke). Ereignisse wie DL-Zusage/-Absage,
    Urlaub/Sperrzeit, Checkliste zurück, Eventbericht eingereicht."""
    __tablename__ = "benachrichtigungen"

    id          = Column(Integer, primary_key=True, index=True)
    typ         = Column(String, nullable=False)   # dl_zusage|dl_absage|dl_urlaub|checkliste|bericht
    titel       = Column(String, nullable=False)
    text        = Column(Text)
    link        = Column(String)                    # interner Pfad zum Deep-Link, z. B. /admin/events/12
    erstellt_am = Column(String, nullable=False, index=True)  # ISO-Datetime (sortierbar)
    marke       = Column(String)   # Kindsalabim | Knallfrosch | None = markenneutral (immer sichtbar)


class AppEinstellung(Base):
    """Schlüssel/Wert-Einstellungen der App (z. B. E-Mail-Benachrichtigungs-Schalter)."""
    __tablename__ = "app_einstellungen"

    key   = Column(String, primary_key=True)
    value = Column(String)


class Wissensartikel(Base):
    __tablename__ = "wissensartikel"

    id              = Column(Integer, primary_key=True, index=True)
    titel           = Column(String, nullable=False)
    inhalt          = Column(Text, default="")        # Markdown
    kategorie       = Column(String, default="Allgemein")
    sichtbarkeit    = Column(String, default="beide")  # admin | dienstleister | beide
    veroeffentlicht = Column(Boolean, default=True)
    sortierung      = Column(Integer, default=0)
    parent_id       = Column(Integer, ForeignKey("wissensartikel.id"), nullable=True)
    cover_bild      = Column(String)                   # Pfad zum Karten-Bild (static/img/wissen/...)
    erstellt_am     = Column(String)                   # ISO-Datetime
    aktualisiert_am = Column(String)                   # ISO-Datetime

    kinder = relationship("Wissensartikel",
                          backref=backref("parent", remote_side=[id]),
                          cascade="all, delete-orphan")


class Rechnung(Base):
    __tablename__ = "rechnungen"

    id             = Column(Integer, primary_key=True, index=True)
    datum          = Column(Date, nullable=False)
    kunde          = Column(String)
    marke          = Column(String, default="Kindsalabim")  # steuert die Sichtbarkeit je Admin
    rgnr           = Column(String)       # Rechnungsnummer, z. B. RE-2026-001
    brutto         = Column(Float, default=0.0)
    bezahlt          = Column(Boolean, default=False)
    # Letzte Überfällig-Meldung (ISO-Datum) – wiederholt sich alle 7 Tage, bis bezahlt.
    ueberfaellig_erinnert_am = Column(String)
    steuer_erledigt  = Column(Boolean, default=False)
    personalkosten   = Column(Float, default=0.0)
    materialkosten   = Column(Float, default=0.0)
    notiz            = Column(Text)


# ── CRM ──────────────────────────────────────────────────────────────────────

# Pipeline-Stufen (verschlankt): lead → kontakt → bedarf → angebot → gebucht → verloren
KUNDE_STATUS = ["lead", "kontakt", "bedarf", "angebot", "gebucht", "verloren"]

kunde_tag_zuordnung = Table(
    "kunde_tag_zuordnung", Base.metadata,
    Column("kunde_id", Integer, ForeignKey("kunden.id"), primary_key=True),
    Column("tag_id",   Integer, ForeignKey("kunde_tags.id"), primary_key=True),
)


class KundeTag(Base):
    __tablename__ = "kunde_tags"
    id    = Column(Integer, primary_key=True, index=True)
    name  = Column(String, unique=True, nullable=False)
    farbe = Column(String, default="#1D4E89")


class Kunde(Base):
    __tablename__ = "kunden"

    id            = Column(Integer, primary_key=True, index=True)
    firma         = Column(String, nullable=False)   # einziges Pflichtfeld
    ansprechpartner = Column(String)
    telefon       = Column(String)
    email         = Column(String)
    rechnung_email = Column(String)  # separate Rechnungs-Mailadresse (Erinnerung nach dem Event nutzt sie)
    strasse       = Column(String)
    plz           = Column(String)
    ort           = Column(String)
    website       = Column(String)
    branche       = Column(String)
    weitere_ansprechpartner = Column(Text)  # JSON [{"name","telefon","email"}] – zusätzliche Kontakte (z. B. Planung)
    marke         = Column(String, default="Kindsalabim")

    # Vertrieb / Pipeline (Kanban folgt in Stufe 3)
    pipeline_status      = Column(String, default="lead")
    pipeline_reihenfolge = Column(Integer, default=0)

    # Profil-Wissen (alles optional – „Kundengedächtnis")
    notizen               = Column(Text)   # allgemeine interne Notizen
    kommunikationsstil    = Column(Text)
    besonderheiten        = Column(Text)
    bevorzugte_eventarten = Column(String)
    typische_budgets      = Column(String)

    erstellt_am     = Column(String)
    aktualisiert_am = Column(String)

    events = relationship("Event", back_populates="kunde", foreign_keys="Event.kunde_id")
    tags   = relationship("KundeTag", secondary=kunde_tag_zuordnung, backref="kunden")
    aktivitaeten = relationship("KundeAktivitaet", back_populates="kunde",
                                cascade="all, delete-orphan",
                                order_by="KundeAktivitaet.datum.desc(), KundeAktivitaet.id.desc()")
    wiedervorlagen = relationship("KundeWiedervorlage", back_populates="kunde",
                                  cascade="all, delete-orphan",
                                  order_by="KundeWiedervorlage.faellig")


# ── Baker-Ross-Recherche (Bastelset-Katalog + KI-Kuratierung) ────────────────

class BastelProdukt(Base):
    """Lokaler Spiegel eines Baker-Ross-Bastelsets (aus der offiziellen Sitemap).
    Preis wird erst bei Bedarf (für kuratierte Treffer) von der Produktseite nachgeladen.
    Robots-konform: Quelle ist die freigegebene Sitemap, kein KI-Live-Scraping."""
    __tablename__ = "bastel_produkte"

    id              = Column(Integer, primary_key=True, index=True)
    url             = Column(String, unique=True, nullable=False)  # Produktseite
    name            = Column(String, nullable=False)
    beschreibung    = Column(Text)                 # aus image:caption der Sitemap
    bild_url        = Column(String)               # Haupt-Produktbild
    preis           = Column(Float)                # BR-Preis € (pro Packung), None = noch nicht geholt
    stueckzahl      = Column(Integer)              # Inhalt pro Packung (pack_size), None = unbekannt
    preis_stand     = Column(String)               # ISO-Datum des letzten Preis-Abrufs
    kategorie       = Column(String)
    lastmod         = Column(String)               # aus Sitemap
    aktiv           = Column(Boolean, default=True)
    erstellt_am     = Column(String)
    aktualisiert_am = Column(String)


class Bastelvorschlag(Base):
    """An ein Event angedockter, kuratierter Bastelset-Vorschlag (Snapshot)."""
    __tablename__ = "bastel_vorschlaege"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    name        = Column(String, nullable=False)
    url         = Column(String)
    bild_url    = Column(String)
    br_preis    = Column(Float)        # BR-Preis pro Packung
    stueckzahl  = Column(Integer)      # Inhalt pro Packung
    kundenpreis = Column(Float)        # Kundenpreis pro Stück = (br_preis/stueckzahl) × Faktor
    begruendung = Column(Text)
    erstellt_am = Column(String)


class GeloeschtesObjekt(Base):
    """Papierkorb / Notfall-Sicherung: JSON-Snapshot eines gelöschten Datensatzes.
    Wird beim Löschen von Event/Dienstleister/Kunde angelegt, BEVOR hart gelöscht wird –
    so geht bei einem Fehlklick nichts unwiederbringlich verloren."""
    __tablename__ = "geloeschte_objekte"

    id            = Column(Integer, primary_key=True, index=True)
    typ           = Column(String, nullable=False)   # event | dienstleister | kunde
    objekt_id     = Column(Integer)                  # ursprüngliche ID
    bezeichnung   = Column(String)                   # lesbares Label für die Liste
    daten_json    = Column(Text, nullable=False)     # vollständiger Snapshot inkl. Verknüpfungen
    geloescht_am  = Column(String)                   # ISO-Datetime
    geloescht_von = Column(String)                   # Admin-E-Mail


class KundeAktivitaet(Base):
    __tablename__ = "kunde_aktivitaeten"
    id          = Column(Integer, primary_key=True, index=True)
    kunde_id    = Column(Integer, ForeignKey("kunden.id"), nullable=False)
    typ         = Column(String, default="notiz")   # notiz | anruf | email | meeting | angebot
    datum       = Column(Date)
    notiz       = Column(Text)
    erstellt_am = Column(String)
    kunde = relationship("Kunde", back_populates="aktivitaeten")


class KundeWiedervorlage(Base):
    __tablename__ = "kunde_wiedervorlagen"
    id          = Column(Integer, primary_key=True, index=True)
    kunde_id    = Column(Integer, ForeignKey("kunden.id"), nullable=False)
    titel       = Column(String, nullable=False)
    faellig     = Column(Date)
    prioritaet  = Column(String, default="mittel")  # niedrig | mittel | hoch
    erledigt    = Column(Boolean, default=False)
    erstellt_am = Column(String)
    erledigt_am = Column(String)
    kunde = relationship("Kunde", back_populates="wiedervorlagen")
