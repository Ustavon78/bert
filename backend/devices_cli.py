# SPDX-License-Identifier: GPL-3.0-or-later
"""Manage devices from the command line (until the admin web page exists).

    python devices_cli.py list
    python devices_cli.py mode <id|all> active|deactivated
    python devices_cli.py fw <id|all> <version> [--force]   request a firmware update
    python devices_cli.py fw <id|all> --clear               cancel a pending update

A firmware update needs the files <board>_<version>.bin in FIRMWARE_DIR. Without --force the
update is installed at the next wake-up inside the OTA window (default 21:00-05:00).
"""

import sys
from datetime import datetime

from sqlalchemy import select, update

from app import FIRMWARE_DIR
from db import DEVICE_MODES, device_is_active, devices, engine
from wake_schedule import OTA_WINDOW


def select_devices(conn, target: str):
    query = select(devices).order_by(devices.c.room, devices.c.id)
    if target != "all":
        query = query.where(devices.c.id == target)
    rows = conn.execute(query).all()
    if not rows:
        sys.exit(f"No device found for '{target}'.")
    return rows


def cmd_list() -> None:
    with engine.connect() as conn:
        rows = conn.execute(select(devices).order_by(devices.c.room, devices.c.id)).all()
    print(f"{'ID':<8}{'ROOM':<8}{'MODE':<13}{'FW (now -> wanted)':<22}{'IMAGE':<8}{'LAST SEEN':<18}RSSI")
    for d in rows:
        fw = f"{d.reported_fw or '?'} -> {d.desired_fw or '-'}"
        synced = "ok" if d.desired_hash and d.desired_hash == d.reported_hash else "open"
        seen = d.last_seen.strftime("%d.%m. %H:%M") if d.last_seen else "never"
        mode = d.mode if device_is_active(d.mode) else f"{d.mode}!"
        print(f"{d.id:<8}{d.room or '':<8}{mode:<13}{fw:<22}{synced:<8}{seen:<18}{d.rssi or ''}")
    print("\nA '!' after the mode means: not 'active', the device is treated as deactivated.")


def cmd_mode(target: str, mode: str) -> None:
    if mode not in DEVICE_MODES:
        sys.exit(f"Unknown mode '{mode}'. Allowed: {', '.join(DEVICE_MODES)}")
    with engine.begin() as conn:
        rows = select_devices(conn, target)
        conn.execute(update(devices).where(devices.c.id.in_([d.id for d in rows])).values(mode=mode))
    print(f"{len(rows)} device(s) set to '{mode}'.")
    print("The change takes effect at the next wake-up of the display "
          "(reset the display to apply it immediately).")


def cmd_fw(target: str, version: str | None, force: bool, clear: bool) -> None:
    with engine.begin() as conn:
        rows = select_devices(conn, target)
        ids = [d.id for d in rows]
        if clear:
            conn.execute(update(devices).where(devices.c.id.in_(ids))
                         .values(desired_fw=None, ota_force=False, ota_after=None))
            print(f"Pending update cancelled for {len(ids)} device(s).")
            return
        files = sorted(FIRMWARE_DIR.glob(f"*_{version}.bin"))
        if not files:
            sys.exit(f"No firmware file '*_{version}.bin' in {FIRMWARE_DIR}/. Copy the files there first.")
        conn.execute(update(devices).where(devices.c.id.in_(ids))
                     .values(desired_fw=version, ota_force=force, ota_after=None))
    print(f"Firmware {version} requested for {len(ids)} device(s). Files: {', '.join(f.name for f in files)}")
    if force:
        print("Forced: installed at the next wake-up of each display.")
    elif OTA_WINDOW is None:
        print("Installed at the next wake-up of each display.")
    else:
        start, end = OTA_WINDOW
        print(f"Installed at the first wake-up inside the OTA window ({start:%H:%M}-{end:%H:%M}).")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if args[:1] == ["list"]:
        cmd_list()
    elif args[:1] == ["mode"] and len(args) == 3:
        cmd_mode(args[1], args[2])
    elif args[:1] == ["fw"] and len(args) == 3 and "--clear" not in flags:
        cmd_fw(args[1], args[2], "--force" in flags, False)
    elif args[:1] == ["fw"] and len(args) == 2 and "--clear" in flags:
        cmd_fw(args[1], None, False, True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()