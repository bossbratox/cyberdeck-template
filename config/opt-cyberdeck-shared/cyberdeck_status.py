#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-shared/cyberdeck_status.py on Pi
#
# Shared status bar: clock + battery %. Used by F1 (tmux/bash), F5 (dash),
# F6 (wifi), F7 (bt). Battery backend is pluggable: tries MAX17048 fuel
# gauge over I2C; returns None when hardware absent so callers render `--%`.
#
# Curses callers:   draw_curses(stdscr, row=0, right=True)
# Plain text:       format_status(width=None)
# CLI:              python3 -m cyberdeck_status   (prints one line, no newline)

from __future__ import annotations

import curses
import os
import sys
import threading
import time
from datetime import datetime

# ---- Battery sampling -----------------------------------------------------

_I2C_BUS = 1
_MAX17048_ADDR = 0x36
_MAX17048_SOC_REG = 0x04

_BATT_TTL_SEC = 30.0
_batt_cache = {"value": None, "ts": 0.0}
_batt_lock = threading.Lock()


def _read_max17048() -> int | None:
    """Read state-of-charge % from MAX17048 fuel gauge at I2C 0x36.

    Returns int 0-100 on success, None on any failure (no bus, no chip,
    NACK, smbus2 missing). Never raises.
    """
    try:
        from smbus2 import SMBus  # type: ignore
    except Exception:
        return None
    try:
        with SMBus(_I2C_BUS) as bus:
            data = bus.read_i2c_block_data(_MAX17048_ADDR, _MAX17048_SOC_REG, 2)
        # SOC register: high byte = integer %, low byte = 1/256 %.
        pct = data[0] + data[1] / 256.0
        return max(0, min(100, int(round(pct))))
    except Exception:
        return None


def read_battery(force: bool = False) -> int | None:
    """Cached battery read. Returns 0-100 or None if unknown."""
    now = time.time()
    with _batt_lock:
        if not force and now - _batt_cache["ts"] < _BATT_TTL_SEC:
            return _batt_cache["value"]
    value = _read_max17048()
    with _batt_lock:
        _batt_cache["value"] = value
        _batt_cache["ts"] = now
    return value


# ---- Formatting -----------------------------------------------------------

def _battery_glyph(pct: int | None) -> str:
    if pct is None:
        return "--%"
    if pct <= 15:
        return f"!{pct}%"
    return f"{pct}%"


def format_status(width: int | None = None) -> str:
    """Compact status: `HH:MM  85%`. Battery `--%` if unknown."""
    clock = datetime.now().strftime("%H:%M")
    batt = _battery_glyph(read_battery())
    s = f"{clock}  {batt}"
    if width is not None and len(s) > width:
        return clock[:width]
    return s


# ---- Curses helper --------------------------------------------------------

def draw_curses(stdscr, row: int = 0, right: bool = True, attr=None) -> None:
    """Draw status string on `row`. Right-aligned by default.

    Safe against curses.error (small screens, partial draws). Caller is
    responsible for refresh().
    """
    try:
        h, w = stdscr.getmaxyx()
        if row >= h or w < 8:
            return
        s = format_status(width=w - 1)
        if attr is None:
            attr = curses.A_NORMAL
        x = (w - 1 - len(s)) if right else 0
        x = max(0, x)
        stdscr.addnstr(row, x, s, w - 1 - x, attr)
    except curses.error:
        pass


# ---- CLI ------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout.write(format_status())
    sys.stdout.flush()
