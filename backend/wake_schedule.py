# SPDX-License-Identifier: GPL-3.0-or-later
"""Wake-up schedule: when should a display wake up next, and may it install updates now?"""

import hashlib
import os
import sys
from datetime import datetime, time, timedelta

from sqlalchemy import select

import config  # noqa: F401  (loads the .env)
from db import wake_schedules

# A scheduled time closer than this to the current check-in is skipped. This avoids a second
# wake-up shortly after a device woke up a bit early because of clock drift (the ESP32 clock
# drifts by a few percent). Must be smaller than the shortest interval in the schedule.
MIN_GAP_SECONDS = int(os.getenv("MIN_WAKE_GAP_SECONDS", "900"))

# Every device gets a fixed random offset (0..N seconds) so that all displays do not
# connect in the same second.
JITTER_SECONDS = int(os.getenv("WAKE_JITTER_SECONDS", "120"))


def _parse_window(text: str) -> tuple[time, time] | None:
    """Parse "21:00-05:00". Empty text means: no restriction."""
    text = text.strip()
    if not text:
        return None
    try:
        start_text, end_text = text.split("-")
        return time.fromisoformat(start_text.strip()), time.fromisoformat(end_text.strip())
    except ValueError:
        sys.exit(f'Invalid OTA_WINDOW "{text}". Expected format: HH:MM-HH:MM (or empty).')


OTA_WINDOW = _parse_window(os.getenv("OTA_WINDOW", "21:00-05:00"))


def load_entries(conn, name: str = "default") -> list[tuple[int, time]]:
    """Return the (weekday, time) entries of a schedule."""
    rows = conn.execute(
        select(wake_schedules.c.weekday, wake_schedules.c.wake_time)
        .where(wake_schedules.c.name == name)
    ).all()
    return [(row.weekday, row.wake_time) for row in rows]


def jitter_for(device_id: str) -> int:
    """Fixed offset in seconds for a device."""
    if JITTER_SECONDS <= 0:
        return 0
    digest = hashlib.sha256(device_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") % (JITTER_SECONDS + 1)


def next_wake(now: datetime, entries: list[tuple[int, time]], device_id: str) -> datetime | None:
    """First scheduled time that is at least MIN_GAP_SECONDS away (plus the device jitter)."""
    if not entries:
        return None
    jitter = timedelta(seconds=jitter_for(device_id))
    candidates = []
    for offset in range(8):  # today and the next 7 days cover every weekday at least once
        day = now.date() + timedelta(days=offset)
        for weekday, wake_time in entries:
            if weekday == day.weekday():
                candidates.append(datetime.combine(day, wake_time) + jitter)
    for candidate in sorted(candidates):
        if (candidate - now).total_seconds() >= MIN_GAP_SECONDS:
            return candidate
    return None


def sleep_seconds(now: datetime, entries: list[tuple[int, time]], device_id: str,
                  busy_seconds: int, fallback: int) -> int:
    """Seconds the device should sleep. busy_seconds is the time it stays awake after the
    answer (download and refresh), so that it wakes up close to the scheduled time.
    Without schedule entries the fallback is used."""
    target = next_wake(now, entries, device_id)
    if target is None:
        return fallback
    return max(1, int((target - now).total_seconds()) - busy_seconds)


def in_ota_window(now: datetime) -> bool:
    """Firmware updates are only offered inside the OTA window (default: at night)."""
    if OTA_WINDOW is None:
        return True
    start, end = OTA_WINDOW
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end  # window crosses midnight