#!/usr/bin/env python3
"""Interactive sprite editor for mermaid tamagotchi pixel art.

Half-block pixel art editor with 16-color cyberdeck palette.
Target: 106×33 terminal (6×12 font on 640×400 DSI display).

Usage:
    python3 sprite_editor.py [sprite.json]
    python3 sprite_editor.py --new WIDTHxHEIGHT [sprite.json]

Controls:
    Arrow keys         Move cursor
    Space / Enter      Paint pixel with current color
    0-9, a-f           Select palette color (hex)
    X / Delete         Erase pixel (set transparent)
    I                  Eyedropper (pick color under cursor)
    F (shift)          Flood fill
    G                  Toggle grid overlay
    M                  Toggle mirror mode (horizontal symmetry)
    U                  Undo (up to 50 steps)
    R                  Redo
    [  ]               Prev/next frame (animation)
    N                  New frame (copy current)
    Shift+N            Delete current frame
    +  -               Resize canvas
    P                  Toggle preview panel
    T                  Test animation (play all frames)
    S / Ctrl+S         Save
    L                  Load
    Q / Esc            Quit

Layout:
    Left: pixel grid (each pixel = 2×1 chars in editor, colored block)
    Right: half-block preview + palette + info
"""

import curses
import json
import os
import sys
import time

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pet_pixel import (
    PALETTE, PALETTE_NAMES, remap_palette, ColorPairRegistry,
    render_halfblock, new_grid, init_pixel_colors, get_registry,
)


