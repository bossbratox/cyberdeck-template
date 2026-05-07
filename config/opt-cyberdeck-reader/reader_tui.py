#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-reader/reader_tui.py on Pi
#
# Curses-based file browser and reader for the cyberdeck Obsidian vault.
# Reads local ~/Vault (synced from Nextcloud via vault_sync.sh on wifi connect).
# Pure stdlib — no venv needed.

import curses
import os
import select
import subprocess
import sys
import threading
from datetime import datetime

from cyberdeck_colors import (
    init_colors, CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM,
    CP_DIVIDER, CP_REASONING, CP_SELECTED_BG, CP_BLUE,
)
import cyberdeck_touch

_DBG = open("/tmp/reader-exit.log", "a")
def _log(msg):
    _DBG.write(msg + "\n")
    _DBG.flush()

sys.path.insert(0, "/opt/cyberdeck-shell")
try:
    from cyberdeck_switch import switch_to
except Exception:
    def switch_to(app_name):
        return False

VAULT_ROOT = os.path.expanduser("~/Vault")
CURRENT_APP = "reader"

# Escape sequences for F-keys (full sequences including ESC byte)
_ESC_SEQ_MAP = {
    # VT100 style
    b"\x1bOP": "F1", b"\x1bOQ": "F2", b"\x1bOR": "F3", b"\x1bOS": "F4",
    # Linux console / fbterm style
    b"\x1b[[A": "F1", b"\x1b[[B": "F2", b"\x1b[[C": "F3",
    b"\x1b[[D": "F4", b"\x1b[[E": "F5",
    # xterm style
    b"\x1b[11~": "F1", b"\x1b[12~": "F2", b"\x1b[13~": "F3",
    b"\x1b[14~": "F4", b"\x1b[15~": "F5", b"\x1b[17~": "F6",
    b"\x1b[18~": "F7",
    # arrows / other
    b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT",
    b"\x1b[D": "LEFT", b"\x1b[5~": "PGUP", b"\x1b[6~": "PGDN",
    b"\x1b[3~": "DEL",
}


def _read_esc_seq_raw():
    """Read the bytes after the leading ESC of an escape sequence.

    Returns bytes without the leading ESC. Recognizes SS3 (\\x1bO?),
    CSI (\\x1b[...<final>), and Linux console (\\x1b[[?). Bare ESC → b"".
    """
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], 0.05)[0]:
        return b""
    first = os.read(fd, 1)
    if not first:
        return b""
    if first == b"O":
        if select.select([fd], [], [], 0.05)[0]:
            nxt = os.read(fd, 1)
            if nxt:
                return first + nxt
        return first
    if first != b"[":
        return first
    buf = first
    for i in range(16):
        if not select.select([fd], [], [], 0.05)[0]:
            break
        ch = os.read(fd, 1)
        if not ch:
            break
        buf += ch
        if i == 0 and ch == b"[":
            if select.select([fd], [], [], 0.05)[0]:
                tail = os.read(fd, 1)
                if tail:
                    buf += tail
            return buf
        if 0x40 <= ch[0] <= 0x7E:
            break
    return buf


def _handle_fkey(key):
    """Switch to the app mapped to an F-key.

    Returns True only if the switch targets a *different* app — this
    prevents spurious escape sequences that get mapped to F-keys from
    exiting the current TUI.
    """
    mapping = {
        "F1": "term", "F2": "chat", "F3": "pet",
        "F4": "reader", "F5": "dash", "F6": "wifi", "F7": "bt",
    }
    app = mapping.get(key)
    if app:
        switch_to(app)
        return CURRENT_APP != app
    return False


class ReaderApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.lock = threading.Lock()
        self.touch_active = False
        self.mouse_active = False
        self.should_quit = False
        self.term_w = 80  # cached width, updated by draw()

        # Mode: "browser" or "reader"
        self.mode = "browser"

        # Browser state
        self.current_dir = VAULT_ROOT
        self.file_list = []       # [(name, is_dir, full_path), ...]
        self.file_cursor = 0
        self.file_offset = 0
        self.browser_status = ""  # error/loading message
        self.all_files = []       # cached all .md/.pdf paths

        # Reader state
        self.content_path = ""
        self.content_title = ""
        self.display_lines = []   # list of [(text, color, attr, link_target), ...]
        self.reader_offset = 0
        self.cursor_y = 0
        self.back_stack = []      # [(path, offset, cursor_y), ...]

        # Search
        self.search_active = False
        self.search_buf = ""
        self.search_results = []
        self.search_idx = 0

        # New file prompt
        self.newfile_active = False
        self.newfile_buf = ""

        # Inline editor state
        self.edit_active = False
        self.edit_path = ""
        self.edit_lines = [""]   # list[str], one entry per line
        self.edit_row = 0        # cursor line index (absolute)
        self.edit_col = 0        # cursor column in current line
        self.edit_offset = 0     # top line displayed
        self.edit_dirty = False
        self.edit_status = ""    # transient status message

        # Bookmarks
        self.bookmark_dir = os.path.expanduser(
            "~/.local/share/cyberdeck-reader/bookmarks"
        )
        self.persist_bookmark_dir = "/boot/firmware/persistent/reader-bookmarks"

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.timeout(50)  # smoother trackpad scroll redraws
        init_colors()

        self._load_all_files()
        self._refresh_dir()

        def _on_scroll(delta):
            _log(f"SCROLL: mode={self.mode} delta={delta} edit={self.edit_active}")
            with self.lock:
                if self.edit_active:
                    return  # _on_delta handles edit-mode movement
                if self.mode == "browser":
                    if delta > 0:
                        self.file_cursor = min(
                            max(0, len(self.file_list) - 1),
                            self.file_cursor + delta,
                        )
                    else:
                        self.file_cursor = max(0, self.file_cursor + delta)
                else:
                    self.cursor_y += delta

        def _on_delta(dx, dy):
            with self.lock:
                if self.edit_active:
                    self._edit_move_cursor(dx, dy)

        def _on_tap():
            with self.lock:
                if self.search_active:
                    self._execute_search()
                    self.search_active = False
                elif self.mode == "browser":
                    self._open_selected()
                else:
                    self._follow_link()

        # Touch handlers. Touchscreen is 640x480 px.
        # Swipe -> scroll. Tap zones:
        #   * top-left  (x<100, y<80)           -> back / up-dir
        #   * bottom-right (x>480, y>400)        -> edit selected/current file
        #   * bottom-center (160<x<480, y>400)   -> new file (browser only)
        #   * search active                      -> execute search
        #   * browser, tap on file row           -> jump cursor + open
        #   * reader, left half  (x<=320)        -> page up
        #   * reader, right half (x>320)         -> page down
        def _touch_tap_xy(x, y):
            _log(f"TOUCH_XY x={x} y={y} edit={self.edit_active} mode={self.mode}")
            with self.lock:
                if self.newfile_active:
                    self._create_new_file()
                    return
                if self.search_active:
                    self._execute_search()
                    self.search_active = False
                    return
                # Edit mode: tap-to-position cursor (top-left = save+exit)
                if self.edit_active:
                    if x < 100 and y < 80:
                        self._exit_edit(save=self.edit_dirty)
                        return
                    h = max(1, getattr(self, "term_h", 24))
                    w = max(1, self.term_w)
                    cell_h = 480.0 / h
                    cell_w = 640.0 / w
                    target_row_screen = int(y / cell_h)
                    if 2 <= target_row_screen <= h - 3:
                        line_idx = self.edit_offset + (target_row_screen - 2)
                        if 0 <= line_idx < len(self.edit_lines):
                            self.edit_row = line_idx
                            col_in_line = int(x / cell_w)
                            self.edit_col = min(col_in_line, len(self.edit_lines[line_idx]))
                    return
                # Bottom-right corner: edit
                if x > 480 and y > 400:
                    if self.mode == "browser" and self.file_list:
                        name, is_dir, path = self.file_list[self.file_cursor]
                        if not is_dir and path.endswith(".md"):
                            self._edit_file(path)
                    elif self.mode == "reader" and self.content_path.endswith(".md"):
                        self._edit_file(self.content_path)
                    return
                # Bottom-center: new file (browser only)
                if 160 < x < 480 and y > 400 and self.mode == "browser":
                    self.newfile_active = True
                    self.newfile_buf = ""
                    return
                if x < 100 and y < 80:
                    if self.mode == "reader":
                        self._go_back()
                    else:
                        self._go_up_dir()
                    return
                if self.mode == "browser":
                    h, _w = self.stdscr.getmaxyx()
                    if h > 0:
                        row = int(y * h / 480)
                        if 2 <= row <= h - 3 and self.file_list:
                            idx = self.file_offset + (row - 2)
                            if 0 <= idx < len(self.file_list):
                                self.file_cursor = idx
                                self._open_selected()
                                return
                    self._open_selected()
                else:
                    page = self._content_height()
                    if x > 320:
                        max_off = max(0, len(self.display_lines) - page)
                        self.reader_offset = min(max_off, self.reader_offset + page)
                    else:
                        self.reader_offset = max(0, self.reader_offset - page)
                    self.cursor_y = 0

        self.touch_active = cyberdeck_touch.start_touch_listener(
            _on_scroll, lambda: None, on_tap_xy=_touch_tap_xy
        )
        self.mouse_active = cyberdeck_touch.start_mouse_listener(
            _on_scroll, on_tap=_on_tap, on_delta=_on_delta
        )
        _log(f"LISTENERS touch_active={self.touch_active} mouse_active={self.mouse_active}")

        while not self.should_quit:
            self.draw()
            try:
                ch = self.stdscr.get_wch()
                _log(f"KEY: {repr(ch)} type={type(ch).__name__}")
            except curses.error:
                continue
            if ch == '\x03' or ch == '\x11':
                break
            # F-keys and escape sequences
            # Guard: only exit the loop if switching to a *different* app.
            # Spurious F-key keycodes can be injected by fbterm escape
            # sequences (e.g. trackpad scroll misidentified as KEY_F4).
            if ch == curses.KEY_F1:
                _log("F1->term"); switch_to("term")
                if CURRENT_APP != "term":
                    break
                continue
            elif ch == curses.KEY_F2:
                _log("F2->chat"); switch_to("chat")
                if CURRENT_APP != "chat":
                    break
                continue
            elif ch == curses.KEY_F3:
                _log("F3->pet"); switch_to("pet")
                if CURRENT_APP != "pet":
                    break
                continue
            elif ch == curses.KEY_F4:
                _log("F4->reader"); switch_to("reader")
                if CURRENT_APP != "reader":
                    break
                continue
            elif ch == curses.KEY_F5:
                _log("F5->dash"); switch_to("dash")
                if CURRENT_APP != "dash":
                    break
                continue
            elif ch == curses.KEY_F6:
                _log("F6->wifi"); switch_to("wifi")
                if CURRENT_APP != "wifi":
                    break
                continue
            elif ch == curses.KEY_F7:
                _log("F7->bt"); switch_to("bt")
                if CURRENT_APP != "bt":
                    break
                continue
            elif ch in (27, '\x1b'):
                try:
                    rest = _read_esc_seq_raw()
                except Exception:
                    rest = b""
                if not rest:
                    with self.lock:
                        if self.edit_active:
                            self._exit_edit(save=self.edit_dirty)
                        elif self.newfile_active:
                            self.newfile_active = False
                            self.newfile_buf = ""
                        elif self.search_active:
                            self.search_active = False
                            self.search_buf = ""
                            self.search_results = []
                        elif self.mode == "reader":
                            self._go_back()
                        else:
                            self._go_up_dir()
                        if self.should_quit:
                            break
                    continue
                seq = b"\x1b" + rest
                key = _ESC_SEQ_MAP.get(seq)
                if _handle_fkey(key):
                    break
                if key == "UP":
                    with self.lock:
                        if self.mode == "browser":
                            self.file_cursor = max(0, self.file_cursor - 1)
                        else:
                            self.cursor_y -= 1
                    continue
                elif key == "DOWN":
                    with self.lock:
                        if self.mode == "browser":
                            self.file_cursor = min(max(0, len(self.file_list) - 1),
                                                   self.file_cursor + 1)
                        else:
                            self.cursor_y += 1
                    continue
                elif key == "PGUP":
                    with self.lock:
                        if self.mode == "browser":
                            self.file_cursor = max(0, self.file_cursor - 5)
                        else:
                            h = self._content_height()
                            self.reader_offset = max(0, self.reader_offset - h)
                            self.cursor_y = 0
                    continue
                elif key == "PGDN":
                    with self.lock:
                        if self.mode == "browser":
                            self.file_cursor = min(max(0, len(self.file_list) - 1),
                                                   self.file_cursor + 5)
                        else:
                            h = self._content_height()
                            max_off = max(0, len(self.display_lines) - h)
                            self.reader_offset = min(max_off, self.reader_offset + h)
                            self.cursor_y = 0
                    continue
                continue
            with self.lock:
                self._handle_input(ch)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def _handle_input(self, ch):
        if self.edit_active:
            self._handle_edit_input(ch)
            return
        if self.newfile_active:
            self._handle_newfile_input(ch)
            return
        if self.search_active:
            self._handle_search_input(ch)
            return
        if self.mode == "browser":
            self._handle_browser_input(ch)
        else:
            self._handle_reader_input(ch)

    def _handle_browser_input(self, ch):
        if ch in ('q', 'Q'):
            _log("QUIT: q/Q"); self.should_quit = True
        elif ch == '/':
            self.search_active = True
            self.search_buf = ""
        elif ch in ('n', 'N'):
            self.newfile_active = True
            self.newfile_buf = ""
        elif ch in ('e', 'E'):
            if self.file_list:
                name, is_dir, path = self.file_list[self.file_cursor]
                if not is_dir and path.endswith(".md"):
                    self._edit_file(path)
        elif ch == curses.KEY_UP:
            self.file_cursor = max(0, self.file_cursor - 1)
        elif ch == curses.KEY_DOWN:
            self.file_cursor = min(max(0, len(self.file_list) - 1),
                                   self.file_cursor + 1)
        elif ch == curses.KEY_PPAGE:
            self.file_cursor = max(0, self.file_cursor - 5)
        elif ch == curses.KEY_NPAGE:
            self.file_cursor = min(max(0, len(self.file_list) - 1),
                                   self.file_cursor + 5)
        elif ch in ('\n', '\r', curses.KEY_ENTER):
            self._open_selected()
        elif ch in (27, '\x1b') or ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
            self._go_up_dir()

    def _handle_reader_input(self, ch):
        if ch in ('q', 'Q'):
            self._save_bookmark()
            self.mode = "browser"
        elif ch == '/':
            self.search_active = True
            self.search_buf = ""
        elif ch in ('e', 'E'):
            if self.content_path and self.content_path.endswith(".md"):
                self._edit_file(self.content_path)
        elif ch == curses.KEY_UP:
            self.cursor_y -= 1
        elif ch == curses.KEY_DOWN:
            self.cursor_y += 1
        elif ch == curses.KEY_PPAGE:
            h = self._content_height()
            self.reader_offset = max(0, self.reader_offset - h)
            self.cursor_y = 0
        elif ch == curses.KEY_NPAGE:
            h = self._content_height()
            max_off = max(0, len(self.display_lines) - h)
            self.reader_offset = min(max_off, self.reader_offset + h)
            self.cursor_y = 0
        elif ch in ('\n', '\r', curses.KEY_ENTER):
            self._follow_link()
        elif ch in (27, '\x1b') or ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
            self._go_back()

    def _handle_search_input(self, ch):
        if ch == '\x1b':
            self.search_active = False
            self.search_buf = ""
            self.search_results = []
        elif ch in ('\n', '\r', curses.KEY_ENTER):
            self._execute_search()
            self.search_active = False
        elif ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
            self.search_buf = self.search_buf[:-1]
        elif isinstance(ch, str) and len(ch) == 1 and ch.isprintable():
            self.search_buf += ch

    def _handle_newfile_input(self, ch):
        if ch == '\x1b':
            self.newfile_active = False
            self.newfile_buf = ""
        elif ch in ('\n', '\r', curses.KEY_ENTER):
            self._create_new_file()
        elif ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
            self.newfile_buf = self.newfile_buf[:-1]
        elif isinstance(ch, str) and len(ch) == 1 and ch.isprintable():
            self.newfile_buf += ch

    def _execute_search(self):
        if self.mode == "browser":
            for i, (name, _is_dir, _path) in enumerate(self.file_list):
                if self.search_buf.lower() in name.lower():
                    self.file_cursor = i
                    break
        else:
            self.search_results = []
            for i, line in enumerate(self.display_lines):
                text = "".join(seg[0] for seg in line)
                if self.search_buf.lower() in text.lower():
                    self.search_results.append(i)
            if self.search_results:
                h = self._content_height()
                self.reader_offset = max(
                    0, self.search_results[0] - h // 2
                )
                self.cursor_y = self.search_results[0] - self.reader_offset

    # ------------------------------------------------------------------
    # Data loading (local filesystem)
    # ------------------------------------------------------------------
    def _load_all_files(self):
        files = []
        try:
            for dirpath, dirnames, filenames in os.walk(VAULT_ROOT):
                # Skip hidden dirs (.obsidian, .trash, etc.)
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in sorted(filenames):
                    if fname.endswith(".md") or fname.endswith(".pdf"):
                        files.append(os.path.join(dirpath, fname))
            self.all_files = sorted(files)
        except OSError as e:
            self.all_files = []
            self.browser_status = f"vault err: {e.strerror}"

    def _refresh_dir(self):
        try:
            entries = sorted(os.listdir(self.current_dir))
        except OSError as e:
            self.file_list = []
            self.browser_status = f"err: {e.strerror}"
            return

        items = []
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(self.current_dir, name)
            is_dir = os.path.isdir(full)
            if is_dir or name.endswith(".md") or name.endswith(".pdf"):
                items.append((name, is_dir, full))

        if self.current_dir != VAULT_ROOT:
            parent = os.path.dirname(self.current_dir)
            items.insert(0, ("..", True, parent))

        self.file_list = items
        self.file_cursor = 0
        self.file_offset = 0
        self.browser_status = ""

    def _reload_browser(self):
        self._refresh_dir()
        self.draw()

    def _open_selected(self):
        if not self.file_list:
            return
        name, is_dir, path = self.file_list[self.file_cursor]
        if is_dir:
            self.current_dir = path
            self._refresh_dir()
        else:
            self._open_file(path)

    def _go_up_dir(self):
        if self.current_dir != VAULT_ROOT:
            self.current_dir = os.path.dirname(self.current_dir)
            self._refresh_dir()
        else:
            self.should_quit = True

    def _read_file_local(self, path):
        """Read file content, returns (text, is_markdown)."""
        if path.endswith(".pdf"):
            # Cache extracted text next to the PDF as a dotfile so
            # vault-sync's `.*` exclude skips it. Big OCR'd PDFs take
            # >100s on the Pi — caching makes second opens instant.
            d, base = os.path.split(path)
            cache = os.path.join(d, "." + base + ".txt")
            try:
                if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
                    with open(cache, "r", encoding="utf-8", errors="replace") as f:
                        return f.read(), False
            except OSError:
                pass
            try:
                result = subprocess.run(
                    ["pdftotext", path, "-"],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    return f"[PDF error: rc={result.returncode}]", False
                raw = result.stdout.replace("\f", "\n")
                try:
                    with open(cache, "w", encoding="utf-8") as f:
                        f.write(raw)
                except OSError:
                    pass
                return raw, False
            except Exception as e:
                return f"[PDF error: {e}]", False
        else:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read(), True
            except OSError as e:
                return f"[Error: {e.strerror}]", True

    def _open_file(self, path):
        self._save_bookmark()
        self.back_stack.append((self.content_path, self.reader_offset,
                                self.cursor_y))
        self.content_path = path
        self.content_title = os.path.basename(path)

        raw, is_markdown = self._read_file_local(path)
        self._render_text(raw, is_markdown=is_markdown)

        self.mode = "reader"
        self.reader_offset = 0
        self.cursor_y = 0
        saved = self._load_bookmark(path)
        if saved is not None:
            self.reader_offset = saved

    def _go_back(self):
        self._save_bookmark()
        if self.back_stack:
            path, offset, cursor_y = self.back_stack.pop()
            if path:
                self.content_path = path
                self.content_title = os.path.basename(path)
                raw, is_markdown = self._read_file_local(path)
                self._render_text(raw, is_markdown=is_markdown)
                self.mode = "reader"
                self.reader_offset = offset
                self.cursor_y = cursor_y
            else:
                self.mode = "browser"
        else:
            self.mode = "browser"

    def _follow_link(self):
        abs_line = self.reader_offset + self.cursor_y
        if 0 <= abs_line < len(self.display_lines):
            for _text, _color, _attr, link in self.display_lines[abs_line]:
                if link:
                    self._resolve_wikilink(link)
                    return

    def _resolve_wikilink(self, target):
        target_norm = target.lower()
        candidates = []
        for f in self.all_files:
            base = os.path.basename(f)
            no_ext = os.path.splitext(base)[0].lower()
            if no_ext == target_norm:
                candidates.append((0, f))
            elif target_norm in no_ext:
                candidates.append((1, f))
            elif no_ext in target_norm:
                candidates.append((2, f))
        if candidates:
            candidates.sort()
            self._open_file(candidates[0][1])

    # ------------------------------------------------------------------
    # Edit / create
    # ------------------------------------------------------------------
    def _edit_file(self, path):
        """Enter inline curses editor for path. Stays in reader's curses context."""
        _log(f"EDIT: {path}")
        self._save_bookmark()
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            self.browser_status = f"open err: {e.strerror}"
            return
        # Strip trailing \n so we don't get phantom blank line, then split
        if content.endswith("\n"):
            content = content[:-1]
        self.edit_lines = content.split("\n") if content else [""]
        self.edit_path = path
        self.edit_row = 0
        self.edit_col = 0
        self.edit_offset = 0
        self.edit_dirty = False
        self.edit_status = "Ctrl-S save  Esc/Ctrl-X exit  F-keys switch app"
        self.edit_active = True
        try:
            curses.curs_set(1)  # show cursor
        except curses.error:
            pass

    def _exit_edit(self, save=False):
        was_dirty = self.edit_dirty
        if save:
            self._save_edit_file()
        self.edit_active = False
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        # Reload if currently viewing this file
        if self.mode == "reader" and self.content_path == self.edit_path:
            raw, is_md = self._read_file_local(self.edit_path)
            self._render_text(raw, is_markdown=is_md)
        else:
            self._refresh_dir()
            self._load_all_files()
        # If user actually saved changes, push to nextcloud in background.
        # Fire-and-forget — vault-sync exits silently if nextcloud unreachable.
        if save and was_dirty:
            self._trigger_vault_sync()
        _log("EDIT done")

    def _trigger_vault_sync(self):
        """Fully detached background vault-sync — survives reader process exit.
        Must NOT be a daemon thread (those die when reader exits, killing sync
        mid-flight). Spawn as new session leader via setsid so it outlives us.
        """
        try:
            log_fd = open("/tmp/vault-sync.log", "a")
            subprocess.Popen(
                ["/usr/local/bin/vault-sync"],
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # decouple from reader's process group
                close_fds=True,
            )
            _log("vault-sync detached")
        except Exception as e:
            _log(f"vault-sync trigger err: {e!r}")

    def _edit_move_cursor(self, dx, dy):
        """Move text cursor by (dx, dy) cells. Called from trackpad on_delta."""
        if not self.edit_lines:
            return
        if dy:
            self.edit_row = max(0, min(len(self.edit_lines) - 1, self.edit_row + dy))
        if dx:
            self.edit_col = max(0, self.edit_col + dx)
        # Clamp col to current line length
        self.edit_col = min(self.edit_col, len(self.edit_lines[self.edit_row]))

    def _save_edit_file(self):
        try:
            with open(self.edit_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.edit_lines))
                f.write("\n")
            self.edit_dirty = False
            self.edit_status = f"saved {os.path.basename(self.edit_path)}"
        except OSError as e:
            self.edit_status = f"save err: {e.strerror}"

    def _handle_edit_input(self, ch):
        # Ctrl-S = save (chr 19)
        if ch == '\x13' or ch == 19:
            self._save_edit_file()
            return
        # Ctrl-X = save and exit (chr 24)
        if ch == '\x18' or ch == 24:
            self._exit_edit(save=self.edit_dirty)
            return
        # ESC = exit (with implicit save if dirty)
        if ch in (27, '\x1b'):
            self._exit_edit(save=self.edit_dirty)
            return
        # Backspace
        if ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
            if self.edit_col > 0:
                line = self.edit_lines[self.edit_row]
                self.edit_lines[self.edit_row] = line[:self.edit_col-1] + line[self.edit_col:]
                self.edit_col -= 1
                self.edit_dirty = True
            elif self.edit_row > 0:
                # merge with previous line
                prev = self.edit_lines[self.edit_row - 1]
                cur = self.edit_lines[self.edit_row]
                self.edit_col = len(prev)
                self.edit_lines[self.edit_row - 1] = prev + cur
                del self.edit_lines[self.edit_row]
                self.edit_row -= 1
                self.edit_dirty = True
            return
        # Enter = newline
        if ch in ('\n', '\r', curses.KEY_ENTER, 10, 13):
            line = self.edit_lines[self.edit_row]
            self.edit_lines[self.edit_row] = line[:self.edit_col]
            self.edit_lines.insert(self.edit_row + 1, line[self.edit_col:])
            self.edit_row += 1
            self.edit_col = 0
            self.edit_dirty = True
            return
        # Arrows
        if ch == curses.KEY_UP:
            if self.edit_row > 0:
                self.edit_row -= 1
                self.edit_col = min(self.edit_col, len(self.edit_lines[self.edit_row]))
            return
        if ch == curses.KEY_DOWN:
            if self.edit_row < len(self.edit_lines) - 1:
                self.edit_row += 1
                self.edit_col = min(self.edit_col, len(self.edit_lines[self.edit_row]))
            return
        if ch == curses.KEY_LEFT:
            if self.edit_col > 0:
                self.edit_col -= 1
            elif self.edit_row > 0:
                self.edit_row -= 1
                self.edit_col = len(self.edit_lines[self.edit_row])
            return
        if ch == curses.KEY_RIGHT:
            if self.edit_col < len(self.edit_lines[self.edit_row]):
                self.edit_col += 1
            elif self.edit_row < len(self.edit_lines) - 1:
                self.edit_row += 1
                self.edit_col = 0
            return
        if ch == curses.KEY_PPAGE:
            self.edit_row = max(0, self.edit_row - 10)
            self.edit_col = min(self.edit_col, len(self.edit_lines[self.edit_row]))
            return
        if ch == curses.KEY_NPAGE:
            self.edit_row = min(len(self.edit_lines) - 1, self.edit_row + 10)
            self.edit_col = min(self.edit_col, len(self.edit_lines[self.edit_row]))
            return
        if ch == curses.KEY_HOME:
            self.edit_col = 0
            return
        if ch == curses.KEY_END:
            self.edit_col = len(self.edit_lines[self.edit_row])
            return
        # Regular printable char
        if isinstance(ch, str) and len(ch) == 1 and (ch.isprintable() or ch == '\t'):
            line = self.edit_lines[self.edit_row]
            insert = '    ' if ch == '\t' else ch
            self.edit_lines[self.edit_row] = line[:self.edit_col] + insert + line[self.edit_col:]
            self.edit_col += len(insert)
            self.edit_dirty = True

    def _draw_edit(self, h, w):
        # Header
        dirty_mark = "*" if self.edit_dirty else " "
        title = f"edit{dirty_mark} {os.path.basename(self.edit_path)}"
        self.stdscr.addnstr(
            0, 0, title[:w - 1], w - 1,
            curses.color_pair(CP_PINK_HEADER) | curses.A_BOLD,
        )
        self.stdscr.addnstr(
            1, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )

        content_h = max(1, h - 4)
        # Adjust scroll offset to keep cursor visible
        if self.edit_row < self.edit_offset:
            self.edit_offset = self.edit_row
        elif self.edit_row >= self.edit_offset + content_h:
            self.edit_offset = self.edit_row - content_h + 1

        # Draw lines
        for i in range(content_h):
            row = 2 + i
            line_idx = self.edit_offset + i
            if line_idx >= len(self.edit_lines):
                break
            line = self.edit_lines[line_idx]
            # truncate to width
            try:
                self.stdscr.addnstr(row, 0, line[:w - 1], w - 1,
                                    curses.color_pair(CP_WHITE))
            except curses.error:
                pass

        # Footer
        self.stdscr.addnstr(
            h - 2, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )
        footer = self.edit_status or "Ctrl-S save  Esc/Ctrl-X exit"
        self.stdscr.addnstr(
            h - 1, 0, footer[:w - 1], w - 1,
            curses.color_pair(CP_DIVIDER),
        )

        # Place cursor (clamp to visible area)
        cy = 2 + (self.edit_row - self.edit_offset)
        cx = min(self.edit_col, w - 1)
        if 2 <= cy < h - 2:
            try:
                self.stdscr.move(cy, cx)
            except curses.error:
                pass

    def _create_new_file(self):
        self.newfile_active = False
        name = self.newfile_buf.strip()
        self.newfile_buf = ""
        if not name:
            return
        if not name.endswith(".md"):
            name += ".md"
        path = os.path.join(self.current_dir, name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    f.write(f"# {os.path.splitext(name)[0]}\n\n")
        except OSError as e:
            self.browser_status = f"create err: {e.strerror}"
            return
        self._edit_file(path)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _content_height(self):
        return max(1, getattr(self, "term_h", 24) - 4)

    def _render_text(self, text, is_markdown=True):
        content_w = max(1, self.term_w)
        lines = text.split("\n")
        self.display_lines = []
        in_code = False

        for line in lines:
            if not is_markdown:
                wrapped = self._wrap_line([(line, CP_WHITE, 0, None)], content_w)
                self.display_lines.extend(wrapped)
                continue

            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if stripped.startswith("```"):
                in_code = not in_code
                self.display_lines.append(
                    [(" " * min(indent, 2) + stripped, CP_DIM, 0, None)]
                )
                continue

            if in_code:
                self.display_lines.append([(line, CP_DIM, 0, None)])
                continue

            if stripped.startswith("# "):
                seg = (stripped[2:], CP_PINK_HEADER, curses.A_BOLD, None)
                self.display_lines.extend(self._wrap_line([seg], content_w))
            elif stripped.startswith("## "):
                seg = (stripped[3:], CP_PINK_HEADER, curses.A_BOLD, None)
                self.display_lines.extend(self._wrap_line([seg], content_w))
            elif stripped.startswith("### "):
                seg = (stripped[4:], CP_PINK_HEADER, curses.A_BOLD, None)
                self.display_lines.extend(self._wrap_line([seg], content_w))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                seg = ("  • " + stripped[2:], CP_WHITE, 0, None)
                self.display_lines.extend(self._wrap_line([seg], content_w))
            else:
                segments = self._parse_inline(stripped)
                if indent >= 4:
                    segments = [
                        (seg[0], CP_DIM, seg[2], seg[3]) for seg in segments
                    ]
                self.display_lines.extend(
                    self._wrap_line(segments, content_w)
                )

    def _parse_inline(self, text):
        segments = []
        i = 0
        while i < len(text):
            if text[i:i + 2] == "[[":
                j = text.find("]]", i + 2)
                if j != -1:
                    if i > 0:
                        segments.append((text[:i], CP_WHITE, 0, None))
                    target = text[i + 2:j]
                    segments.append(
                        (text[i:j + 2], CP_BLUE, 0, target)
                    )
                    text = text[j + 2:]
                    i = 0
                    continue
            if text[i:i + 2] == "**":
                j = text.find("**", i + 2)
                if j != -1:
                    if i > 0:
                        segments.append((text[:i], CP_WHITE, 0, None))
                    segments.append(
                        (text[i + 2:j], CP_WHITE, curses.A_BOLD, None)
                    )
                    text = text[j + 2:]
                    i = 0
                    continue
            i += 1
        if text:
            segments.append((text, CP_WHITE, 0, None))
        return segments

    def _wrap_line(self, segments, width):
        if width <= 0:
            return [[]]
        words = []
        for text, color, attr, link in segments:
            parts = text.split(" ")
            for pi, part in enumerate(parts):
                if pi > 0:
                    words.append((" ", color, attr, link))
                if part:
                    words.append((part, color, attr, link))
        lines = []
        current = []
        cur_len = 0
        for word, color, attr, link in words:
            wlen = len(word)
            if cur_len + wlen <= width:
                current.append((word, color, attr, link))
                cur_len += wlen
            else:
                if current:
                    lines.append(current)
                    current = []
                    cur_len = 0
                if wlen > width:
                    i = 0
                    while i < wlen:
                        chunk = word[i:i + width]
                        current.append((chunk, color, attr, link))
                        cur_len = len(chunk)
                        if cur_len >= width:
                            lines.append(current)
                            current = []
                            cur_len = 0
                        i += width
                else:
                    current.append((word, color, attr, link))
                    cur_len = wlen
        if current:
            lines.append(current)
        return lines if lines else [[]]

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------
    def _bookmark_key(self, path):
        return path.replace("/", "_").replace("~", "HOME")

    def _save_bookmark(self):
        if not self.content_path:
            return
        key = self._bookmark_key(self.content_path)
        data = str(self.reader_offset)
        for base in (self.bookmark_dir, self.persist_bookmark_dir):
            try:
                os.makedirs(base, exist_ok=True)
                with open(os.path.join(base, key), "w") as f:
                    f.write(data)
            except OSError:
                pass

    def _load_bookmark(self, path):
        key = self._bookmark_key(path)
        for base in (self.bookmark_dir, self.persist_bookmark_dir):
            bpath = os.path.join(base, key)
            if os.path.exists(bpath):
                try:
                    with open(bpath) as f:
                        return int(f.read().strip())
                except (ValueError, OSError):
                    pass
        return None

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw(self):
        with self.lock:
            try:
                self.stdscr.erase()
                h, w = self.stdscr.getmaxyx()
                self.term_w = w
                self.term_h = h
                if h < 3 or w < 10:
                    return
                if self.edit_active:
                    self._draw_edit(h, w)
                elif self.mode == "browser":
                    self._draw_browser(h, w)
                else:
                    self._draw_reader(h, w)
                if self.newfile_active:
                    self._draw_newfile_box(h, w)
                elif self.search_active and not self.edit_active:
                    self._draw_search_box(h, w)
                self.stdscr.refresh()
            except curses.error:
                pass

    def _draw_browser(self, h, w):
        title = "vault browser"
        now = datetime.now().strftime("%H:%M")
        gap = max(1, w - 1 - len(title) - len(now))
        self.stdscr.addnstr(
            0, 0, title, w - 1,
            curses.color_pair(CP_PINK_HEADER) | curses.A_BOLD,
        )
        now_x = len(title) + gap
        if now_x + len(now) < w:
            self.stdscr.addnstr(
                0, now_x, now, w - 1 - now_x,
                curses.color_pair(CP_WHITE),
            )

        self.stdscr.addnstr(
            1, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )

        content_h = h - 4
        if self.file_cursor < self.file_offset:
            self.file_offset = self.file_cursor
        elif self.file_cursor >= self.file_offset + content_h:
            self.file_offset = self.file_cursor - content_h + 1

        if not self.file_list:
            msg = self.browser_status or "(empty directory)"
            self.stdscr.addnstr(
                2, 0, msg[:w - 1], w - 1,
                curses.color_pair(CP_DIM),
            )
        else:
            for i in range(content_h):
                idx = self.file_offset + i
                row = 2 + i
                if row >= h - 2:
                    break
                if idx >= len(self.file_list):
                    break
                name, is_dir, _path = self.file_list[idx]
                display = f"  {name}{'/' if is_dir else ''}"
                if idx == self.file_cursor:
                    self.stdscr.addnstr(
                        row, 0, display[:w - 1], w - 1,
                        curses.color_pair(CP_SELECTED_BG),
                    )
                else:
                    color = CP_MINT if is_dir else CP_WHITE
                    self.stdscr.addnstr(
                        row, 0, display[:w - 1], w - 1,
                        curses.color_pair(color),
                    )

        self.stdscr.addnstr(
            h - 2, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )
        footer = "/search  enter=open  e=edit  n=new  q=quit  esc=back"
        self.stdscr.addnstr(
            h - 1, 0, footer[:w - 1], w - 1,
            curses.color_pair(CP_DIVIDER),
        )

    def _draw_reader(self, h, w):
        ch = self._content_height()
        total_pages = max(1, (len(self.display_lines) + ch - 1) // ch)
        current_page = self.reader_offset // ch + 1
        title = self.content_title
        page_str = f"[{current_page}/{total_pages}]"

        self.stdscr.addnstr(
            0, 0, title[:w - 1 - len(page_str) - 1], w - 1,
            curses.color_pair(CP_PINK_HEADER) | curses.A_BOLD,
        )
        if w > len(page_str) + 1:
            self.stdscr.addnstr(
                0, w - 1 - len(page_str), page_str, len(page_str),
                curses.color_pair(CP_WHITE),
            )

        self.stdscr.addnstr(
            1, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )

        max_offset = max(0, len(self.display_lines) - ch)
        if self.reader_offset > max_offset:
            self.reader_offset = max_offset
        if self.cursor_y < 0:
            self.reader_offset = max(0, self.reader_offset + self.cursor_y)
            self.cursor_y = 0
        if self.cursor_y >= ch:
            self.reader_offset += self.cursor_y - ch + 1
            self.cursor_y = ch - 1
        if self.reader_offset > max_offset:
            self.reader_offset = max_offset
            self.cursor_y = min(self.cursor_y,
                                max(0, len(self.display_lines) - max_offset - 1))

        for i in range(ch):
            line_idx = self.reader_offset + i
            row = 2 + i
            if row >= h - 2:
                break
            if line_idx >= len(self.display_lines):
                break
            line = self.display_lines[line_idx]
            x = 0
            is_cursor_line = (i == self.cursor_y)
            for text, color, attr, link in line:
                if color == CP_BLUE:
                    seg_attr = curses.color_pair(CP_BLUE) | attr
                else:
                    seg_attr = curses.color_pair(color) | attr
                if is_cursor_line and link:
                    seg_attr |= curses.A_BOLD
                if x >= w - 1:
                    break
                self.stdscr.addnstr(row, x, text, w - 1 - x, seg_attr)
                x += len(text)

        self.stdscr.addnstr(
            h - 2, 0, "─" * (w - 1), w - 1,
            curses.color_pair(CP_DIVIDER),
        )
        footer = "pgup/pgdn  enter=follow  e=edit  esc=back  q=browser"
        self.stdscr.addnstr(
            h - 1, 0, footer[:w - 1], w - 1,
            curses.color_pair(CP_DIVIDER),
        )

    def _draw_search_box(self, h, w):
        prompt = f"/{self.search_buf}"
        self.stdscr.addnstr(
            h - 1, 0, prompt[:w - 1], w - 1,
            curses.color_pair(CP_REASONING),
        )

    def _draw_newfile_box(self, h, w):
        prompt = f"new file: {self.newfile_buf}_"
        self.stdscr.addnstr(
            h - 1, 0, prompt[:w - 1], w - 1,
            curses.color_pair(CP_REASONING),
        )


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main(stdscr):
    app = ReaderApp(stdscr)
    try:
        app.run()
    finally:
        _log("RUN EXITING\n---")
        _DBG.close()
        if app.touch_active:
            cyberdeck_touch.stop_touch_listener()
        if app.mouse_active:
            cyberdeck_touch.stop_mouse_listener()


if __name__ == "__main__":
    curses.wrapper(main)
