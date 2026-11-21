# SPDX-License-Identifier: GPL-3.0-or-later
"""Admin API for the management web page. All endpoints are below /api/admin and need
HTTP Basic Auth (see admin_auth.py). Changing requests also need the header
X-Requested-With: bert-admin.

Overview:
    GET    /status                         overview: scraper, days, devices, settings
    POST   /refresh, GET /refresh          run scraper + renderer now / state of that run
    GET    /scrapes                        history of scraper runs

    GET    /devices                        all devices with computed status
    POST   /devices                        create a device (token is shown only once)
    PATCH  /devices/{id}                   change name, room, mode, sleep time
    DELETE /devices/{id}                   delete a device
    POST   /devices/{id}/rotate-token      new token (the old one stops working)
    POST   /devices/{id}/clear-error       forget the last reported error
    GET    /devices/{id}/preview.png       image the display should show

    GET    /firmware                       firmware files
    POST   /firmware                       upload a firmware file (multipart form)
    DELETE /firmware/{board}/{version}     delete a firmware file
    POST   /firmware/assign                request/cancel a firmware update for devices

    GET    /schedule                       wake-up schedule with warnings
    PUT    /schedule                       replace the schedule
    GET    /schedule/preview               the next wake-up times

    GET    /teachers                       teacher abbreviations and names
    PUT    /teachers/{abbreviation}        create or change one teacher
    DELETE /teachers/{abbreviation}
    POST   /teachers/bulk                  create or change many teachers
    GET    /teachers/missing               abbreviations used in the plan but without a name
"""

import logging
import os
import subprocess
import sys
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

import add_device
import config  # noqa: F401  (loads the .env)
from admin_auth import admin_auth
from db import DEVICE_MODES, days, device_is_active, devices, engine, lessons, scrapes, teachers, wake_schedules
from firmware_files import FIRMWARE_DIR, FILE_RE, VERSION_RE, firmware_file, firmware_info, firmware_path, list_firmware
from schooldays import display_day
from wake_schedule import JITTER_SECONDS, MIN_GAP_SECONDS, OTA_WINDOW, jitter_for, load_entries, next_wake

log = logging.getLogger("uvicorn.error")
BASE_DIR = Path(__file__).resolve().parent
IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "images"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
BATTERY_LOW_MV = int(os.getenv("BATTERY_LOW_MV", "3500"))
# A device counts as overdue when it is this much later than its next scheduled wake-up.
OVERDUE_GRACE_SECONDS = int(os.getenv("OVERDUE_GRACE_SECONDS", "1800"))
MAX_FIRMWARE_BYTES = 4 * 1024 * 1024
REFRESH_SCRIPTS = ("scraper.py", "renderer.py")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_auth)])


def audit(user: str, text: str) -> None:
    log.info("ADMIN %s: %s", user, text)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def device_status(d, now: datetime, entries) -> str:
    """deactivated | never_seen | ok | overdue"""
    if not device_is_active(d.mode):
        return "deactivated"
    if d.last_seen is None:
        return "never_seen"
    expected = next_wake(d.last_seen, entries, d.id) if entries else None
    if expected is None:
        expected = d.last_seen + timedelta(seconds=d.sleep_seconds)
    return "overdue" if now > expected + timedelta(seconds=OVERDUE_GRACE_SECONDS) else "ok"


def device_dict(d, now: datetime, entries) -> dict:
    return {
        "id": d.id, "name": d.name, "room": d.room, "board": d.board,
        "mode": d.mode, "active": device_is_active(d.mode),
        "status": device_status(d, now, entries),
        "last_seen": d.last_seen, "rssi": d.rssi, "batt_mv": d.batt_mv,
        "battery_low": None if d.batt_mv is None else d.batt_mv < BATTERY_LOW_MV,
        "firmware": {
            "running": d.reported_fw, "wanted": d.desired_fw, "force": bool(d.ota_force),
            "after": d.ota_after, "update_pending": bool(d.desired_fw and d.desired_fw != d.reported_fw),
        },
        "image": {
            "synced": bool(d.desired_hash and d.desired_hash == d.reported_hash),
            "desired_hash": d.desired_hash, "reported_hash": d.reported_hash,
        },
        "sleep_seconds": d.sleep_seconds,
        "last_error": d.last_error, "last_error_at": d.last_error_at,
        "created_at": d.created_at,
    }


def get_device_or_404(conn, device_id: str):
    d = conn.execute(select(devices).where(devices.c.id == device_id)).first()
    if d is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return d


