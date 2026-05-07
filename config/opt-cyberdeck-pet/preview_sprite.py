#!/usr/bin/env python3
"""Quick curses preview of a sprite JSON file with half-block rendering.

Usage:
    python3 preview_sprite.py sprites/mermaid_happy.json
    python3 preview_sprite.py sprites/mermaid_happy.json --bg sprites/bg_coral_kingdom.json
    python3 preview_sprite.py --all   # cycle through all sprites

Controls:
    Space / Enter    Next sprite (in --all mode)
    [ ]              Prev/next frame
    Q / Esc          Quit
"""

import curses
import json
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pet_pixel import (
    init_pixel_colors, render_halfblock_to_win, new_grid, stamp_grid,
    get_registry,
)

SPRITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")


def load_sprite(path):
    with open(path) as f:
        return json.load(f)


def preview(stdscr, sprite_path, bg_path=None):
    curses.curs_set(0)
    init_pixel_colors()
    reg = get_registry()

    data = load_sprite(sprite_path)
    frames = data["frames"]
    w = data["width"]
    h = data["height"]
    name = data.get("name", os.path.basename(sprite_path))
    fidx = 0

    bg_grid = None
    if bg_path:
        bg_data = load_sprite(bg_path)
        bg_grid = bg_data["grid"]

    stdscr.timeout(250)

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Build display grid
        frame = frames[fidx % len(frames)]

        if bg_grid:
            # Composite sprite onto backdrop
            display = [row[:] for row in bg_grid]
            # Center sprite on backdrop
            sx = (len(bg_grid[0]) - w) // 2
            sy = (len(bg_grid) - h) // 2
            stamp_grid(display, frame, sx, sy)
        else:
            display = frame

        # Render with half-blocks
        render_halfblock_to_win(stdscr, display, start_y=2, start_x=1, default_bg=0)

        # Header
        term_h = (h + 1) // 2
        header = f" {name} | {w}×{h}px ({w}×{term_h} cells) | Frame {fidx % len(frames) + 1}/{len(frames)}"
        try:
            stdscr.addstr(0, 0, header, reg.get(15, 8))
            stdscr.addstr(0, len(header), " " * max(0, max_x - 1 - len(header)), reg.get(15, 8))
        except curses.error:
            pass

        # Footer
        hint = " SPC:next  []:frame  Q:quit"
        try:
            stdscr.addstr(max_y - 1, 0, hint[:max_x - 1], reg.get(8, 0))
        except curses.error:
            pass

        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return "quit"
        elif key in (ord(" "), 10, 13):
            return "next"
        elif key == ord("]"):
            fidx = (fidx + 1) % len(frames)
        elif key == ord("["):
            fidx = (fidx - 1) % len(frames)


def main(stdscr):
    args = sys.argv[1:]

    if "--all" in args:
        files = sorted(glob.glob(os.path.join(SPRITE_DIR, "*.json")))
        for f in files:
            result = preview(stdscr, f)
            if result == "quit":
                break
    else:
        sprite_path = args[0] if args else os.path.join(SPRITE_DIR, "mermaid_happy.json")
        bg_path = None
        if "--bg" in args:
            bg_idx = args.index("--bg")
            if bg_idx + 1 < len(args):
                bg_path = args[bg_idx + 1]
        preview(stdscr, sprite_path, bg_path)


if __name__ == "__main__":
    curses.wrapper(main)
