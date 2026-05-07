#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-wifi/wifi_tui.py on Pi
#
# Curses-based WiFi manager for cyberdeck.
# Replaces whiptail/nmtui with native curses that supports F-keys,
# arrow keys, and touch input on fbterm.

import curses
import os
import select
import subprocess
import sys
import threading
import time

from cyberdeck_colors import (
    init_colors, CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM,
    CP_DIVIDER, CP_REASONING, CP_SELECTED_BG, CP_BLUE,
)
import cyberdeck_status
import cyberdeck_touch

sys.path.insert(0, "/opt/cyberdeck-shell")
try:
    from cyberdeck_switch import switch_to
except Exception:
    def switch_to(app_name):
        return False


# Escape sequences for F-keys (full sequences including ESC byte)
_ESC_SEQ_MAP = {
    b"\x1bOP": "F1", b"\x1bOQ": "F2", b"\x1bOR": "F3", b"\x1bOS": "F4",
    b"\x1b[[A": "F1", b"\x1b[[B": "F2", b"\x1b[[C": "F3",
    b"\x1b[[D": "F4", b"\x1b[[E": "F5",
    b"\x1b[11~": "F1", b"\x1b[12~": "F2", b"\x1b[13~": "F3",
    b"\x1b[14~": "F4", b"\x1b[15~": "F5", b"\x1b[17~": "F6",
    b"\x1b[18~": "F7",
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
    mapping = {
        "F1": "term", "F2": "chat", "F3": "pet",
        "F4": "reader", "F5": "dash", "F6": "wifi", "F7": "bt",
    }
    app = mapping.get(key)
    if app:
        switch_to(app)
        return True
    return False


_WIFI_IFACE = None


def get_wifi_interface():
    """Return the name of the WiFi interface, or None."""
    global _WIFI_IFACE
    if _WIFI_IFACE is not None:
        return _WIFI_IFACE
    rc, out, _ = nmcli("-t", "-f", "DEVICE,TYPE", "device", "status")
    if rc != 0:
        return None
    for line in out.strip().splitlines():
        if ":wifi" in line:
            _WIFI_IFACE = line.split(":")[0]
            return _WIFI_IFACE
    return None


def nmcli(*args, timeout=10):
    """Run nmcli and return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["nmcli"] + list(args),
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1, "", "nmcli not found or timed out"


def _get_active_wifi_raw():
    """Return (ssid, ip, signal) or None."""
    rc, out, _ = nmcli("-t", "-f", "NAME,TYPE", "connection", "show", "--active")
    if rc != 0:
        return None
    for line in out.strip().splitlines():
        if ":802-11-wireless" in line:
            ssid = line.split(":")[0]
            # Get IP
            iface = get_wifi_interface() or "wlan0"
            rc2, out2, _ = nmcli("-t", "-f", "IP4.ADDRESS", "device", "show", iface)
            ip = ""
            for l2 in out2.strip().splitlines():
                if l2.startswith("IP4.ADDRESS"):
                    ip = l2.split(":", 1)[1].strip().split("/")[0]
                    break
            # Get signal
            rc3, out3, _ = nmcli("-t", "-f", "IN-USE,SIGNAL", "device", "wifi", "list")
            signal = "?"
            for l3 in out3.strip().splitlines():
                if l3.startswith("*:"):
                    signal = l3.split(":")[1]
                    break
            return ssid, ip, signal
    return None


def scan_networks():
    """Return list of (ssid, signal, security) sorted by signal desc."""
    nmcli("device", "wifi", "rescan", timeout=5)
    time.sleep(1)
    rc, out, _ = nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    if rc != 0:
        return []
    seen = set()
    nets = []
    for line in out.strip().splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = parts[1] if parts[1] else "0"
        security = parts[2] if parts[2] else "open"
        nets.append((ssid, signal, security))
    def _signal_key(item):
        try:
            return int(item[1])
        except ValueError:
            return 0
    nets.sort(key=_signal_key, reverse=True)
    return nets[:15]


def get_saved_networks():
    """Return list of saved WiFi connection names."""
    rc, out, _ = nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
    if rc != 0:
        return []
    return [line.split(":")[0] for line in out.strip().splitlines() if ":802-11-wireless" in line]


def is_saved(ssid):
    """Check if a WiFi network is saved (by SSID / connection name)."""
    return ssid in get_saved_networks()


def connect_saved(ssid, timeout=20):
    rc, out, err = nmcli("connection", "up", ssid, timeout=timeout)
    return rc == 0, (out + err).strip()


def connect_new(ssid, password):
    if password:
        rc, out, err = nmcli("device", "wifi", "connect", ssid, "password", password)
    else:
        rc, out, err = nmcli("device", "wifi", "connect", ssid)
    if rc == 0:
        # Best-effort: ensure the new profile autoconnects in the future.
        # Profile name usually matches SSID, but may differ if a profile
        # already existed; ignore failure here.
        nmcli("connection", "modify", ssid, "connection.autoconnect", "yes")
    return rc == 0, (out + err).strip()


def forget_network(ssid):
    rc, _, _ = nmcli("connection", "delete", ssid)
    return rc == 0


def disconnect_wifi():
    iface = get_wifi_interface() or "wlan0"
    rc, _, _ = nmcli("device", "disconnect", iface)
    return rc == 0


def _is_password_error(msg):
    """Check if an nmcli error is password-related."""
    msg_lower = msg.lower()
    return any(k in msg_lower for k in [
        "passwords or encryption keys",
        "secrets were required",
        "authentication failure",
        "wrong password",
        "invalid password",
        "secret required",
    ])


def try_autoconnect():
    """If not connected, try to connect to any in-range saved network."""
    if _get_active_wifi_raw():
        return True
    saved = get_saved_networks()
    if not saved:
        return False
    # Scan briefly to see what's available
    nmcli("device", "wifi", "rescan", timeout=5)
    time.sleep(1)
    rc, out, _ = nmcli("-t", "-f", "SSID", "device", "wifi", "list")
    if rc != 0:
        return False
    available = {line.strip() for line in out.strip().splitlines() if line.strip()}
    for ssid in saved:
        if ssid in available:
            ok, _ = connect_saved(ssid)
            if ok:
                return True
    return False


class WiFiApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.lock = threading.Lock()
        self.should_quit = False
        self.touch_active = False
        self.mouse_active = False

        # Modes: "main", "scan", "saved", "password", "status", "message", "working"
        self.mode = "main"
        self.message = ""
        self.message_next_mode = "main"
        self.working_text = ""
        self.working_next_mode = "main"

        # Main menu
        self.menu_items = [
            ("scan", "Scan & connect"),
            ("saved", "Saved networks"),
            ("status", "Connection info"),
            ("disconnect", "Disconnect"),
        ]
        self.menu_cursor = 0

        # Scan results
        self.scan_results = []
        self.scan_cursor = 0
        self.scan_offset = 0

        # Saved networks
        self.saved_list = []
        self.saved_cursor = 0
        self.saved_offset = 0

        # Password input
        self.pass_ssid = ""
        self.pass_buf = ""
        self.pass_show_plain = False
        self.pass_action = "new"   # "new" or "update"
        self.pass_next_mode = "main"

        # Cached active WiFi info to avoid spamming nmcli on every redraw
        self._active_cache = None
        self._active_cache_time = 0

    def _get_active_wifi(self):
        """Return cached active WiFi info (refreshes every 2s)."""
        now = time.time()
        if self._active_cache is None or now - self._active_cache_time > 2:
            try:
                self._active_cache = _get_active_wifi_raw()
            except Exception:
                self._active_cache = None
            self._active_cache_time = now
        return self._active_cache

    def _invalidate_cache(self):
        self._active_cache = None
        self._active_cache_time = 0

    def _run_in_thread(self, target, args=(), kwargs=None):
        """Run a blocking function in a background thread."""
        def _wrapper():
            try:
                result = target(*args, **(kwargs or {}))
            except Exception as e:
                result = (False, str(e))
            if result is None:
                result = (False, "no result")
            with self.lock:
                try:
                    self._on_thread_done(result)
                except Exception:
                    pass
        threading.Thread(target=_wrapper, daemon=True).start()

    def _on_thread_done(self, result):
        """Called when a background thread finishes. Override via closures."""
        pass

    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.timeout(200)
        init_colors()

        # Attempt autoconnect on startup
        try:
            try_autoconnect()
        except Exception:
            pass

        def _on_scroll(delta):
            with self.lock:
                if self.mode == "main":
                    if delta > 0:
                        self.menu_cursor = max(0, self.menu_cursor - 1)
                    else:
                        self.menu_cursor = min(len(self.menu_items) - 1,
                                               self.menu_cursor + 1)
                elif self.mode == "scan":
                    if delta > 0:
                        self.scan_cursor = max(0, self.scan_cursor - 1)
                    else:
                        self.scan_cursor = min(max(0, len(self.scan_results) - 1),
                                               self.scan_cursor + 1)
                elif self.mode == "saved":
                    if delta > 0:
                        self.saved_cursor = max(0, self.saved_cursor - 1)
                    else:
                        self.saved_cursor = min(max(0, len(self.saved_list) - 1),
                                                self.saved_cursor + 1)

        def _on_tap():
            with self.lock:
                if self.mode == "main":
                    self._activate_menu()
                elif self.mode == "scan" and self.scan_results:
                    self._connect_scan_selection()
                elif self.mode == "saved" and self.saved_list:
                    self._activate_saved()
                elif self.mode == "password":
                    self._activate()

        def _on_tap_xy(x, y):
            # Tap in bottom ~60px of screen = back
            with self.lock:
                if y > 420:
                    self._go_back()

        self.touch_active = cyberdeck_touch.start_touch_listener(_on_scroll, _on_tap, _on_tap_xy)
        self.mouse_active = cyberdeck_touch.start_mouse_listener(_on_scroll, _on_tap)

        while not self.should_quit:
            try:
                self.draw()
                ch = self.stdscr.getch()
                if ch == -1:
                    continue

                with self.lock:
                    if ch == 3 or ch == 17:  # Ctrl-C, Ctrl-Q
                        break
                    elif ch == curses.KEY_F1:
                        switch_to("term"); break
                    elif ch == curses.KEY_F2:
                        switch_to("chat"); break
                    elif ch == curses.KEY_F3:
                        switch_to("pet"); break
                    elif ch == curses.KEY_F4:
                        switch_to("reader"); break
                    elif ch == curses.KEY_F5:
                        switch_to("dash"); break
                    elif ch == curses.KEY_F6:
                        switch_to("wifi"); break
                    elif ch == curses.KEY_F7:
                        switch_to("bt"); break
                    elif ch == 27:  # ESC — bare or start of sequence
                        rest = _read_esc_seq_raw()
                        seq = b"\x1b" + rest
                        key = _ESC_SEQ_MAP.get(seq)
                        if _handle_fkey(key):
                            break
                        if not rest:
                            self._go_back()
                        elif key == "UP":
                            self._move_cursor(-1)
                        elif key == "DOWN":
                            self._move_cursor(1)
                        continue
                    elif ch == curses.KEY_UP:
                        self._move_cursor(-1)
                    elif ch == curses.KEY_DOWN:
                        self._move_cursor(1)
                    elif ch == curses.KEY_RESIZE:
                        pass
                    elif ch == ord('f') and self.mode == "saved":
                        self._forget_saved()
                    elif ch == ord('e') and self.mode == "saved":
                        self._edit_saved_password()
                    elif ch in (10, 13, curses.KEY_ENTER):  # \n, \r, KEY_ENTER
                        self._activate()
                    elif ch == 9 and self.mode == "password":  # Tab = toggle show/hide
                        self.pass_show_plain = not self.pass_show_plain
                    elif ch in (127, 8, curses.KEY_BACKSPACE, 263):
                        self._backspace()
                    elif 32 <= ch <= 126:  # printable ASCII
                        self._type(chr(ch))
            except Exception:
                # Log and exit cleanly on unexpected errors so the shell daemon
                # can return to the default app rather than hanging.
                try:
                    with open("/tmp/wifi_tui_error.log", "a") as f:
                        import traceback
                        f.write(f"[{time.time()}] main-loop exception\n")
                        traceback.print_exc(file=f)
                except Exception:
                    pass
                break

        if self.touch_active:
            cyberdeck_touch.stop_touch_listener()
        if self.mouse_active:
            cyberdeck_touch.stop_mouse_listener()

    def _go_back(self):
        if self.mode == "main":
            self.should_quit = True
        elif self.mode in ("scan", "saved", "status", "message"):
            self.mode = "main"
        elif self.mode == "password":
            self.mode = self.pass_next_mode
            self.pass_buf = ""
            self.pass_show_plain = False
        elif self.mode == "working":
            # Can't cancel a working operation, but back returns to next mode
            self.mode = self.working_next_mode

    def _move_cursor(self, delta):
        if self.mode == "main":
            self.menu_cursor = max(0, min(len(self.menu_items) - 1,
                                          self.menu_cursor + delta))
        elif self.mode == "scan":
            self.scan_cursor = max(0, min(max(0, len(self.scan_results) - 1),
                                          self.scan_cursor + delta))
        elif self.mode == "saved":
            self.saved_cursor = max(0, min(max(0, len(self.saved_list) - 1),
                                           self.saved_cursor + delta))

    def _activate(self):
        if self.mode == "main":
            self._activate_menu()
        elif self.mode == "scan":
            self._connect_scan_selection()
        elif self.mode == "saved":
            self._activate_saved()
        elif self.mode == "password":
            if self.pass_action == "update":
                self._do_update_saved_password()
            else:
                self._do_connect_new()
        elif self.mode == "message":
            self.mode = self.message_next_mode
        elif self.mode == "working":
            # Enter during working just returns to the next mode
            self.mode = self.working_next_mode

    def _activate_menu(self):
        action = self.menu_items[self.menu_cursor][0]
        if action == "scan":
            self.mode = "scan"
            self.scan_results = scan_networks()
            self.scan_cursor = 0
            self.scan_offset = 0
        elif action == "saved":
            self.mode = "saved"
            self.saved_list = get_saved_networks()
            self.saved_cursor = 0
            self.saved_offset = 0
        elif action == "status":
            self.mode = "status"
        elif action == "disconnect":
            if disconnect_wifi():
                self._invalidate_cache()
                self._show_message("Disconnected", "main")
            else:
                self._show_message("Disconnect failed", "main")

    def _trigger_vault_sync(self):
        """Detached background vault-sync — survives wifi TUI exit.
        Daemon threads die with their process; setsid-detached child survives.
        """
        try:
            log_fd = open("/tmp/vault-sync.log", "a")
            subprocess.Popen(
                ["/usr/local/bin/vault-sync"],
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            pass

    def _connect_scan_selection(self):
        if not self.scan_results:
            return
        ssid = self.scan_results[self.scan_cursor][0]
        active = self._get_active_wifi()
        if active and active[0] == ssid:
            self._show_message(f"Already connected to {ssid}", "main")
            return
        if is_saved(ssid):
            self._start_working(f"Connecting to {ssid}...", "main")

            def _on_done(result):
                ok, msg = result
                self._invalidate_cache()
                if ok:
                    self._trigger_vault_sync()
                    self._show_message(f"Connected to {ssid}", "main")
                else:
                    # Always allow password retry on saved-network failures
                    self.pass_ssid = ssid
                    self.pass_buf = ""
                    self.pass_action = "update"
                    self.pass_next_mode = "main"
                    self.mode = "password"

            self._on_thread_done = _on_done
            self._run_in_thread(connect_saved, (ssid,))
        else:
            self.pass_ssid = ssid
            self.pass_buf = ""
            self.pass_action = "new"
            self.pass_next_mode = "scan"
            self.mode = "password"

    def _do_connect_new(self):
        self._start_working(f"Connecting to {self.pass_ssid}...", self.pass_next_mode)

        def _on_done(result):
            ok, msg = result
            self._invalidate_cache()
            if ok:
                self._trigger_vault_sync()
                self._show_message(f"Connected to {self.pass_ssid}", self.pass_next_mode)
            else:
                self._show_message(f"Failed:\n{msg[:120]}", self.pass_next_mode)
            self.pass_buf = ""
            self.pass_show_plain = False

        self._on_thread_done = _on_done
        self._run_in_thread(connect_new, (self.pass_ssid, self.pass_buf))

    def _do_update_saved_password(self):
        """Update password on a saved network by deleting and recreating the profile."""
        self._start_working(f"Updating {self.pass_ssid}...", self.pass_next_mode)

        def _update_then_connect():
            # Remove old profile and connect with new password
            forget_network(self.pass_ssid)
            return connect_new(self.pass_ssid, self.pass_buf)

        def _on_done(result):
            ok, msg = result
            self._invalidate_cache()
            if ok:
                self._show_message(f"Connected to {self.pass_ssid}", self.pass_next_mode)
            else:
                self._show_message(f"Failed:\n{msg[:120]}", self.pass_next_mode)
            self.pass_buf = ""
            self.pass_show_plain = False

        self._on_thread_done = _on_done
        self._run_in_thread(_update_then_connect)

    def _activate_saved(self):
        if not self.saved_list:
            return
        ssid = self.saved_list[self.saved_cursor]
        active = self._get_active_wifi()
        if active and active[0] == ssid:
            self._show_message(f"Already connected to {ssid}", "saved")
            return
        self._start_working(f"Connecting to {ssid}...", "saved")

        def _on_done(result):
            ok, msg = result
            self._invalidate_cache()
            if ok:
                self._trigger_vault_sync()
                self._show_message(f"Connected to {ssid}", "saved")
            else:
                # Always allow password retry on saved-network failures
                self.pass_ssid = ssid
                self.pass_buf = ""
                self.pass_action = "update"
                self.pass_next_mode = "saved"
                self.mode = "password"

        self._on_thread_done = _on_done
        self._run_in_thread(connect_saved, (ssid,))

    def _edit_saved_password(self):
        """Prompt to re-enter password for the selected saved network."""
        if not self.saved_list:
            return
        ssid = self.saved_list[self.saved_cursor]
        self.pass_ssid = ssid
        self.pass_buf = ""
        self.pass_action = "update"
        self.pass_next_mode = "saved"
        self.mode = "password"

    def _forget_saved(self):
        if not self.saved_list:
            return
        ssid = self.saved_list[self.saved_cursor]
        if forget_network(ssid):
            self.saved_list.pop(self.saved_cursor)
            self.saved_cursor = min(self.saved_cursor, max(0, len(self.saved_list) - 1))
            self._invalidate_cache()
            self._show_message(f"Forgot {ssid}", "saved")
        else:
            self._show_message(f"Failed to forget {ssid}", "saved")

    def _backspace(self):
        if self.mode == "password":
            self.pass_buf = self.pass_buf[:-1]

    def _type(self, ch):
        if self.mode == "password":
            self.pass_buf += ch

    def _show_message(self, text, next_mode):
        self.message = text
        self.message_next_mode = next_mode
        self.mode = "message"

    def _start_working(self, text, next_mode):
        self.working_text = text
        self.working_next_mode = next_mode
        self.mode = "working"

    def draw(self):
        try:
            self.stdscr.erase()
        except curses.error:
            return
        h, w = self.stdscr.getmaxyx()
        if w < 20 or h < 5:
            return

        # Header — white bold for legibility on candy-pink bg
        header = " WiFi "
        try:
            self.stdscr.addnstr(0, 0, header, w - 1,
                                curses.color_pair(CP_WHITE) | curses.A_BOLD)
            self.stdscr.chgat(0, 0, w - 1, curses.color_pair(CP_WHITE) | curses.A_BOLD)
            cyberdeck_status.draw_curses(self.stdscr, row=0, right=True,
                                         attr=curses.color_pair(CP_WHITE) | curses.A_BOLD)
        except curses.error:
            pass

        try:
            if self.mode == "main":
                self._draw_main(h, w)
            elif self.mode == "scan":
                self._draw_scan(h, w)
            elif self.mode == "saved":
                self._draw_saved(h, w)
            elif self.mode == "status":
                self._draw_status(h, w)
            elif self.mode == "password":
                self._draw_password(h, w)
            elif self.mode == "message":
                self._draw_message(h, w)
            elif self.mode == "working":
                self._draw_working(h, w)
        except curses.error:
            pass

        # Footer — mode-dependent hints
        if h > 2:
            try:
                self.stdscr.addnstr(h - 2, 0, "─" * (w - 1), w - 1, curses.color_pair(CP_BLUE))
                if self.mode == "saved":
                    footer = "enter=connect  e=edit password  f=forget  esc=back"
                elif self.mode == "password":
                    footer = "enter=connect  tab=show/hide  esc=back"
                elif self.mode == "message":
                    footer = "enter=ok  esc=back"
                else:
                    footer = "enter=select  esc=back"
                self.stdscr.addnstr(h - 1, 0, footer[:w - 1], w - 1, curses.color_pair(CP_MINT))
            except curses.error:
                pass

        try:
            self.stdscr.refresh()
        except curses.error:
            pass

    def _draw_main(self, h, w):
        # Show connected status above the menu
        active = self._get_active_wifi()
        if active:
            ssid, ip, signal = active
            status_line = f"Connected: {ssid} ({signal}%)"
            self.stdscr.addnstr(2, 0, status_line[:w - 1], w - 1,
                                curses.color_pair(CP_MINT))
            start = 4
        else:
            self.stdscr.addnstr(2, 0, "Not connected", w - 1,
                                curses.color_pair(CP_DIM))
            start = 4
        for i, (key, label) in enumerate(self.menu_items):
            if start + i >= h - 2:
                break
            attr = curses.color_pair(CP_WHITE)
            prefix = "  "
            if i == self.menu_cursor:
                attr = curses.color_pair(CP_SELECTED_BG)
                prefix = "> "
            line = f"{prefix}{label}"
            self.stdscr.addnstr(start + i, 0, line[:w - 1], w - 1, attr)

    def _draw_scan(self, h, w):
        if not self.scan_results:
            self.stdscr.addnstr(2, 0, "No networks found", w - 1,
                                curses.color_pair(CP_BLUE))
            return
        list_h = h - 4
        self.scan_offset = max(0, min(self.scan_offset,
                                      len(self.scan_results) - list_h))
        self.scan_offset = max(0, self.scan_cursor - list_h + 1,
                               min(self.scan_offset, self.scan_cursor))
        start = 2
        for i in range(list_h):
            idx = self.scan_offset + i
            if idx >= len(self.scan_results):
                break
            ssid, signal, security = self.scan_results[idx]
            lock = "L" if security and security != "open" else "O"
            line = f"{ssid[:20]:<20} {signal:>3}% {lock}"
            attr = curses.color_pair(CP_WHITE)
            if idx == self.scan_cursor:
                attr = curses.color_pair(CP_SELECTED_BG)
            self.stdscr.addnstr(start + i, 0, line[:w - 1], w - 1, attr)

    def _draw_saved(self, h, w):
        if not self.saved_list:
            self.stdscr.addnstr(2, 0, "No saved networks", w - 1,
                                curses.color_pair(CP_BLUE))
            return
        list_h = h - 4
        self.saved_offset = max(0, min(self.saved_offset,
                                       len(self.saved_list) - list_h))
        self.saved_offset = max(0, self.saved_cursor - list_h + 1,
                                min(self.saved_offset, self.saved_cursor))
        start = 2
        for i in range(list_h):
            idx = self.saved_offset + i
            if idx >= len(self.saved_list):
                break
            ssid = self.saved_list[idx]
            line = f"  {ssid[:w-4]}"
            attr = curses.color_pair(CP_WHITE)
            if idx == self.saved_cursor:
                attr = curses.color_pair(CP_SELECTED_BG)
                line = "> " + ssid[:w-4]
            self.stdscr.addnstr(start + i, 0, line[:w - 1], w - 1, attr)

    def _draw_status(self, h, w):
        active = self._get_active_wifi()
        lines = []
        if active:
            ssid, ip, signal = active
            lines = [
                (f"Connected: ", CP_MINT),
                (f"{ssid}", CP_WHITE),
                (f"IP: ", CP_MINT),
                (f"{ip or 'n/a'}", CP_WHITE),
                (f"Signal: ", CP_MINT),
                (f"{signal}%", CP_WHITE),
            ]
        else:
            lines = [("Not connected to WiFi", CP_BLUE)]
        row = 2
        for text, color in lines:
            if row >= h - 2:
                break
            self.stdscr.addnstr(row, 0, text[:w - 1], w - 1,
                                curses.color_pair(color))
            row += 1

    def _draw_password(self, h, w):
        display = self.pass_buf if self.pass_show_plain else '•' * len(self.pass_buf)
        lines = [
            (f"Password for:", CP_BLUE),
            (f"{self.pass_ssid}", CP_MINT),
            ("", CP_WHITE),
            (f"{display}", CP_WHITE),
        ]
        for i, (text, color) in enumerate(lines):
            if 2 + i >= h - 2:
                break
            self.stdscr.addnstr(2 + i, 0, text[:w - 1], w - 1,
                                curses.color_pair(color))

    def _draw_message(self, h, w):
        lines = self.message.split("\n")
        for i, line in enumerate(lines):
            if 2 + i >= h - 2:
                break
            # Use mint for success messages, white for errors
            color = CP_MINT if "Connected" in line or "Forgot" in line or "Disconnected" in line else CP_WHITE
            self.stdscr.addnstr(2 + i, 0, line[:w - 1], w - 1,
                                curses.color_pair(color))

    def _draw_working(self, h, w):
        self.stdscr.addnstr(2, 0, self.working_text[:w - 1], w - 1,
                            curses.color_pair(CP_MINT))
        self.stdscr.addnstr(4, 0, "Please wait...", w - 1,
                            curses.color_pair(CP_WHITE))


def main():
    curses.wrapper(lambda stdscr: WiFiApp(stdscr).run())


if __name__ == "__main__":
    main()
