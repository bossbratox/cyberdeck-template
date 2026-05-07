#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-bt/bt_tui.py on Pi
#
# Curses-based Bluetooth manager TUI for cyberdeck shell.
# Wraps bluetoothctl for scan/pair/connect/disconnect/remove.
# Uses only curses (stdlib) + subprocess — no external deps.

import curses
import os
import pty
import select
import subprocess
import sys
import threading
import time

from cyberdeck_colors import init_colors, CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM, CP_DIVIDER, CP_REASONING, CP_SELECTED_BG
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
    """Switch to the app mapped to an F-key."""
    mapping = {
        "F1": "term", "F2": "chat", "F3": "pet",
        "F4": "reader", "F5": "dash", "F6": "wifi", "F7": "bt",
    }
    app = mapping.get(key)
    if app:
        switch_to(app)
        return True
    return False


def bt_cmd(*args):
    """Run a bluetoothctl command, return stdout lines."""
    try:
        r = subprocess.run(
            ["bluetoothctl"] + list(args),
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip().splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError, KeyboardInterrupt):
        return []


def bt_session(commands, timeout=15, auto_confirm=False):
    """Run multiple commands in a single bluetoothctl interactive session.

    Uses a pty so bluetoothctl runs in interactive mode (required for
    agent registration and pairing). Sends commands with small delays
    to let the daemon process each one.

    If auto_confirm is True, automatically responds 'yes' to passkey
    confirmation prompts (needed for Apple/BLE devices that require
    DisplayYesNo pairing).
    """
    try:
        master, slave = pty.openpty()
        p = subprocess.Popen(
            ["bluetoothctl"], stdin=slave, stdout=slave, stderr=slave,
            close_fds=True
        )
        os.close(slave)

        # Wait for daemon connection
        time.sleep(0.5)

        for cmd in commands:
            os.write(master, (cmd + "\n").encode())
            time.sleep(0.3)

        # Collect output, watching for confirmation prompts
        deadline = time.monotonic() + timeout
        output = b""
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.5)[0]:
                # No output for 0.5s — check if pair finished
                decoded = output.decode(errors="replace").lower()
                if "pairing successful" in decoded or "failed" in decoded:
                    break
                continue
            chunk = os.read(master, 4096)
            output += chunk
            if auto_confirm and b"(yes/no)" in chunk:
                time.sleep(0.2)
                os.write(master, b"yes\n")

        os.write(master, b"quit\n")
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
        os.close(master)

        return output.decode(errors="replace").splitlines()
    except (OSError, FileNotFoundError):
        return []


def bt_power_on():
    bt_cmd("power", "on")
    bt_cmd("pairable", "on")


def get_paired_devices():
    """Return list of (mac, name, connected) tuples for paired devices."""
    lines = bt_cmd("devices", "Paired")
    if not lines:
        # Fallback — older bluetoothctl doesn't support 'devices Paired'
        lines = bt_cmd("paired-devices")
    devices = []
    for line in lines:
        # "Device AA:BB:CC:DD:EE:FF Name Here"
        parts = line.split(None, 2)
        if len(parts) >= 3 and parts[0] == "Device":
            mac = parts[1]
            name = parts[2] if len(parts) > 2 else mac
            connected = is_connected(mac)
            devices.append((mac, name, connected))
    return devices


def get_all_devices():
    """Return list of (mac, name) from scan results."""
    lines = bt_cmd("devices")
    devices = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0] == "Device":
            mac = parts[1]
            name = parts[2] if len(parts) > 2 else mac
            devices.append((mac, name))
    return devices


def is_connected(mac):
    """Check if a device is currently connected."""
    lines = bt_cmd("info", mac)
    for line in lines:
        if "Connected: yes" in line:
            return True
    return False


class BtApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.devices = []       # list of (mac, name, connected)
        self.cursor = 0
        self.status = ""
        self.scanning = False
        self.scan_proc = None
        self._gatttool_proc = None
        self.lock = threading.Lock()
        self.mode = "paired"    # "paired" or "scan"
        self.touch_active = False
        self.mouse_active = False
        # Updated by draw() so the touch thread can map Y -> device index
        self.visible_start = 0
        self.list_row_top = 2       # first row of the device list
        self.list_row_bottom = 0    # exclusive; set in draw()
        self.term_h = 0

    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.timeout(500)
        init_colors()

        bt_power_on()
        self.refresh_devices()

        def _on_scroll(delta):
            self._move_cursor(delta)

        def _on_tap():
            self.action_connect()

        self.touch_active = cyberdeck_touch.start_touch_listener(_on_scroll, _on_tap)
        self.mouse_active = cyberdeck_touch.start_mouse_listener(_on_scroll, _on_tap)
        touch_msg = "  touch=tap/swipe" if (self.touch_active or self.mouse_active) else ""
        self.status = ("s=scan p=paired c=connect d=disconnect "
                       "t=trust r=remove q=quit" + touch_msg)
        self.draw()

        while True:
            try:
                ch = self.stdscr.getch()
            except curses.error:
                self.draw()
                continue

            if ch == -1:
                # Timeout — redraw for scan updates
                if self.scanning:
                    self.refresh_scan_devices()
                self.draw()
                continue

            if ch in (ord('q'), ord('Q')):
                self.stop_scan()
                if self._gatttool_proc:
                    self._gatttool_proc.terminate()
                break
            elif ch == 27:  # ESC — could be bare Esc or start of sequence
                rest = _read_esc_seq_raw()
                if not rest:  # bare Esc = quit
                    self.stop_scan()
                    if self._gatttool_proc:
                        self._gatttool_proc.terminate()
                    break
                seq = b"\x1b" + rest
                key = _ESC_SEQ_MAP.get(seq)
                if _handle_fkey(key):
                    self.stop_scan()
                    if self._gatttool_proc:
                        self._gatttool_proc.terminate()
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
            elif ch == ord('s'):
                self.start_scan()
            elif ch == ord('p'):
                self.stop_scan()
                self.mode = "paired"
                self.refresh_devices()
                self.status = "showing paired devices"
                self.draw()
            elif ch == ord('c'):
                self.action_connect()
            elif ch == ord('d'):
                self.action_disconnect()
            elif ch == ord('t'):
                self.action_trust()
            elif ch == ord('r'):
                self.action_remove()
            elif ch == ord('a'):
                self.action_pair()
            elif ch == curses.KEY_UP or ch == ord('k'):
                with self.lock:
                    if self.cursor > 0:
                        self.cursor -= 1
                self.draw()
            elif ch == curses.KEY_DOWN or ch == ord('j'):
                with self.lock:
                    if self.cursor < len(self.devices) - 1:
                        self.cursor += 1
                self.draw()
            elif ch == curses.KEY_RESIZE:
                self.draw()
            elif ch == ord('\n'):
                self.action_connect()

    def _handle_tap(self, touch_y):
        """Tap within device list area: move cursor to tapped row."""
        with self.lock:
            if self.term_h <= 0 or not self.devices:
                return
            # Map touch Y (0..TOUCH_Y_MAX) to curses screen row
            screen_row = int((touch_y / TOUCH_Y_MAX) * self.term_h)
            if screen_row < self.list_row_top or screen_row >= self.list_row_bottom:
                return
            idx = self.visible_start + (screen_row - self.list_row_top)
            if 0 <= idx < len(self.devices):
                self.cursor = idx
        self.draw()

    def _move_cursor(self, delta):
        """Move cursor by delta rows, clamped."""
        with self.lock:
            if not self.devices:
                return
            new = self.cursor + delta
            self.cursor = max(0, min(len(self.devices) - 1, new))
        self.draw()

    def refresh_devices(self):
        with self.lock:
            if self.mode == "paired":
                self.devices = get_paired_devices()
            else:
                self.refresh_scan_devices_inner()
            if self.cursor >= len(self.devices):
                self.cursor = max(0, len(self.devices) - 1)

    def refresh_scan_devices(self):
        with self.lock:
            self.refresh_scan_devices_inner()

    def refresh_scan_devices_inner(self):
        all_devs = get_all_devices()
        paired = {mac for mac, _, _ in get_paired_devices()}
        self.devices = [
            (mac, name, is_connected(mac))
            for mac, name in all_devs
            # Filter out unnamed devices (just MAC echoed back)
            if name != mac or mac in paired
        ]
        if self.cursor >= len(self.devices):
            self.cursor = max(0, len(self.devices) - 1)

    def start_scan(self):
        if self.scanning:
            return
        self.mode = "scan"
        self.scanning = True
        self.status = "scanning LE+BR/EDR... (s=stop, a=pair, c=connect)"
        # Set transport filter to auto (LE + BR/EDR), then start scan.
        # Must use interactive session for menu commands.
        try:
            self.scan_proc = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Send commands to set LE transport and start scan
            self.scan_proc.stdin.write(b"menu scan\ntransport auto\nback\nscan on\n")
            self.scan_proc.stdin.flush()
        except FileNotFoundError:
            self.status = "bluetoothctl not found"
            self.scanning = False
        self.draw()

    def stop_scan(self):
        if not self.scanning:
            return
        self.scanning = False
        if self.scan_proc and self.scan_proc.stdin:
            try:
                self.scan_proc.stdin.write(b"scan off\nquit\n")
                self.scan_proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        if self.scan_proc:
            try:
                self.scan_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.scan_proc.kill()
            self.scan_proc = None

    def selected_device(self):
        with self.lock:
            if 0 <= self.cursor < len(self.devices):
                return self.devices[self.cursor]
        return None

    def action_connect(self):
        dev = self.selected_device()
        if not dev:
            return
        mac, name, _ = dev
        self.status = f"connecting to {name}..."
        self.draw()
        result = bt_cmd("connect", mac)
        success = any("successful" in l.lower() for l in result)
        # If classic connect fails with br-connection-not-supported,
        # fall back to gatttool for BLE-only devices (e.g. BluTouch)
        if not success and any("br-connection-not-supported" in l for l in result):
            self.status = f"BLE connect to {name}..."
            self.draw()
            success = self._ble_connect(mac)
        self.status = f"connected to {name}" if success else f"connect failed: {name}"
        self.refresh_devices()
        self.draw()

    def _ble_connect(self, mac):
        """Force LE connection via gatttool for BLE-only devices."""
        try:
            p = subprocess.Popen(
                ["gatttool", "-b", mac, "-t", "public", "-I"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True
            )
            time.sleep(0.5)
            p.stdin.write("connect\n")
            p.stdin.flush()
            time.sleep(5)
            connected = is_connected(mac)
            # Keep gatttool alive in background — killing it drops the connection
            if connected:
                self._gatttool_proc = p
            else:
                p.stdin.write("quit\n")
                p.stdin.flush()
                p.wait(timeout=3)
            return connected
        except (OSError, subprocess.TimeoutExpired):
            return False

    def action_disconnect(self):
        dev = self.selected_device()
        if not dev:
            return
        mac, name, _ = dev
        self.status = f"disconnecting {name}..."
        self.draw()
        bt_cmd("disconnect", mac)
        self.status = f"disconnected {name}"
        self.refresh_devices()
        self.draw()

    def action_trust(self):
        dev = self.selected_device()
        if not dev:
            return
        mac, name, _ = dev
        bt_cmd("trust", mac)
        self.status = f"trusted {name}"
        self.draw()

    def action_pair(self):
        dev = self.selected_device()
        if not dev:
            return
        mac, name, _ = dev
        self.status = f"pairing {name}..."
        self.draw()
        # Pairing requires an interactive session with agent registered.
        # Use KeyboardDisplay agent — handles both BLE "Just Works" and
        # devices requiring passkey confirmation (auto-confirmed).
        result = bt_session([
            "agent off",
            "agent KeyboardDisplay",
            "default-agent",
            "pairable on",
            f"pair {mac}",
            f"trust {mac}",
        ], timeout=30, auto_confirm=True)
        success = any(
            "pairing successful" in l.lower() or "already exists" in l.lower()
            for l in result
        )
        if success:
            self.status = f"paired + trusted {name}"
        else:
            # Filter ANSI codes for cleaner error display
            errors = [l for l in result if "fail" in l.lower() or "error" in l.lower()]
            msg = errors[-1] if errors else "check device is in pairing mode"
            self.status = f"pair failed: {msg}"
        self.refresh_devices()
        self.draw()

    def action_remove(self):
        dev = self.selected_device()
        if not dev:
            return
        mac, name, _ = dev
        bt_cmd("remove", mac)
        self.status = f"removed {name}"
        self.refresh_devices()
        self.draw()

    def draw(self):
        with self.lock:
            try:
                self.stdscr.erase()
                h, w = self.stdscr.getmaxyx()
                self.term_h = h
                if h < 5 or w < 20:
                    return

                row = 0

                # Header
                title = " bluetooth " if self.mode == "paired" else " bluetooth scan "
                pad = max(0, w - 1 - len(title)) // 2
                header = "─" * pad + title + "─" * max(0, w - 1 - pad - len(title))
                self.stdscr.addnstr(row, 0, header, w - 1, curses.color_pair(CP_WHITE) | curses.A_BOLD)
                cyberdeck_status.draw_curses(self.stdscr, row=row, right=True,
                                             attr=curses.color_pair(CP_WHITE) | curses.A_BOLD)
                row += 1

                # Column header
                if row < h - 2:
                    col_hdr = f"  {'device':<{w - 16}}{'status':>8}"
                    self.stdscr.addnstr(row, 0, col_hdr[:w - 1], w - 1, curses.color_pair(CP_DIVIDER))
                    row += 1

                # Device list
                list_h = h - 4  # reserve header(2) + status + help
                self.list_row_top = row
                if not self.devices:
                    if row < h - 2:
                        msg = "  no devices found" if self.mode == "scan" else "  no paired devices"
                        self.stdscr.addnstr(row, 0, msg, w - 1, curses.color_pair(CP_REASONING))
                        row += 1
                else:
                    # Scroll window if list is longer than display area
                    visible_start = 0
                    if self.cursor >= list_h:
                        visible_start = self.cursor - list_h + 1
                    self.visible_start = visible_start

                    for i in range(visible_start, min(len(self.devices), visible_start + list_h)):
                        if row >= h - 2:
                            break
                        mac, name, connected = self.devices[i]
                        selected = (i == self.cursor)

                        # Build line
                        indicator = "●" if connected else "○"
                        status_str = "connected" if connected else ""
                        display_name = name if len(name) <= w - 20 else name[:w - 23] + "..."
                        line = f"  {indicator} {display_name}"
                        line = line.ljust(w - 12)
                        line = (line + status_str)[:w - 1]

                        if selected:
                            attr = curses.color_pair(CP_SELECTED_BG) | curses.A_BOLD
                        elif connected:
                            attr = curses.color_pair(CP_MINT)
                        else:
                            attr = curses.color_pair(CP_WHITE)

                        self.stdscr.addnstr(row, 0, line, w - 1, attr)
                        row += 1

                self.list_row_bottom = row

                # Status line (second to last)
                status_y = h - 2
                div = "─" * (w - 1)
                self.stdscr.addnstr(status_y, 0, div, w - 1, curses.color_pair(CP_DIVIDER))

                # Help / status (last line)
                help_y = h - 1
                display_status = self.status[:w - 1] if self.status else ""
                self.stdscr.addnstr(help_y, 0, display_status, w - 1, curses.color_pair(CP_WHITE))

                self.stdscr.refresh()
            except curses.error:
                pass


def main(stdscr):
    app = BtApp(stdscr)
    app.run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
