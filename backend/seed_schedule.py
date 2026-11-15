# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the default wake-up schedule.

    python seed_schedule.py            create it if it does not exist yet
    python seed_schedule.py --reset    delete the default schedule and create it again

Default: Monday to Friday 06:30, 07:30, 09:30, 11:30, 13:30 and the night sync at 22:00
(the night sync loads the plan of the next school day and is the time for updates).
Sunday only the night sync (for Monday). Saturday: no wake-up.
"""

import sys
from datetime import time

from sqlalchemy import delete, func, insert, select

from db import engine, wake_schedules

NAME = "default"
SCHOOL_DAY_TIMES = [time(6, 30), time(7, 30), time(9, 30), time(11, 30), time(13, 30), time(22, 0)]
DEFAULT_ENTRIES = {0: SCHOOL_DAY_TIMES, 1: SCHOOL_DAY_TIMES, 2: SCHOOL_DAY_TIMES,
                   3: SCHOOL_DAY_TIMES, 4: SCHOOL_DAY_TIMES, 6: [time(22, 0)]}


def main() -> None:
    with engine.begin() as conn:
        count = conn.execute(
            select(func.count()).select_from(wake_schedules).where(wake_schedules.c.name == NAME)
        ).scalar()
        if count and "--reset" not in sys.argv:
            sys.exit(f'Schedule "{NAME}" already exists ({count} entries). Use --reset to replace it.')
        conn.execute(delete(wake_schedules).where(wake_schedules.c.name == NAME))
        rows = [{"name": NAME, "weekday": weekday, "wake_time": wake_time}
                for weekday, times in DEFAULT_ENTRIES.items() for wake_time in times]
        conn.execute(insert(wake_schedules), rows)
    print(f'Schedule "{NAME}" created with {len(rows)} entries.')


if __name__ == "__main__":
    main()