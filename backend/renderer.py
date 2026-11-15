# SPDX-License-Identifier: GPL-3.0-or-later
"""Erzeugt für jedes aktive Display das Bild seines Raums.

Ablauf (nach jedem Scraper-Lauf):
    python scraper.py && python renderer.py
Für jedes Display wird das Bild des Anzeigetags gezeichnet und ein Hash gebildet.
Hat sich der Hash geändert, wird das Bild gespeichert und als desired_hash eingetragen.
"""

import hashlib
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, update

import config  # noqa: F401  (lädt die .env)
from db import days, devices, engine, lessons, teachers
from schooldays import display_day

WIDTH, HEIGHT = 800, 480
WHITE, BLACK, RED = (255, 255, 255), (0, 0, 0), (255, 0, 0)

IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "images"))
FONT_REGULAR = os.getenv("FONT_REGULAR", "DejaVuSans.ttf")
FONT_BOLD = os.getenv("FONT_BOLD", "DejaVuSans-Bold.ttf")

HEADER_H, FOOTER_H, MARGIN = 70, 22, 20
NUM_PERIODS = int(os.getenv("NUM_PERIODS", "8"))  # so viele Stunden werden immer angezeigt
BLOCK_SIZE = int(os.getenv("BLOCK_SIZE", "2"))    # Stunden pro Block (Doppelstunde = 2), 0 = aus
MAX_PERIODS = 12
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


@lru_cache(maxsize=None)
def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def fit(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> str:
    """Kürzt den Text mit '…', bis er in die Breite passt."""
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > max_width:
        text = text[:-1]
    return text + "…"


def split_teachers(text: str | None) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def resolve_teachers(text: str | None, names: dict[str, str]) -> str:
    """Ersetzt Kürzel durch Namen aus der Tabelle teachers (unbekannte Kürzel bleiben stehen)."""
    return ", ".join(names.get(abbr.casefold(), abbr) for abbr in split_teachers(text))


def group_lessons(rows, teacher_names: dict[str, str]) -> list[SimpleNamespace]:
    """Fasst gleiche Stunden mehrerer Klassen zu einer Zeile zusammen."""
    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r.period, r.subject, r.teacher, r.info, r.cancelled,
               r.subject_changed, r.teacher_changed, r.room_changed, r.class_changed)
        groups.setdefault(key, []).append(r.class_name)
    result = []
    for key, classes in groups.items():
        (period, subject, teacher, info, cancelled,
         subject_ch, teacher_ch, room_ch, class_ch) = key
        names = sorted({c for c in classes if c})
        result.append(SimpleNamespace(
            period=period, subject=subject or "", teacher=resolve_teachers(teacher, teacher_names), info=info or "",
            cancelled=cancelled, subject_changed=subject_ch, teacher_changed=teacher_ch,
            room_changed=room_ch, class_changed=class_ch, classes=", ".join(names),
        ))
    result.sort(key=lambda g: (g.period, g.classes, g.subject))
    return result


