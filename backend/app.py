# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP API for the e-paper displays.

Run (development):  uvicorn app:app --reload
Run (network):      uvicorn app:app --host 0.0.0.0 --port 8000

Every endpoint except /api/health needs two headers:
    X-Device-Id: <6-digit device id>
    X-Token:     <device token>

Endpoints:
    POST /api/checkin                    device reports its state, server answers with an action
    GET  /api/image                      current image of the device (two bit planes, 96000 bytes)
    GET  /api/firmware/{board}/{ver}     firmware binary, only the version assigned to the device
    GET  /api/health                     liveness check (no authentication)

Firmware files live in FIRMWARE_DIR and are named <board>_<version>.bin,
for example waveshare_esp32_0.3.1.bin.
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

import config  # noqa: F401  (loads the .env)
from db import DEVICE_MODES, device_is_active, devices, engine, normalize_mode
from admin_api import router as admin_router
from firmware_files import firmware_file, firmware_info
from wake_schedule import in_ota_window, load_entries, sleep_seconds

IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "images"))
# A deactivated device still checks in now and then, so that it notices when it is activated again.
DEACTIVATED_SLEEP_SECONDS = int(os.getenv("DEACTIVATED_SLEEP_SECONDS", "14400"))
# Seconds a device stays awake after our answer (download + refresh). The sleep time is
# shortened by this, so that the device wakes up close to the scheduled time.
BUSY_SECONDS = {"image": 40, "ota": 90}

log = logging.getLogger("uvicorn.error")

# Interactive docs (/docs) are off by default; set API_DOCS=1 in .env for development.
docs_enabled = os.getenv("API_DOCS", "0") == "1"
app = FastAPI(
    title="E-Paper Display API",
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

app.include_router(admin_router)

# Only needed while the admin web page is developed on another address/port than the API.
# In production nginx serves page and API from the same address, CORS stays off.
cors_origins = [o.strip() for o in os.getenv("ADMIN_CORS_ORIGINS", "").split(",") if o.strip()]
if cors_origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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
    if normalize_mode(dev.mode) not in DEVICE_MODES:
        log.warning("Device %s has the unknown mode %r and is treated as deactivated", dev.id, dev.mode)
    return dev


def require_active(dev) -> None:
    if not device_is_active(dev.mode):
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
    board: str = Field("", max_length=30)      # board type, selects the firmware file
    batt_mv: int | None = Field(None, ge=0, le=10000)
    rssi: int | None = Field(None, ge=-150, le=0)
    err: str = Field("", max_length=100)       # last error of the device (e.g. a failed update)


def decide_action(dev, body: Checkin, now: datetime, firmware_available: bool) -> str:
    """Firmware update first, then new image, otherwise nothing to do."""
    ota_wanted = bool(dev.desired_fw) and dev.desired_fw != body.fw
    # Updates are installed at night (OTA_WINDOW), unless they are forced.
    ota_allowed = dev.ota_force or (
            (dev.ota_after is None or now >= dev.ota_after) and in_ota_window(now)
    )
    if ota_wanted and ota_allowed:
        if firmware_available:
            return "ota"
        log.warning("Device %s should get firmware %s for board %r, but the file is missing",
                    dev.id, dev.desired_fw, body.board)
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
    if body.board:
        values["board"] = body.board
    if body.err:
        log.warning("Device %s (room %s) reports: %s", dev.id, dev.room, body.err)
        values["last_error"] = body.err
        values["last_error_at"] = now

    sleep = DEACTIVATED_SLEEP_SECONDS
    fw_path = None
    if not device_is_active(dev.mode):
        action = "deactivated"
    else:
        if dev.desired_fw and dev.desired_fw != body.fw:
            fw_path = firmware_file(body.board, dev.desired_fw)
        action = decide_action(dev, body, now, fw_path is not None)
        with engine.connect() as conn:
            entries = load_entries(conn)
        # Without schedule entries the fixed per-device sleep time is used.
        sleep = sleep_seconds(now, entries, dev.id, BUSY_SECONDS.get(action, 0), dev.sleep_seconds)
        # The update is done once the device reports the desired version.
        if dev.desired_fw and body.fw == dev.desired_fw and (dev.ota_force or dev.ota_after):
            values["ota_force"] = False
            values["ota_after"] = None
            values["last_error"] = None  # a successful update clears the old error
            values["last_error_at"] = None

    with engine.begin() as conn:
        conn.execute(update(devices).where(devices.c.id == dev.id).values(**values))

    answer: dict = {"action": action, "sleep": sleep}
    if action == "ota":
        size, digest = firmware_info(fw_path)
        answer.update(fw=dev.desired_fw, size=size, sha256=digest)
    # A pending image is always announced, even next to an update: if the device skips the
    # update (e.g. after failures) it can still refresh its display.
    if action in ("image", "ota") and dev.desired_hash and dev.desired_hash != body.hash:
        answer["hash"] = dev.desired_hash
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


@app.get("/api/firmware/{board}/{version}")
def get_firmware(board: str, version: str, dev=Depends(current_device)):
    """Send the firmware, but only the version assigned to this device."""
    require_active(dev)
    if version != dev.desired_fw:
        raise HTTPException(status_code=403, detail="Version not allowed")
    path = firmware_file(board, version)
    if path is None:
        raise HTTPException(status_code=404, detail="Firmware not found")
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/api/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ok"}