# SPDX-License-Identifier: GPL-3.0-or-later
"""Firmware files in FIRMWARE_DIR, named <board>_<version>.bin (e.g. waveshare_esp32_0.3.1.bin)."""

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

import config  # noqa: F401  (loads the .env)

FIRMWARE_DIR = Path(os.getenv("FIRMWARE_DIR", "firmware"))
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,19}")
BOARD_RE = re.compile(r"[a-z0-9_]{1,30}")
# Board = everything before the first "_" that is followed by a digit (the version).
FILE_RE = re.compile(r"([a-z0-9_]+?)_(\d[0-9A-Za-z._-]{0,19})\.bin")

_cache: dict[Path, tuple[float, int, str]] = {}  # path -> (mtime, size, sha256)


def firmware_path(board: str, version: str) -> Path | None:
    """Path where the file would be, or None if board or version are not valid names."""
    if not BOARD_RE.fullmatch(board) or not VERSION_RE.fullmatch(version):
        return None
    return FIRMWARE_DIR / f"{board}_{version}.bin"


def firmware_file(board: str, version: str) -> Path | None:
    """Path of an existing firmware file, or None."""
    path = firmware_path(board, version)
    return path if path is not None and path.is_file() else None


def firmware_info(path: Path) -> tuple[int, str]:
    """Size and SHA-256 of a firmware file (cached until the file changes)."""
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    _cache[path] = (mtime, len(data), digest)
    return len(data), digest


def list_firmware() -> list[dict]:
    """All valid firmware files, newest first."""
    result = []
    if FIRMWARE_DIR.is_dir():
        for path in FIRMWARE_DIR.iterdir():
            match = FILE_RE.fullmatch(path.name)
            if match and path.is_file():
                size, digest = firmware_info(path)
                result.append({
                    "board": match.group(1), "version": match.group(2), "size": size,
                    "sha256": digest, "modified": datetime.fromtimestamp(path.stat().st_mtime),
                })
    return sorted(result, key=lambda f: f["modified"], reverse=True)