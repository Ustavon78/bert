# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP API for the e-paper displays.

Run (development):  uvicorn app:app --reload
Run (network):      uvicorn app:app --host 0.0.0.0 --port 8000

Every endpoint except /api/health needs two headers:
    X-Device-Id: <6-digit device id>
    X-Token:     <device token>

Endpoints:
    POST /api/checkin          device reports its state, server answers with an action
    GET  /api/image            current image of the device (two bit planes, 96000 bytes)
    GET  /api/firmware/{ver}   firmware binary, only the version assigned to the device
    GET  /api/health           liveness check (no authentication)
"""

import hashlib
import hmac
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

import config  # noqa: F401  (loads the .env)
from db import devices, engine
from wake_schedule import in_ota_window, load_entries, sleep_seconds

IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "images"))
FIRMWARE_DIR = Path(os.getenv("FIRMWARE_DIR", "firmware"))
DEACTIVATED_SLEEP_SECONDS = int(os.getenv("DEACTIVATED_SLEEP_SECONDS", "86400"))
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,19}")
# Seconds a device stays awake after our answer (download + refresh). The sleep time is
# shortened by this, so that the device wakes up close to the scheduled time.
BUSY_SECONDS = {"image": 40, "ota": 90}

# Interactive docs (/docs) are off by default; set API_DOCS=1 in .env for development.
docs_enabled = os.getenv("API_DOCS", "0") == "1"
app = FastAPI(
    title="E-Paper Display API",
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None,
)


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
def current_device(
        x_device_id: str = Header(max_length=12),
        x_token: str = Header(max_length=128),
):
    """Check device id and token. Unknown id and wrong token give the same answer."""
    with engine.connect() as conn:
        dev = conn.execute(select(devices).where(devices.c.id == x_device_id)).first()
    given = hashlib.sha256(x_token.encode()).hexdigest()
    expected = dev.token_hash if dev is not None else "0" * 64
    # Always compare (also for unknown ids) so the timing does not reveal valid ids.
    if not hmac.compare_digest(given, expected) or dev is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return dev


def require_active(dev) -> None:
    if dev.mode != "active":
        raise HTTPException(status_code=403, detail="Device deactivated")


# --------------------------------------------------------------------------
# Check-in
# --------------------------------------------------------------------------
def _now() -> datetime:
    """Current local time (a separate function so tests can replace it)."""
    return datetime.now()


class Checkin(BaseModel):
    hash: str = Field("", max_length=64)       # hash of the image currently shown
    fw: str = Field("", max_length=20)         # running firmware version
    batt_mv: int | None = Field(None, ge=0, le=10000)
    rssi: int | None = Field(None, ge=-150, le=0)


def decide_action(dev, body: Checkin, now: datetime) -> str:
    """Firmware update first, then new image, otherwise nothing to do."""
    ota_wanted = bool(dev.desired_fw) and dev.desired_fw != body.fw
    # Updates are installed at night (OTA_WINDOW), unless they are forced.
    ota_allowed = dev.ota_force or (
            (dev.ota_after is None or now >= dev.ota_after) and in_ota_window(now)
    )
    if ota_wanted and ota_allowed:
        return "ota"
    if dev.desired_hash and dev.desired_hash != body.hash:
        return "image"
    return "none"


@app.post("/api/checkin")
def checkin(body: Checkin, dev=Depends(current_device)):
    now = _now()
    values = {"last_seen": now, "reported_hash": body.hash or None}
    if body.fw:
        values["reported_fw"] = body.fw
    if body.batt_mv is not None:
        values["batt_mv"] = body.batt_mv
    if body.rssi is not None:
        values["rssi"] = body.rssi

    sleep = DEACTIVATED_SLEEP_SECONDS
    if dev.mode != "active":
        action = "deactivated"
    else:
        action = decide_action(dev, body, now)
        with engine.connect() as conn:
            entries = load_entries(conn)
        # Without schedule entries the fixed per-device sleep time is used.
        sleep = sleep_seconds(now, entries, dev.id, BUSY_SECONDS.get(action, 0), dev.sleep_seconds)
        # The update is done once the device reports the desired version.
        if dev.desired_fw and body.fw == dev.desired_fw and (dev.ota_force or dev.ota_after):
            values["ota_force"] = False
            values["ota_after"] = None

    with engine.begin() as conn:
        conn.execute(update(devices).where(devices.c.id == dev.id).values(**values))

    answer: dict = {"action": action, "sleep": sleep}
    if action == "image":
        answer["hash"] = dev.desired_hash
    elif action == "ota":
        answer["fw"] = dev.desired_fw
    return answer


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
@app.get("/api/image")
def get_image(dev=Depends(current_device)):
    """Send the current image. The device must store the hash from X-Image-Hash."""
    require_active(dev)
    if not dev.desired_hash:
        raise HTTPException(status_code=404, detail="No image yet")
    path = IMAGE_DIR / f"{dev.id}_{dev.desired_hash[:16]}.bin"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(
        path, media_type="application/octet-stream",
        headers={"X-Image-Hash": dev.desired_hash, "Cache-Control": "no-store"},
    )


@app.get("/api/firmware/{version}")
def get_firmware(version: str, dev=Depends(current_device)):
    """Send the firmware, but only the version assigned to this device."""
    require_active(dev)
    if not VERSION_RE.fullmatch(version) or version != dev.desired_fw:
        raise HTTPException(status_code=403, detail="Version not allowed")
    path = FIRMWARE_DIR / f"{version}.bin"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Firmware not found")
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/api/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ok"}