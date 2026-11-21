# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker for the Docker setup: runs the scraper and then the renderer again and again.

    python worker.py

The renderer runs after every scraper run, also when the scraper failed: the displays switch to
the next school day at a fixed time (see schooldays.py), which needs a new image even without
new data. A failing run never stops the loop.

Settings (.env):
    WORKER_INTERVAL_SECONDS         pause between runs during the day (default 300)
    WORKER_NIGHT_INTERVAL_SECONDS   pause at night (default 1800)
    WORKER_NIGHT=22:00-05:00        what counts as night
"""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, time as day_time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = ("scraper.py", "renderer.py")
RUN_TIMEOUT_SECONDS = 300

stop_requested = False


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] worker: {message}", flush=True)


def parse_window(text: str) -> tuple[day_time, day_time]:
    start, end = text.split("-")
    return day_time.fromisoformat(start.strip()), day_time.fromisoformat(end.strip())


def is_night(now: datetime, window: tuple[day_time, day_time]) -> bool:
    start, end = window
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end  # the window crosses midnight


def request_stop(signum, frame) -> None:
    global stop_requested
    stop_requested = True
    log("stop requested, finishing")


def run_script(name: str) -> bool:
    try:
        result = subprocess.run([sys.executable, name], cwd=BASE_DIR, timeout=RUN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        log(f"{name} was stopped after {RUN_TIMEOUT_SECONDS} seconds")
        return False
    if result.returncode != 0:
        log(f"{name} ended with exit code {result.returncode}")
    return result.returncode == 0


def sleep_interruptible(seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not stop_requested and time.monotonic() < deadline:
        time.sleep(1)


def main() -> None:
    day_interval = int(os.getenv("WORKER_INTERVAL_SECONDS", "300"))
    night_interval = int(os.getenv("WORKER_NIGHT_INTERVAL_SECONDS", "1800"))
    night_window = parse_window(os.getenv("WORKER_NIGHT", "22:00-05:00"))
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    log(f"started (every {day_interval} s, at night every {night_interval} s)")

    while not stop_requested:
        for script in SCRIPTS:  # always both, a failure does not skip the renderer
            if stop_requested:
                break
            run_script(script)
        interval = night_interval if is_night(datetime.now(), night_window) else day_interval
        sleep_interruptible(interval)
    log("stopped")


if __name__ == "__main__":
    main()