def one_device(device_id: str) -> dict:
    with engine.connect() as conn:
        d = get_device_or_404(conn, device_id)
        return device_dict(d, datetime.now(), load_entries(conn))


def provisioning(device_id: str, token: str) -> list[str]:
    """Console lines for the serial setup of the display (WiFi is entered separately)."""
    lines = [f"set id {device_id}", f"set token {token}"]
    if PUBLIC_URL:
        lines.insert(0, f"set server {PUBLIC_URL}")
    ca_file = Path(os.getenv("CA_B64_FILE", "certs/public/ca.b64"))
    if PUBLIC_URL.startswith("https://") and ca_file.is_file():
        lines.insert(1, f"set ca {ca_file.read_text().strip()}")  # needed for HTTPS
    return lines


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
class DeviceCreate(BaseModel):
    room: str = Field(min_length=1, max_length=40)
    name: str | None = Field(None, max_length=60)


class DevicePatch(BaseModel):
    name: str | None = Field(None, max_length=60)
    room: str | None = Field(None, min_length=1, max_length=40)
    mode: Literal["active", "deactivated"] | None = None
    sleep_seconds: int | None = Field(None, ge=30, le=604800)


@router.get("/devices")
def list_devices():
    now = datetime.now()
    with engine.connect() as conn:
        entries = load_entries(conn)
        rows = conn.execute(select(devices).order_by(devices.c.room, devices.c.id)).all()
    return [device_dict(d, now, entries) for d in rows]


@router.post("/devices", status_code=201)
def create_device(body: DeviceCreate, user: str = Depends(admin_auth)):
    room = body.room.strip()
    if not room:
        raise HTTPException(status_code=422, detail="Room must not be empty")
    device_id, token = add_device.create_device(room, (body.name or "").strip() or None)
    audit(user, f"created device {device_id} for room {room}")
    return {"device": one_device(device_id), "token": token, "console_commands": provisioning(device_id, token),
            "note": "The token is shown only once."}


@router.patch("/devices/{device_id}")
def patch_device(device_id: str, body: DevicePatch, user: str = Depends(admin_auth)):
    values = body.model_dump(exclude_none=True)
    if "room" in values:
        values["room"] = values["room"].strip()
        if not values["room"]:
            raise HTTPException(status_code=422, detail="Room must not be empty")
    if not values:
        raise HTTPException(status_code=422, detail="Nothing to change")
    with engine.begin() as conn:
        get_device_or_404(conn, device_id)
        conn.execute(update(devices).where(devices.c.id == device_id).values(**values))
    audit(user, f"changed device {device_id}: {values}")
    return one_device(device_id)


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, user: str = Depends(admin_auth)):
    with engine.begin() as conn:
        get_device_or_404(conn, device_id)
        conn.execute(delete(devices).where(devices.c.id == device_id))
    for path in IMAGE_DIR.glob(f"{device_id}_*.bin"):
        path.unlink(missing_ok=True)
    (IMAGE_DIR / f"{device_id}.png").unlink(missing_ok=True)
    audit(user, f"deleted device {device_id}")
    return {"deleted": device_id}


@router.post("/devices/{device_id}/rotate-token")
def rotate_token(device_id: str, user: str = Depends(admin_auth)):
    token = add_device.rotate_token(device_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Device not found")
    audit(user, f"rotated the token of device {device_id}")
    return {"token": token, "console_commands": provisioning(device_id, token),
            "note": "The token is shown only once. The display must get it again over the serial console."}


@router.post("/devices/{device_id}/clear-error")
def clear_error(device_id: str, user: str = Depends(admin_auth)):
    with engine.begin() as conn:
        get_device_or_404(conn, device_id)
        conn.execute(update(devices).where(devices.c.id == device_id).values(last_error=None, last_error_at=None))
    return one_device(device_id)


@router.get("/devices/{device_id}/preview.png")
def device_preview(device_id: str):
    with engine.connect() as conn:
        get_device_or_404(conn, device_id)
    path = IMAGE_DIR / f"{device_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No image rendered yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------
# Firmware
# --------------------------------------------------------------------------
class FirmwareAssign(BaseModel):
    device_ids: list[str] | None = None   # None = all devices
    version: str | None = Field(None, max_length=20)
    force: bool = False                   # install at the next wake-up instead of at night
    after: datetime | None = None         # do not install before this time
    clear: bool = False                   # cancel a pending update instead


@router.get("/firmware")
def get_firmware_files():
    files = list_firmware()
    with engine.connect() as conn:
        rows = conn.execute(select(devices.c.id, devices.c.board, devices.c.reported_fw, devices.c.desired_fw)).all()
    for f in files:
        f["devices_running"] = [d.id for d in rows if d.reported_fw == f["version"] and d.board in (None, f["board"])]
        f["devices_wanted"] = [d.id for d in rows if d.desired_fw == f["version"] and d.board in (None, f["board"])]
    return {"directory": str(FIRMWARE_DIR), "files": files}


@router.post("/firmware", status_code=201)
async def upload_firmware(board: str = Form(...), version: str = Form(...), overwrite: bool = Form(False),
                          file: UploadFile = File(...), user: str = Depends(admin_auth)):
    path = firmware_path(board, version)
    if path is None or not FILE_RE.fullmatch(path.name):
        raise HTTPException(status_code=422, detail="Invalid board or version (board: a-z 0-9 _, version starts with a digit)")
    data = await file.read(MAX_FIRMWARE_BYTES + 1)
    if len(data) > MAX_FIRMWARE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    if len(data) < 1024 or data[0] != 0xE9:  # 0xE9 = first byte of an ESP32 application image
        raise HTTPException(status_code=400, detail="This is not an ESP32 firmware image")
    if path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="This version already exists (overwrite=true replaces it)")
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    size, digest = firmware_info(path)
    audit(user, f"uploaded firmware {path.name} ({size} bytes)")
    return {"board": board, "version": version, "size": size, "sha256": digest}