def draw_message(draw, text: str) -> None:
    f = font(True, 34)
    draw.text((WIDTH // 2, (HEIGHT + HEADER_H) // 2), text, font=f, fill=BLACK, anchor="mm")


COLS = {"subject": (90, 190), "class": (285, 100), "teacher": (390, 190), "info": (590, WIDTH - MARGIN - 590)}


def draw_group(draw, g: SimpleNamespace, y: float, h: float) -> None:
    """Zeichnet eine Unterrichtsstunde in ein Feld der Höhe h (ab y)."""
    size = max(13, min(24, int(h * 0.42)))
    f_norm, f_bold, f_info = font(False, size), font(True, size + 2), font(False, max(13, size - 3))
    mid = int(y + h / 2)
    any_change = (g.cancelled or g.subject_changed or g.teacher_changed
                  or g.room_changed or g.class_changed)

    subj = fit(draw, g.subject, f_bold, COLS["subject"][1])
    x = COLS["subject"][0]
    draw.text((x, mid), subj, font=f_bold, fill=RED if g.subject_changed else BLACK, anchor="lm")
    if g.cancelled:  # durchgestrichen
        draw.line((x, mid, x + draw.textlength(subj, font=f_bold), mid), fill=RED, width=2)

    draw.text((COLS["class"][0], mid), fit(draw, g.classes, f_norm, COLS["class"][1]),
              font=f_norm, fill=RED if g.class_changed else BLACK, anchor="lm")
    draw.text((COLS["teacher"][0], mid), fit(draw, g.teacher, f_norm, COLS["teacher"][1]),
              font=f_norm, fill=RED if g.teacher_changed else BLACK, anchor="lm")

    if g.cancelled:
        status = f"Entfall: {g.info}" if g.info else "Entfall"
    elif g.room_changed:
        status = "Raum geändert"
    else:
        status = g.info
    draw.text((COLS["info"][0], mid), fit(draw, status, f_info, COLS["info"][1]),
              font=f_info, fill=RED if any_change else BLACK, anchor="lm")


def draw_rows(draw, groups: list[SimpleNamespace]) -> None:
    """Eine Zeile pro Stunde (1 bis NUM_PERIODS), auch freie Stunden."""
    by_period: dict[int, list] = defaultdict(list)
    for g in groups:
        by_period[g.period].append(g)
    last = min(max([NUM_PERIODS, *by_period]), MAX_PERIODS)
    top, bottom = HEADER_H + 6, HEIGHT - FOOTER_H
    row_h = (bottom - top) / last

    for p in range(1, last + 1):
        y = top + (p - 1) * row_h
        mid = int(y + row_h / 2)
        draw.text((MARGIN + 18, mid), str(p), font=font(True, int(min(row_h * 0.62, 34))),
                  fill=BLACK, anchor="mm")
        items = by_period.get(p, [])
        if not items:
            draw.text((COLS["subject"][0], mid), "frei", font=font(False, max(13, min(22, int(row_h * 0.4)))),
                      fill=BLACK, anchor="lm")
        else:
            shown = items[:2]
            sub_h = row_h / len(shown)
            for k, g in enumerate(shown):
                draw_group(draw, g, y + k * sub_h, sub_h)
            if len(items) > 2:
                draw.text((WIDTH - MARGIN, int(y + row_h) - 2), f"+{len(items) - 2}",
                          font=font(True, 13), fill=RED, anchor="rd")
        if p < last:
            line_y = int(y + row_h)
            block_end = BLOCK_SIZE > 0 and p % BLOCK_SIZE == 0
            draw.line((MARGIN, line_y, WIDTH - MARGIN, line_y), fill=BLACK, width=3 if block_end else 1)


def draw_image(room: str, day: date, day_row, rows, names: dict[str, str]) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # keine Kantenglättung: nur reine Farben (Schwarz/Weiß/Rot)

    # Kopfzeile
    draw.text((MARGIN, HEADER_H // 2), f"Raum {room}", font=font(True, 42), fill=BLACK, anchor="lm")
    draw.text((WIDTH - MARGIN, HEADER_H // 2), f"{WEEKDAYS[day.weekday()]}, {day:%d.%m.%Y}",
              font=font(False, 26), fill=BLACK, anchor="rm")
    draw.line((MARGIN, HEADER_H, WIDTH - MARGIN, HEADER_H), fill=BLACK, width=3)

    # Inhalt
    if day_row is None:
        draw_message(draw, "Plan noch nicht verfügbar")
    elif day_row.is_free:
        draw_message(draw, "Unterrichtsfrei")
    else:
        draw_rows(draw, group_lessons(rows, names))

    # Fußzeile: bewusst KEIN Planstand/Uhrzeit. Jede Veröffentlichung bei vpmobil würde sonst
    # das Bild aller Displays ändern, auch wenn sich ihr Raum nicht geändert hat.
    footer = "Regulärer Stundenplan" if day_row is not None and day_row.source == "normal" else ""
    if footer:
        draw.text((WIDTH - MARGIN, HEIGHT - 6), footer, font=font(False, 14), fill=BLACK, anchor="rd")
    return img


def pack_planes(img: Image.Image) -> bytes:
    """Schwarz- und Rot-Ebene als je 1 Bit pro Pixel (1 = Farbe), Zeile für Zeile, MSB zuerst."""
    arr = np.asarray(img.convert("RGB"))
    red = (arr[..., 0] > 127) & (arr[..., 1] < 128) & (arr[..., 2] < 128)
    black = (arr[..., 0] < 128) & (arr[..., 1] < 128) & (arr[..., 2] < 128)
    return np.packbits(black, axis=1).tobytes() + np.packbits(red, axis=1).tobytes()


def save_image(device_id: str, new_hash: str, data: bytes, img: Image.Image) -> None:
    """Speichert die Bitplanes unter <id>_<hash>.bin (atomar) und eine PNG-Vorschau."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGE_DIR / f"{device_id}_{new_hash[:16]}.bin"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    img.save(IMAGE_DIR / f"{device_id}.png")


def remove_old_images(device_id: str, new_hash: str) -> None:
    for old in IMAGE_DIR.glob(f"{device_id}_*.bin"):
        if not old.name.startswith(f"{device_id}_{new_hash[:16]}"):
            old.unlink(missing_ok=True)


def main() -> int:
    day = display_day()
    with engine.connect() as conn:
        active = conn.execute(select(devices).where(devices.c.mode == "active")).all()
        day_row = conn.execute(select(days).where(days.c.day == day)).first()
        rows = conn.execute(select(lessons).where(lessons.c.day == day)).all()
        names = {t.abbreviation.strip().casefold(): t.name
                 for t in conn.execute(select(teachers)).all()}

    by_room = defaultdict(list)
    for row in rows:
        by_room[row.room].append(row)

    missing = sorted({a for r in rows for a in split_teachers(r.teacher) if a.casefold() not in names})
    if missing:
        log(f"Kürzel ohne Namen in der Tabelle teachers ({len(missing)}): {', '.join(missing[:15])}"
            + (" …" if len(missing) > 15 else ""))
    log(f"Anzeigetag: {day} ({len(active)} aktive Displays)")
    updated = errors = 0
    for dev in active:
        try:
            room = str(dev.room).strip()
            img = draw_image(room, day, day_row, by_room.get(room, []), names)
            data = pack_planes(img)
            new_hash = hashlib.sha256(data).hexdigest()
            if new_hash == dev.desired_hash:
                continue
            save_image(dev.id, new_hash, data, img)
            with engine.begin() as conn:
                conn.execute(update(devices).where(devices.c.id == dev.id).values(
                    desired_hash=new_hash))
            remove_old_images(dev.id, new_hash)
            updated += 1
            log(f"Display {dev.id} (Raum {room}): neues Bild {new_hash[:8]}")
        except Exception as error:  # ein Display darf die anderen nicht blockieren
            errors += 1
            log(f"Display {dev.id}: Fehler: {error}")
    log(f"Fertig: {updated} Bild(er) aktualisiert, {errors} Fehler.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())