class SpriteEditor:
    MAX_UNDO = 50

    def __init__(self, stdscr, filepath=None, width=30, height=40):
        self.stdscr = stdscr
        self.filepath = filepath
        self.frames = [new_grid(width, height)]
        self.frame_idx = 0
        self.cx, self.cy = 0, 0  # cursor in pixel coords
        self.color = 5  # current palette color (deep pink)
        self.grid_on = True
        self.mirror = False
        self.preview_on = True
        self.scroll_x, self.scroll_y = 0, 0  # viewport scroll
        self.undo_stack = []
        self.redo_stack = []
        self.dirty = False
        self.message = ""
        self.msg_time = 0
        self.anim_playing = False
        self.name = "untitled"
        self.anchor_x = 0
        self.anchor_y = 0

        if filepath and os.path.exists(filepath):
            self._load(filepath)

        curses.curs_set(0)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        init_pixel_colors()

        # Editor-specific color pairs for UI chrome
        self._reg = get_registry()

    @property
    def grid(self):
        return self.frames[self.frame_idx]

    @grid.setter
    def grid(self, val):
        self.frames[self.frame_idx] = val

    @property
    def pw(self):
        return len(self.grid[0]) if self.grid else 0

    @property
    def ph(self):
        return len(self.grid)

    # ── Undo / Redo ──────────────────────────────────────────────────

    def _push_undo(self):
        snapshot = [row[:] for row in self.grid]
        self.undo_stack.append((self.frame_idx, snapshot))
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack:
            self._msg("Nothing to undo")
            return
        # Save current for redo
        self.redo_stack.append((self.frame_idx, [row[:] for row in self.grid]))
        fidx, snapshot = self.undo_stack.pop()
        self.frame_idx = fidx
        self.grid = snapshot
        self._msg("Undo")

    def _redo(self):
        if not self.redo_stack:
            self._msg("Nothing to redo")
            return
        self.undo_stack.append((self.frame_idx, [row[:] for row in self.grid]))
        fidx, snapshot = self.redo_stack.pop()
        self.frame_idx = fidx
        self.grid = snapshot
        self._msg("Redo")

    # ── Drawing ──────────────────────────────────────────────────────

    def _paint(self, x, y, color):
        if 0 <= x < self.pw and 0 <= y < self.ph:
            if self.grid[y][x] != color:
                self._push_undo()
                self.grid[y][x] = color
                self.dirty = True
                if self.mirror:
                    mx = self.pw - 1 - x
                    if 0 <= mx < self.pw:
                        self.grid[y][mx] = color

    def _erase(self, x, y):
        if 0 <= x < self.pw and 0 <= y < self.ph:
            if self.grid[y][x] is not None:
                self._push_undo()
                self.grid[y][x] = None
                self.dirty = True
                if self.mirror:
                    mx = self.pw - 1 - x
                    if 0 <= mx < self.pw:
                        self.grid[y][mx] = None

    def _eyedrop(self, x, y):
        if 0 <= x < self.pw and 0 <= y < self.ph:
            c = self.grid[y][x]
            if c is not None:
                self.color = c
                self._msg(f"Picked color {c}: {PALETTE_NAMES.get(c, '?')}")

    def _flood_fill(self, x, y, new_color):
        if not (0 <= x < self.pw and 0 <= y < self.ph):
            return
        old = self.grid[y][x]
        if old == new_color:
            return
        self._push_undo()
        self.dirty = True
        stack = [(x, y)]
        while stack:
            fx, fy = stack.pop()
            if not (0 <= fx < self.pw and 0 <= fy < self.ph):
                continue
            if self.grid[fy][fx] != old:
                continue
            self.grid[fy][fx] = new_color
            stack.extend([(fx+1, fy), (fx-1, fy), (fx, fy+1), (fx, fy-1)])

    # ── Frame Management ─────────────────────────────────────────────

    def _next_frame(self):
        if self.frame_idx < len(self.frames) - 1:
            self.frame_idx += 1
            self._msg(f"Frame {self.frame_idx + 1}/{len(self.frames)}")

    def _prev_frame(self):
        if self.frame_idx > 0:
            self.frame_idx -= 1
            self._msg(f"Frame {self.frame_idx + 1}/{len(self.frames)}")

    def _new_frame(self):
        copy = [row[:] for row in self.grid]
        self.frames.insert(self.frame_idx + 1, copy)
        self.frame_idx += 1
        self._msg(f"New frame {self.frame_idx + 1}/{len(self.frames)}")

    def _delete_frame(self):
        if len(self.frames) <= 1:
            self._msg("Can't delete last frame")
            return
        self.frames.pop(self.frame_idx)
        if self.frame_idx >= len(self.frames):
            self.frame_idx = len(self.frames) - 1
        self._msg(f"Deleted. Frame {self.frame_idx + 1}/{len(self.frames)}")

    # ── Save / Load ──────────────────────────────────────────────────

    def _save(self, path=None):
        path = path or self.filepath
        if not path:
            self._msg("No file path set!")
            return
        data = {
            "name": self.name,
            "width": self.pw,
            "height": self.ph,
            "anchor": [self.anchor_x, self.anchor_y],
            "frames": self.frames,
        }
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        self.filepath = path
        self.dirty = False
        self._msg(f"Saved: {os.path.basename(path)}")

    def _load(self, path):
        with open(path, "r") as f:
            data = json.load(f)
        self.name = data.get("name", "untitled")
        self.frames = data["frames"]
        self.anchor_x = data.get("anchor", [0, 0])[0]
        self.anchor_y = data.get("anchor", [0, 0])[1]
        self.frame_idx = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self._msg(f"Loaded: {os.path.basename(path)}")

    def _prompt_save(self):
        if not self.filepath:
            self._msg("Enter filename: ")
            self._draw()
            curses.echo()
            curses.curs_set(1)
            h, w = self.stdscr.getmaxyx()
            self.stdscr.move(h - 1, 16)
            try:
                name = self.stdscr.getstr(h - 1, 16, 60).decode("utf-8").strip()
            except Exception:
                name = ""
            curses.noecho()
            curses.curs_set(0)
            if not name:
                self._msg("Save cancelled")
                return
            if not name.endswith(".json"):
                name += ".json"
            self.filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites", name)
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self._save()

    # ── Resize ───────────────────────────────────────────────────────

    def _resize(self, dw, dh):
        self._push_undo()
        for i, frame in enumerate(self.frames):
            new_h = max(2, len(frame) + dh)
            new_w = max(2, (len(frame[0]) if frame else 1) + dw)
            new_frame = new_grid(new_w, new_h)
            for y in range(min(len(frame), new_h)):
                for x in range(min(len(frame[y]) if frame else 0, new_w)):
                    new_frame[y][x] = frame[y][x]
            self.frames[i] = new_frame
        self._msg(f"Canvas: {self.pw}×{self.ph}")

    # ── Message ──────────────────────────────────────────────────────

    def _msg(self, text):
        self.message = text
        self.msg_time = time.time()

    # ── Drawing UI ───────────────────────────────────────────────────

    def _draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        reg = self._reg

        # Layout: editor grid on left, preview + palette on right
        # Each pixel in editor = 2 chars wide × 1 char tall (colored "██" or "░░")
        editor_w = min(self.pw * 2, w - 30)  # reserve 30 cols for right panel
        editor_h = min(self.ph, h - 3)       # reserve 3 rows for status

        # Auto-scroll to keep cursor visible
        if self.cx * 2 - self.scroll_x >= editor_w:
            self.scroll_x = self.cx * 2 - editor_w + 2
        if self.cx * 2 - self.scroll_x < 0:
            self.scroll_x = self.cx * 2
        if self.cy - self.scroll_y >= editor_h:
            self.scroll_y = self.cy - editor_h + 1
        if self.cy - self.scroll_y < 0:
            self.scroll_y = self.cy

        # Draw pixel grid
        for sy in range(editor_h):
            py = sy + self.scroll_y
            if py >= self.ph:
                break
            for sx in range(0, editor_w, 2):
                px = (sx + self.scroll_x) // 2
                if px >= self.pw:
                    break
                screen_x = sx
                screen_y = sy + 1  # row 0 is header

                c = self.grid[py][px]
                is_cursor = (px == self.cx and py == self.cy)

                if c is not None:
                    attr = reg.get(c, c)
                    ch = "██"
                    if is_cursor:
                        # Invert for cursor visibility
                        attr = reg.get(0, c) if c != 0 else reg.get(15, 0)
                        ch = "▓▓"
                else:
                    # Transparent — show checkerboard
                    if (px + py) % 2 == 0:
                        attr = reg.get(8, 0)
                        ch = "░░" if not is_cursor else "▓▓"
                    else:
                        attr = reg.get(0, 8) if not is_cursor else reg.get(15, 8)
                        ch = "  " if not is_cursor else "▓▓"

                # Grid lines
                if self.grid_on and not is_cursor:
                    if px % 5 == 0 or py % 5 == 0:
                        if c is None:
                            attr = reg.get(8, 0)
                            ch = "··" if not is_cursor else "▓▓"

                # Mirror line
                if self.mirror and px == self.pw // 2:
                    if c is None:
                        attr = reg.get(5, 0)
                        ch = "│ "

                try:
                    self.stdscr.addstr(screen_y, screen_x, ch, attr)
                except curses.error:
                    pass

        # Right panel starts after editor grid
        panel_x = editor_w + 2
        if panel_x >= w - 2:
            panel_x = w - 28

        # ── Header row ───────────────────────────────────────────
        header = f" {self.name} {self.pw}×{self.ph} F{self.frame_idx+1}/{len(self.frames)}"
        if self.dirty:
            header += " *"
        if self.mirror:
            header += " [M]"
        try:
            self.stdscr.addstr(0, 0, header[:w-1], reg.get(15, 8))
            self.stdscr.addstr(0, len(header), " " * max(0, w - 1 - len(header)), reg.get(15, 8))
        except curses.error:
            pass

        # ── Palette (right panel) ────────────────────────────────
        py_start = 1
        try:
            self.stdscr.addstr(py_start, panel_x, "Palette:", reg.get(15, 0))
        except curses.error:
            pass

        for i in range(16):
            row = py_start + 1 + i
            if row >= h - 2:
                break
            hex_key = format(i, "x")
            selected = " >" if i == self.color else "  "
            swatch = "██"
            label = f" {hex_key} {PALETTE_NAMES.get(i, '?')[:12]}"

            try:
                self.stdscr.addstr(row, panel_x, selected, reg.get(15 if i == self.color else 8, 0))
                self.stdscr.addstr(row, panel_x + 2, swatch, reg.get(i, i))
                self.stdscr.addstr(row, panel_x + 4, label[:w - panel_x - 5],
                                   reg.get(15 if i == self.color else 12, 0))
            except curses.error:
                pass

        # ── Half-block preview (right panel, below palette) ──────
        if self.preview_on:
            prev_y = py_start + 18
            try:
                self.stdscr.addstr(prev_y, panel_x, "Preview:", reg.get(15, 0))
            except curses.error:
                pass

            preview = render_halfblock(self.grid, default_bg=0)
            max_prev_h = h - prev_y - 3
            max_prev_w = w - panel_x - 1
            for dy, row in enumerate(preview):
                if dy >= max_prev_h:
                    break
                for dx, (ch, attr) in enumerate(row):
                    if dx >= max_prev_w:
                        break
                    try:
                        self.stdscr.addstr(prev_y + 1 + dy, panel_x + dx, ch, attr)
                    except curses.error:
                        pass

        # ── Status bar (bottom) ──────────────────────────────────
        status_y = h - 2
        cursor_info = f"({self.cx},{self.cy})"
        c_under = self.grid[self.cy][self.cx] if 0 <= self.cy < self.ph and 0 <= self.cx < self.pw else None
        c_name = PALETTE_NAMES.get(c_under, "transparent") if c_under is not None else "transparent"
        status = f" {cursor_info} color:{self.color}={PALETTE_NAMES.get(self.color, '?')}  under:{c_name}  anchor:({self.anchor_x},{self.anchor_y})"
        try:
            self.stdscr.addstr(status_y, 0, status[:w-1], reg.get(12, 0))
        except curses.error:
            pass

        # Message line
        if self.message and time.time() - self.msg_time < 3:
            try:
                self.stdscr.addstr(h - 1, 0, f" {self.message}"[:w-1], reg.get(11, 0))
            except curses.error:
                pass

        # Controls hint
        help_y = h - 1
        if not self.message or time.time() - self.msg_time >= 3:
            hint = " SPC:paint X:erase I:pick F:fill G:grid M:mirror U:undo S:save 0-f:color Q:quit"
            try:
                self.stdscr.addstr(help_y, 0, hint[:w-1], reg.get(8, 0))
            except curses.error:
                pass

        self.stdscr.noutrefresh()
        curses.doupdate()

    # ── Animation Preview ────────────────────────────────────────

    def _play_animation(self):
        self._msg("Playing animation... (any key to stop)")
        self._draw()
        self.stdscr.timeout(250)  # 4 FPS
        h, w = self.stdscr.getmaxyx()
        reg = self._reg
        panel_x = min(self.pw * 2, w - 30) + 2

        fidx = 0
        while True:
            frame = self.frames[fidx % len(self.frames)]
            preview = render_halfblock(frame, default_bg=0)

            prev_y = 20
            for dy, row in enumerate(preview):
                if prev_y + 1 + dy >= h - 2:
                    break
                # Clear line first
                try:
                    self.stdscr.addstr(prev_y + 1 + dy, panel_x, " " * min(self.pw, w - panel_x - 1))
                except curses.error:
                    pass
                for dx, (ch, attr) in enumerate(row):
                    if dx >= w - panel_x - 1:
                        break
                    try:
                        self.stdscr.addstr(prev_y + 1 + dy, panel_x + dx, ch, attr)
                    except curses.error:
                        pass

            # Frame counter
            try:
                self.stdscr.addstr(prev_y, panel_x, f"Anim F{fidx % len(self.frames) + 1}/{len(self.frames)}  ",
                                   reg.get(15, 0))
            except curses.error:
                pass

            self.stdscr.noutrefresh()
            curses.doupdate()

            key = self.stdscr.getch()
            if key != -1:
                break
            fidx += 1

        self.stdscr.timeout(-1)
        self._msg("Animation stopped")

    # ── Input ────────────────────────────────────────────────────

    def _handle_input(self):
        self.stdscr.timeout(-1)
        key = self.stdscr.getch()

        if key == -1:
            return True

        # Quit
        if key in (ord("q"), ord("Q"), 27):  # q, Q, Esc
            if self.dirty:
                self._msg("Unsaved changes! Press Q again to quit, S to save")
                self._draw()
                k2 = self.stdscr.getch()
                if k2 in (ord("q"), ord("Q")):
                    return False
                if k2 in (ord("s"), ord("S"), 19):  # Ctrl+S = 19
                    self._prompt_save()
                return True
            return False

        # Movement (arrow keys only — a-f reserved for hex color select)
        if key == curses.KEY_UP:
            self.cy = max(0, self.cy - 1)
        elif key == curses.KEY_DOWN:
            self.cy = min(self.ph - 1, self.cy + 1)
        elif key == curses.KEY_LEFT:
            self.cx = max(0, self.cx - 1)
        elif key == curses.KEY_RIGHT:
            self.cx = min(self.pw - 1, self.cx + 1)

        # Fast movement (shift+arrow or pgup/pgdn)
        elif key == curses.KEY_PPAGE:
            self.cy = max(0, self.cy - 10)
        elif key == curses.KEY_NPAGE:
            self.cy = min(self.ph - 1, self.cy + 10)
        elif key == curses.KEY_HOME:
            self.cx = 0
        elif key == curses.KEY_END:
            self.cx = self.pw - 1

        # Paint
        elif key in (ord(" "), 10, 13):  # space, enter
            self._paint(self.cx, self.cy, self.color)

        # Erase
        elif key in (ord("x"), curses.KEY_DC, 127):
            self._erase(self.cx, self.cy)

        # Color select (0-9, a-f)
        elif ord("0") <= key <= ord("9"):
            self.color = key - ord("0")
            self._msg(f"Color {self.color}: {PALETTE_NAMES.get(self.color, '?')}")
        elif ord("a") <= key <= ord("f"):
            self.color = 10 + (key - ord("a"))
            self._msg(f"Color {self.color}: {PALETTE_NAMES.get(self.color, '?')}")

        # Eyedropper (i = inspect)
        elif key in (ord("i"), ord("I")):
            self._eyedrop(self.cx, self.cy)

        # Flood fill (shift+F only — lowercase f = color 0xf)
        elif key == ord("F"):
            self._flood_fill(self.cx, self.cy, self.color)

        # Grid toggle
        elif key in (ord("g"), ord("G")):
            self.grid_on = not self.grid_on
            self._msg(f"Grid {'on' if self.grid_on else 'off'}")

        # Mirror toggle
        elif key in (ord("m"),):
            self.mirror = not self.mirror
            self._msg(f"Mirror {'on' if self.mirror else 'off'}")

        # Preview toggle
        elif key in (ord("p"), ord("P")):
            self.preview_on = not self.preview_on

        # Undo / Redo
        elif key in (ord("u"), ord("U"), 26):  # u, U, Ctrl+Z
            self._undo()
        elif key in (ord("r"),):
            self._redo()

        # Frames
        elif key == ord("]"):
            self._next_frame()
        elif key == ord("["):
            self._prev_frame()
        elif key == ord("n"):
            self._new_frame()
        elif key == ord("N"):
            self._delete_frame()

        # Resize
        elif key == ord("+") or key == ord("="):
            self._resize(2, 2)
        elif key == ord("-") or key == ord("_"):
            self._resize(-2, -2)

        # Animation preview
        elif key in (ord("t"), ord("T")):
            self._play_animation()

        # Save
        elif key in (ord("S"), 19):  # S, Ctrl+S
            self._prompt_save()

        # Load
        elif key == ord("l") or key == ord("L"):
            self._prompt_load()

        # Set anchor at cursor
        elif key == ord("!"):
            self.anchor_x = self.cx
            self.anchor_y = self.cy
            self._msg(f"Anchor set: ({self.anchor_x},{self.anchor_y})")

        # Mouse
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                # Convert screen coords to pixel coords
                if my >= 1:  # skip header
                    px = (mx + self.scroll_x) // 2
                    py = (my - 1) + self.scroll_y
                    if 0 <= px < self.pw and 0 <= py < self.ph:
                        self.cx, self.cy = px, py
                        if bstate & curses.BUTTON1_PRESSED or bstate & curses.BUTTON1_CLICKED:
                            self._paint(px, py, self.color)
                        elif bstate & curses.BUTTON3_PRESSED or bstate & curses.BUTTON3_CLICKED:
                            self._erase(px, py)
            except curses.error:
                pass

        return True

    def _prompt_load(self):
        """List sprite files and let user pick one."""
        sprite_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")
        if not os.path.isdir(sprite_dir):
            self._msg("No sprites/ directory found")
            return

        files = sorted(f for f in os.listdir(sprite_dir) if f.endswith(".json"))
        if not files:
            self._msg("No sprite files found")
            return

        # Simple selection
        self._msg(f"Files: {', '.join(files[:10])}...")
        self._draw()

        curses.echo()
        curses.curs_set(1)
        h, w = self.stdscr.getmaxyx()
        self.stdscr.addstr(h - 1, 0, " Load file: " + " " * 40)
        self.stdscr.move(h - 1, 12)
        try:
            name = self.stdscr.getstr(h - 1, 12, 60).decode("utf-8").strip()
        except Exception:
            name = ""
        curses.noecho()
        curses.curs_set(0)

        if not name:
            self._msg("Load cancelled")
            return
        if not name.endswith(".json"):
            name += ".json"
        path = os.path.join(sprite_dir, name)
        if os.path.exists(path):
            self._load(path)
        else:
            self._msg(f"Not found: {name}")

    # ── Main Loop ────────────────────────────────────────────────

    def run(self):
        while True:
            self._draw()
            if not self._handle_input():
                break


def main(stdscr):
    # Parse args
    filepath = None
    width, height = 30, 40  # default: good size for mermaid sprite

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--new" and i + 1 < len(args):
            try:
                w_str, h_str = args[i + 1].split("x")
                width, height = int(w_str), int(h_str)
            except ValueError:
                pass
            i += 2
        else:
            filepath = args[i]
            i += 1

    editor = SpriteEditor(stdscr, filepath=filepath, width=width, height=height)
    editor.run()


if __name__ == "__main__":
    curses.wrapper(main)
