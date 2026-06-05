from sqlalchemy import Column, Integer, String, Text, Date, Time, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    anlass = Column(String, nullable=False)
    datum = Column(String, nullable=False)       # DD.MM.YYYY
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
    verpflegung = Column(Boolean, default=False)
    teamkleidung = Column(Boolean, default=True)
    status = Column(String, default="Entwurf")   # Entwurf, Bestätigt, Briefing gesendet, Abgeschlossen
    marke = Column(String, default="Kindsalabim")  # Kindsalabim, Knallfrosch
    teamleiter_id = Column(Integer, ForeignKey("dienstleister.id"), nullable=True)

    teamleiter = relationship("Dienstleister", foreign_keys=[teamleiter_id])
    anfragen = relationship("Verfuegbarkeitsanfrage", back_populates="event", cascade="all, delete-orphan")


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
    password_hash = Column(String)               # für Portal-Login

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

    event = relationship("Event", back_populates="anfragen")
    dienstleister = relationship("Dienstleister", back_populates="anfragen")
