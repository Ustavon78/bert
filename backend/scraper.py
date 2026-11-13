# SPDX-License-Identifier: GPL-3.0-or-later
"""Holt Pläne von vpmobil24 (Stundenplan24) und schreibt sie in die Datenbank.

Läuft als Einmal-Skript (z. B. per systemd-Timer oder cron alle paar Minuten):
    python scraper.py
Alle Einstellungen stehen in der Datei .env (siehe .env.example).
Die Tabellen werden einmalig mit  python init_db.py  angelegt.
"""

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import delete, insert, select

from config import json_env_list, require_env
from db import days, engine, lessons, scrapes
from lesson_status import is_cancelled  # eigenes Modul aus deinem Projekt
from vpmobil import ResourceNotFound, Unauthorized, VertretungsplanZugang
from vpmobil.weekly import fetch_weekly_plans


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


# --------------------------------------------------------------------------
# Einstellungen aus .env
# --------------------------------------------------------------------------
SCHULNUMMER = require_env("SCHULNUMMER")
BENUTZERNAME = require_env("BENUTZERNAME")
PASSWORT = require_env("PASSWORT")
ALL_ROOMS = json_env_list("ALL_ROOMS")
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "10"))  # Anzahl Schultage im Voraus
KEEP_DAYS = 7                                    # so lange bleiben alte Tage in der DB


