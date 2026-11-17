# SPDX-License-Identifier: GPL-3.0-or-later
"""Datenbankverbindung und Tabellen. Wird von Scraper, Renderer und API gemeinsam genutzt."""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, MetaData, String, Table, Time, create_engine,
)

from config import require_env

# Alle Verbindungsdaten stecken in DATABASE_URL (siehe .env.example).
engine = create_engine(require_env("DATABASE_URL"), pool_pre_ping=True)
metadata = MetaData()

# Ein Eintrag pro Schultag: woher der Plan kam, ob frei ist und wann er geholt wurde.
days = Table(
    "days", metadata,
    Column("day", Date, primary_key=True),
    Column("plan_timestamp", DateTime, nullable=True),   # Planstand von vpmobil
    Column("source", String(20), nullable=False),        # "vertretung" | "normal"
    Column("is_free", Boolean, nullable=False, default=False),
    Column("scraped_at", DateTime, nullable=False),      # letzter Abruf durch den Scraper  # wann der Scraper den Tag zuletzt geholt hat
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
    Column("days_saved", Integer, nullable=False, default=0),
    Column("message", String(500)),
)


# Ein Eintrag pro Display.
devices = Table(
    "devices", metadata,
    Column("id", String(12), primary_key=True),          # Geräte-ID (nicht geheim)
    Column("name", String(80)),                          # z. B. "Raum 118, Tür"
    Column("room", String(40), index=True),              # Raum, den das Display zeigt
    Column("token_hash", String(64), nullable=False),    # SHA-256 des Geräte-Tokens
    Column("mode", String(20), nullable=False, default="active"),  # active | deactivated
    Column("desired_hash", String(64)),                  # Soll-Hash des Bildes (vom Renderer)
    Column("reported_hash", String(64)),                 # Hash, den das Display zuletzt meldete
    Column("desired_fw", String(20)),                    # Soll-Firmwareversion
    Column("reported_fw", String(20)),                   # gemeldete Firmwareversion
    Column("ota_after", DateTime),                       # Update erst ab diesem Zeitpunkt
    Column("ota_force", Boolean, nullable=False, default=False),   # Update sofort
    Column("sleep_seconds", Integer, nullable=False, default=14400),  # Schlafzeit bis zum nächsten Aufwachen
    Column("last_seen", DateTime),
    Column("batt_mv", Integer),
    Column("rssi", Integer),
    Column("created_at", DateTime, nullable=False),
)


# Ein Eintrag pro Display.
# Lehrer: Kürzel (wie in vpmobil) -> Name, der auf dem Display erscheint.
teachers = Table(
    "teachers", metadata,
    Column("abbreviation", String(20), primary_key=True),
    Column("name", String(80), nullable=False),
)


# Wake-up times of the displays: one row per weekday and time.
# All devices use the schedule "default" (per-device schedules can be added later).
wake_schedules = Table(
    "wake_schedules", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(40), nullable=False, default="default", index=True),
    Column("weekday", Integer, nullable=False),  # 0 = Monday ... 6 = Sunday
    Column("wake_time", Time, nullable=False),
)


# Device modes (devices.mode)
MODE_ACTIVE = "active"            # normal operation
MODE_DEACTIVATED = "deactivated"  # switched off by an admin: no images, no updates, rare check-ins
DEVICE_MODES = (MODE_ACTIVE, MODE_DEACTIVATED)


def normalize_mode(mode) -> str:
    """Lower case without surrounding spaces, so that "Active " is still "active"."""
    return (mode or "").strip().lower()


def device_is_active(mode) -> bool:
    """Only "active" counts as active. Everything else, including typos, is treated as
    deactivated (fail closed). Use this function everywhere instead of comparing strings."""
    return normalize_mode(mode) == MODE_ACTIVE