from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, MetaData, String, Table, Time, create_engine,
)

from config import require_env

# Alle Verbindungsdaten stecken in DATABASE_URL (siehe .env.example).
engine = create_engine(require_env("DATABASE_URL"), pool_pre_ping=True)
metadata = MetaData()

# Ein Eintrag pro Schultag: wann zuletzt geändert und woher der Plan kam.
days = Table(
    "days", metadata,
    Column("day", Date, primary_key=True),
    Column("content_hash", String(64), nullable=False),  # Hash des Tagesinhalts
    Column("plan_timestamp", DateTime, nullable=True),   # Planstand von vpmobil
    Column("source", String(20), nullable=False),        # "vertretung" | "normal"
    Column("is_free", Boolean, nullable=False, default=False),
    Column("updated_at", DateTime, nullable=False),
)

# Eine Zeile pro Unterrichtsstunde und Raum.
lessons = Table(
    "lessons", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("day", Date, nullable=False, index=True),
    Column("period", Integer, nullable=False),
    Column("start_time", Time),                          # Beginn der Stunde
    Column("end_time", Time),                            # Ende der Stunde
    Column("room", String(40), nullable=False, index=True),
    Column("class_name", String(40)),
    Column("subject", String(60)),
    Column("teacher", String(60)),
    Column("info", String(255)),
    Column("cancelled", Boolean, nullable=False, default=False),
    # Änderungs-Markierungen von vpmobil (für die rote Anzeige)
    Column("subject_changed", Boolean, nullable=False, default=False),
    Column("teacher_changed", Boolean, nullable=False, default=False),
    Column("room_changed", Boolean, nullable=False, default=False),
    Column("class_changed", Boolean, nullable=False, default=False),
)

# Protokoll der Scraper-Läufe (für die Verwaltungsseite).
scrapes = Table(
    "scrapes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", DateTime, nullable=False),
    Column("status", String(20), nullable=False),        # ok | partial | error
    Column("days_changed", Integer, nullable=False, default=0),
    Column("message", String(500)),
)


def init_db() -> None:
    """Legt fehlende Tabellen an (vorhandene Tabellen bleiben unverändert)."""
    metadata.create_all(engine)