@router.delete("/firmware/{board}/{version}")
def delete_firmware(board: str, version: str, user: str = Depends(admin_auth)):
    path = firmware_file(board, version)
    if path is None:
        raise HTTPException(status_code=404, detail="Firmware not found")
    with engine.connect() as conn:
        wanted_by = [d.id for d in conn.execute(select(devices.c.id, devices.c.board)
                                                .where(devices.c.desired_fw == version)).all()
                     if d.board in (None, board)]
    if wanted_by:
        raise HTTPException(status_code=409, detail=f"Still requested by devices: {', '.join(wanted_by)}")
    path.unlink()
    audit(user, f"deleted firmware {path.name}")
    return {"deleted": path.name}


@router.post("/firmware/assign")
def assign_firmware(body: FirmwareAssign, user: str = Depends(admin_auth)):
    if not body.clear and not (body.version and VERSION_RE.fullmatch(body.version)):
        raise HTTPException(status_code=422, detail="A valid version is required")
    results = []
    with engine.begin() as conn:
        query = select(devices)
        if body.device_ids is not None:
            query = query.where(devices.c.id.in_(body.device_ids))
        rows = conn.execute(query).all()
        found = {d.id for d in rows}
        for missing in sorted(set(body.device_ids or []) - found):
            results.append({"id": missing, "ok": False, "message": "Device not found"})
        for d in rows:
            if body.clear:
                conn.execute(update(devices).where(devices.c.id == d.id)
                             .values(desired_fw=None, ota_force=False, ota_after=None))
                results.append({"id": d.id, "ok": True, "message": "Update cancelled"})
                continue
            if d.board and firmware_file(d.board, body.version) is None:
                results.append({"id": d.id, "ok": False, "message": f"No firmware file for board {d.board}"})
                continue
            if not d.board and not any(f["version"] == body.version for f in list_firmware()):
                results.append({"id": d.id, "ok": False, "message": "No firmware file with this version"})
                continue
            conn.execute(update(devices).where(devices.c.id == d.id)
                         .values(desired_fw=body.version, ota_force=body.force, ota_after=body.after))
            results.append({"id": d.id, "ok": True, "message": "Update requested"})
    audit(user, f"firmware assign: version={body.version} clear={body.clear} force={body.force} "
                f"devices={body.device_ids or 'all'}")
    return {"results": results}


