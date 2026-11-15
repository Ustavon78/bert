# SPDX-License-Identifier: GPL-3.0-or-later
"""Welche Tage werden geholt und welcher Tag wird auf den Displays angezeigt?

Wird vom Scraper und später vom Renderer gemeinsam genutzt.
"""

from datetime import date, datetime, time, timedelta

# Ab dieser Uhrzeit zeigen die Displays schon den nächsten Schultag
# (relevant für die nächtliche Synchronisation vor Mitternacht).
NEXT_DAY_FROM = time(18, 0)


def next_school_day(after: date) -> date:
    """Der nächste Werktag nach `after` (Mo-Fr; Feiertage kennt diese Funktion nicht)."""
    day = after + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def scrape_days(today: date | None = None) -> list[date]:
    """Tage, die der Scraper holt: heute (falls Werktag) und der nächste Schultag."""
    today = today or date.today()
    result = [today] if today.weekday() < 5 else []
    result.append(next_school_day(today))
    return result


def display_day(now: datetime | None = None) -> date:
    """Der Tag, den die Displays gerade anzeigen sollen."""
    now = now or datetime.now()
    today = now.date()
    if today.weekday() < 5 and now.time() < NEXT_DAY_FROM:
        return today
    return next_school_day(today)