# --------------------------------------------------------------------------
# Plan -> Zeilen
# --------------------------------------------------------------------------
def _text(value, limit: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    return str(value)[:limit]


def split_rooms(room_values) -> list[str]:
    """Zerlegt Raumangaben wie '101-103' oder '204, 205' in einzelne Räume."""
    rooms: list[str] = []
    for room in room_values:
        text = re.sub(r"(\d)\s*([–—-])\s*(?=\d)", r"\1\2", str(room))
        for value in re.split(r"[,;/+&\s]+", text):
            if not value:
                continue
            interval = re.fullmatch(r"(\d+)[–—-](\d+)", value)
            if interval:
                first, last = sorted(map(int, interval.groups()))
                rooms.extend(str(r) for r in ALL_ROOMS if first <= r <= last)
            else:
                digits = "".join(ch for ch in value if ch.isdigit())
                rooms.append(digits or value)
    return list(dict.fromkeys(rooms))  # doppelte entfernen, Reihenfolge behalten


def iter_lessons(plan):
    """Liefert (Klasse, Stunde, Unterricht) für beide Plan-Formen."""
    if hasattr(plan, "stunden"):  # flache Liste (z. B. Lehrerplan)
        for lesson in plan.stunden:
            yield None, int(lesson.periode), lesson
        return
    for class_name, class_item in plan.klassen.items():
        for period, lesson_list in class_item.stunden.items():
            for lesson in lesson_list:
                yield class_name, int(period), lesson


def build_rows(plan) -> list[dict]:
    rows = []
    for class_name, period, lesson in iter_lessons(plan):
        cancelled = bool(is_cancelled(lesson))
        if class_name is None:  # flache Pläne: Klasse(n) aus der Stunde selbst
            class_name = getattr(lesson, "klassen", None)
        for room in split_rooms(lesson.räume):
            rows.append({
                "period": period,
                "start_time": getattr(lesson, "beginn", None),
                "end_time": getattr(lesson, "ende", None),
                "room": room,
                "class_name": _text(class_name, 40),
                "subject": _text(getattr(lesson, "fach", None), 60),
                "teacher": _text(getattr(lesson, "lehrer", None), 60),
                "info": _text(getattr(lesson, "info", None), 255),
                "cancelled": cancelled,
                "subject_changed": bool(getattr(lesson, "fachänderung", False)),
                "teacher_changed": bool(getattr(lesson, "lehreränderung", False)),
                "room_changed": bool(getattr(lesson, "raumänderung", False)),
                "class_changed": bool(getattr(lesson, "klassenänderung", False)),
            })
    rows.sort(key=lambda r: (
        r["period"], r["room"], r["class_name"] or "", r["subject"] or "", r["teacher"] or "",
    ))
    return rows


# --------------------------------------------------------------------------
# Pläne holen
# --------------------------------------------------------------------------
def school_days(count: int) -> list[date]:
    """Die nächsten `count` Werktage ab heute."""
    result, day = [], date.today()
    while len(result) < count:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def get_plan(access, day: date, weekly_cache: dict):
    """Vertretungsplan; gibt es keinen, der normale Wochenplan. -> (plan, quelle)"""
    try:
        return access.fetch(day), "vertretung"
    except ResourceNotFound:
        pass
    monday = day - timedelta(days=day.weekday())
    if monday not in weekly_cache:
        try:
            weekly_cache[monday] = fetch_weekly_plans(access, monday)
        except ResourceNotFound:
            weekly_cache[monday] = {}
    plan = weekly_cache[monday].get(day)
    return (plan, "normal") if plan is not None else (None, None)


# --------------------------------------------------------------------------
# In die DB schreiben
# --------------------------------------------------------------------------
def save_day(conn, day: date, plan, source: str) -> bool:
    """Schreibt einen Tag. Gibt True zurück, wenn sich etwas geändert hat."""
    rows = build_rows(plan)
    is_free = day in getattr(plan, "freieTage", ()) or bool(getattr(plan, "unterrichtsfrei", False))

    # Schutz: Ein leerer Plan an einem normalen Schultag überschreibt keine alten Daten.
    if not rows and not is_free:
        log(f"{day}: Plan ist leer, alte Daten bleiben erhalten.")
        return False

    new_hash = hashlib.sha256(
        json.dumps([rows, is_free], sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    old_hash = conn.execute(select(days.c.content_hash).where(days.c.day == day)).scalar()
    if old_hash == new_hash:
        return False

    conn.execute(delete(lessons).where(lessons.c.day == day))
    conn.execute(delete(days).where(days.c.day == day))
    if rows:
        conn.execute(insert(lessons), [{**row, "day": day} for row in rows])
    conn.execute(insert(days).values(
        day=day, content_hash=new_hash, plan_timestamp=getattr(plan, "zeitstempel", None),
        source=source, is_free=is_free, updated_at=datetime.now(),
    ))
    return True


def cleanup_old(conn) -> None:
    limit = date.today() - timedelta(days=KEEP_DAYS)
    conn.execute(delete(lessons).where(lessons.c.day < limit))
    conn.execute(delete(days).where(days.c.day < limit))


def main() -> int:
    started = datetime.now()
    access = VertretungsplanZugang(SCHULNUMMER, BENUTZERNAME, PASSWORT)
    weekly_cache: dict = {}
    changed, errors, messages = 0, 0, []
    denied = False

    for day in school_days(DAYS_AHEAD):
        try:
            plan, source = get_plan(access, day, weekly_cache)
            if plan is None:
                log(f"{day}: kein Plan verfügbar.")
                continue
            with engine.begin() as conn:  # eine Transaktion pro Tag
                if save_day(conn, day, plan, source):
                    changed += 1
                    log(f"{day}: aktualisiert ({source}).")
        except Unauthorized:
            log("Zugriff verweigert, bitte Zugangsdaten in .env prüfen.")
            messages.append("Zugriff verweigert")
            denied = True
            break
        except Exception as error:  # Netzwerkfehler usw.: alte Daten bleiben
            errors += 1
            messages.append(f"{day}: {error}")
            log(f"{day}: Fehler: {error}")

    status = "error" if denied else ("partial" if errors else "ok")
    with engine.begin() as conn:
        cleanup_old(conn)
        conn.execute(insert(scrapes).values(
            started_at=started, status=status, days_changed=changed,
            message="; ".join(messages)[:500] or None,
        ))
    log(f"Fertig: Status {status}, {changed} Tag(e) geändert.")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())