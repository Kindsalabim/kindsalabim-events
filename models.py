from sqlalchemy import Column, Integer, String, Text, Date, Time, ForeignKey, Boolean, Float
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
    kunde_kontakt = Column(String)
    kunde_telefon = Column(String)
    kunde_email = Column(String)
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
    status = Column(String, default="Entwurf")   # Entwurf, Bestätigt, Briefing gesendet, Abgeschlossen
    marke = Column(String, default="Kindsalabim")  # Kindsalabim, Knallfrosch
    teamleiter_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=True)
    rechnung_gestellt = Column(Boolean, default=False)  # Bedingung für "Abgeschlossen"

    # Eventbericht (vom Teamleiter nach dem Event im Portal ausgefüllt)
    bericht_eingereicht_am = Column(String)
    bericht_anzahl_kinder  = Column(Integer)
    bericht_verlauf        = Column(Text)
    bericht_probleme       = Column(Text)
    bericht_kundenfeedback = Column(Text)

    # Kunden-Checkliste
    checklist_token = Column(String, unique=True, nullable=True)
    cl_ansprechpartner_name  = Column(String)
    cl_ansprechpartner_mobil = Column(String)
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
    cl_eingereicht_am        = Column(String)

    teamleiter = relationship("Dienstleister", foreign_keys=[teamleiter_id])
    anfragen = relationship("Verfuegbarkeitsanfrage", back_populates="event", cascade="all, delete-orphan")
    dateien  = relationship("EventDatei", back_populates="event", cascade="all, delete-orphan")


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
    erfahrungspunkte = Column(Integer, default=0)
    mobilitaet = Column(String, default="Auto")  # Auto, ÖPNV, Beides
    kleidergroesse = Column(String)
    aktiv = Column(Boolean, default=True)
    logistiker = Column(Boolean, default=False)  # Kann Material transportieren
    fuehrerschein = Column(Boolean, default=False)
    password_hash = Column(String)               # für Portal-Login (Legacy)
    magic_token = Column(String)                 # Magic-Link-Token
    magic_token_expires = Column(String)         # ISO-Datetime

    # Erweiterte Felder (aus Jira-Import)
    gebiet           = Column(String)            # Ruhrgebiet, Rheinland, …
    verfuegbarkeit   = Column(String)            # Flexibel, Nur Wochenende, …
    vertragstyp      = Column(String)            # Freelancer, Selbstständig
    stundensatz_teamer   = Column(Float)
    stundensatz_kuenstler = Column(Float)
    dsgvo_unterzeichnet  = Column(Boolean, default=False)
    website          = Column(String)
    notizen          = Column(Text)

    anfragen = relationship("Verfuegbarkeitsanfrage", back_populates="dienstleister")


class Verfuegbarkeitsanfrage(Base):
    __tablename__ = "verfuegbarkeitsanfragen"

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

    event = relationship("Event", back_populates="anfragen")
    dienstleister = relationship("Dienstleister", back_populates="anfragen")


class EventDatei(Base):
    __tablename__ = "event_dateien"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    r2_key      = Column(String, nullable=False)   # Pfad im R2-Bucket
    filename    = Column(String, nullable=False)   # Originaldateiname
    typ         = Column(String, nullable=False)   # "planung" oder "bericht_foto"
    uploaded_at = Column(String, nullable=False)   # ISO-Datetime

    event = relationship("Event", back_populates="dateien")


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
    rgnr           = Column(String)       # Rechnungsnummer, z. B. RE-2026-001
    brutto         = Column(Float, default=0.0)
    bezahlt          = Column(Boolean, default=False)
    steuer_erledigt  = Column(Boolean, default=False)
    personalkosten   = Column(Float, default=0.0)
    materialkosten   = Column(Float, default=0.0)
    notiz            = Column(Text)