# --------------------------------------------------------------------------
# Wake-up schedule
# --------------------------------------------------------------------------
class ScheduleEntry(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # HH:MM


class ScheduleIn(BaseModel):
    entries: list[ScheduleEntry] = Field(max_length=300)


def _format_point(seconds: int) -> str:
    seconds %= 7 * 86400
    return f"{WEEKDAYS[seconds // 86400]} {seconds % 86400 // 3600:02d}:{seconds % 3600 // 60:02d}"


def schedule_warnings(entries: list[tuple[int, time]]) -> list[str]:
    points = sorted(w * 86400 + t.hour * 3600 + t.minute * 60 for w, t in entries)
    if len(points) < 2:
        return []
    warnings = []
    for a, b in zip(points, points[1:] + [points[0] + 7 * 86400]):
        if b - a < MIN_GAP_SECONDS:
            warnings.append(
                f"{_format_point(a)} and {_format_point(b)} are only {(b - a) // 60} min apart "
                f"(MIN_WAKE_GAP_SECONDS={MIN_GAP_SECONDS}): a display that checks in at the first time "
                f"skips the second one."
            )
    return warnings


def schedule_view(conn) -> dict:
    entries = sorted(load_entries(conn), key=lambda e: (e[0], e[1]))
    return {
        "name": "default",
        "entries": [{"weekday": w, "time": t.strftime("%H:%M")} for w, t in entries],
        "wakes_per_weekday": [sum(1 for w, _ in entries if w == day) for day in range(7)],
        "settings": {"min_gap_seconds": MIN_GAP_SECONDS, "jitter_seconds": JITTER_SECONDS,
                     "ota_window": None if OTA_WINDOW is None else f"{OTA_WINDOW[0]:%H:%M}-{OTA_WINDOW[1]:%H:%M}"},
        "warnings": schedule_warnings(entries),
        "empty_note": "Without entries every device sleeps for its own sleep_seconds." if not entries else None,
    }


@router.get("/schedule")
def get_schedule():
    with engine.connect() as conn:
        return schedule_view(conn)


@router.put("/schedule")
def put_schedule(body: ScheduleIn, user: str = Depends(admin_auth)):
    unique = sorted({(e.weekday, datetime.strptime(e.time, "%H:%M").time()) for e in body.entries})
    with engine.begin() as conn:
        conn.execute(delete(wake_schedules).where(wake_schedules.c.name == "default"))
        if unique:
            conn.execute(insert(wake_schedules), [{"name": "default", "weekday": w, "wake_time": t} for w, t in unique])
    audit(user, f"replaced the wake-up schedule ({len(unique)} entries)")
    with engine.connect() as conn:
        return schedule_view(conn)


@router.get("/schedule/preview")
def schedule_preview(count: int = Query(10, ge=1, le=50), device_id: str = Query("0", max_length=12)):
    with engine.connect() as conn:
        entries = load_entries(conn)
    moment, result = datetime.now(), []
    for _ in range(count):
        following = next_wake(moment, entries, device_id)
        if following is None:
            break
        result.append(following)
        moment = following
    return {"device_id": device_id, "next_wakes": result, "jitter_seconds": jitter_for(device_id)}


# --------------------------------------------------------------------------
# Teachers
# --------------------------------------------------------------------------
class TeacherIn(BaseModel):
    abbreviation: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=80)


class TeacherName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _upsert_teacher(conn, abbreviation: str, name: str) -> str:
    abbreviation, name = abbreviation.strip(), name.strip()
    if not abbreviation or not name:
        raise HTTPException(status_code=422, detail="Abbreviation and name must not be empty")
    exists = conn.execute(select(teachers.c.abbreviation).where(teachers.c.abbreviation == abbreviation)).first()
    if exists:
        conn.execute(update(teachers).where(teachers.c.abbreviation == abbreviation).values(name=name))
        return "updated"
    conn.execute(insert(teachers).values(abbreviation=abbreviation, name=name))
    return "created"


@router.get("/teachers")
def list_teachers(q: str | None = Query(None, max_length=80)):
    query = select(teachers).order_by(teachers.c.abbreviation)
    if q:
        like = f"%{q}%"
        query = query.where(teachers.c.abbreviation.ilike(like) | teachers.c.name.ilike(like))
    with engine.connect() as conn:
        return [{"abbreviation": t.abbreviation, "name": t.name} for t in conn.execute(query).all()]


@router.get("/teachers/missing")
def missing_teachers():
    """Abbreviations that appear in the lessons but have no name yet."""
    with engine.connect() as conn:
        used = {a.strip() for (text,) in conn.execute(select(lessons.c.teacher).distinct()).all()
                for a in (text or "").split(",") if a.strip()}
        known = {t.casefold() for (t,) in conn.execute(select(teachers.c.abbreviation)).all()}
    return sorted(a for a in used if a.casefold() not in known)


@router.put("/teachers/{abbreviation}")
def put_teacher(abbreviation: str, body: TeacherName, user: str = Depends(admin_auth)):
    with engine.begin() as conn:
        outcome = _upsert_teacher(conn, abbreviation, body.name)
    audit(user, f"teacher {abbreviation}: {outcome}")
    return {"abbreviation": abbreviation.strip(), "name": body.name.strip(), "result": outcome}


@router.delete("/teachers/{abbreviation}")
def delete_teacher(abbreviation: str, user: str = Depends(admin_auth)):
    with engine.begin() as conn:
        result = conn.execute(delete(teachers).where(teachers.c.abbreviation == abbreviation))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Teacher not found")
    audit(user, f"deleted teacher {abbreviation}")
    return {"deleted": abbreviation}


@router.post("/teachers/bulk")
def bulk_teachers(items: list[TeacherIn] = Body(..., max_length=2000), user: str = Depends(admin_auth)):
    counts = {"created": 0, "updated": 0}
    with engine.begin() as conn:
        for item in items:
            counts[_upsert_teacher(conn, item.abbreviation, item.name)] += 1
    audit(user, f"teachers bulk import: {counts}")
    return counts


# --------------------------------------------------------------------------
# Status and refresh
# --------------------------------------------------------------------------
_refresh_lock = threading.Lock()
_refresh_state: dict = {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": []}


def _run_refresh() -> None:
    output, ok = [], True
    try:
        for script in REFRESH_SCRIPTS:
            result = subprocess.run([sys.executable, script], cwd=BASE_DIR, capture_output=True, text=True, timeout=300)
            output.append(f"$ {script} (exit code {result.returncode})")
            output += (result.stdout + result.stderr).strip().splitlines()[-15:]
            if result.returncode != 0:
                ok = False
                break
    except Exception as error:  # e.g. timeout
        ok = False
        output.append(f"Error: {error}")
    with _refresh_lock:
        _refresh_state.update(running=False, finished_at=datetime.now(), ok=ok, output=output)


@router.post("/refresh", status_code=202)
def start_refresh(user: str = Depends(admin_auth)):
    """Run the scraper and then the renderer in the background."""
    with _refresh_lock:
        if _refresh_state["running"]:
            raise HTTPException(status_code=409, detail="A refresh is already running")
        _refresh_state.update(running=True, started_at=datetime.now(), finished_at=None, ok=None, output=[])
    threading.Thread(target=_run_refresh, daemon=True, name="admin-refresh").start()
    audit(user, "started scraper + renderer")
    return dict(_refresh_state)


@router.get("/refresh")
def get_refresh():
    with _refresh_lock:
        return dict(_refresh_state)


@router.get("/scrapes")
def list_scrapes(limit: int = Query(30, ge=1, le=200)):
    with engine.connect() as conn:
        rows = conn.execute(select(scrapes).order_by(scrapes.c.id.desc()).limit(limit)).all()
    return [{"id": r.id, "started_at": r.started_at, "status": r.status, "days_saved": r.days_saved,
             "message": r.message} for r in rows]


@router.get("/status")
def status():
    now = datetime.now()
    with engine.connect() as conn:
        entries = load_entries(conn)
        device_rows = conn.execute(select(devices)).all()
        recent = conn.execute(select(scrapes).order_by(scrapes.c.id.desc()).limit(5)).all()
        last_ok = conn.execute(select(func.max(scrapes.c.started_at)).where(scrapes.c.status == "ok")).scalar()
        day_rows = conn.execute(select(days).where(days.c.day >= date.today() - timedelta(days=1))
                                .order_by(days.c.day).limit(15)).all()
    devs = [device_dict(d, now, entries) for d in device_rows]
    counts = {
        "total": len(devs),
        "active": sum(d["active"] for d in devs),
        "deactivated": sum(d["status"] == "deactivated" for d in devs),
        "overdue": sum(d["status"] == "overdue" for d in devs),
        "never_seen": sum(d["status"] == "never_seen" for d in devs),
        "image_open": sum(d["active"] and not d["image"]["synced"] for d in devs),
        "battery_low": sum(bool(d["battery_low"]) for d in devs),
        "with_error": sum(bool(d["last_error"]) for d in devs),
        "update_pending": sum(d["firmware"]["update_pending"] for d in devs),
    }
    with _refresh_lock:
        refresh = dict(_refresh_state)
    return {
        "server_time": now,
        "display_day": display_day(now),
        "scraper": {
            "last_success": last_ok,
            "recent": [{"started_at": r.started_at, "status": r.status, "days_saved": r.days_saved,
                        "message": r.message} for r in recent],
        },
        "days": [{"day": r.day, "source": r.source, "is_free": r.is_free, "scraped_at": r.scraped_at} for r in day_rows],
        "devices": counts,
        "refresh": refresh,
        "settings": {"battery_low_mv": BATTERY_LOW_MV, "overdue_grace_seconds": OVERDUE_GRACE_SECONDS,
                     "device_modes": list(DEVICE_MODES)},
    }