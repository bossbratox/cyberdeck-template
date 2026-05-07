#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-dash/dash_tui.py on Pi
#
# Curses-based monitoring dashboard for cyberdeck.
# Polls 6 hosts every 30s: 5 via SSH/Tailscale, 1 local.
# Pure stdlib — no venv needed.

import curses
import os
import select
import subprocess
import sys
import threading
import time
from datetime import datetime

from cyberdeck_colors import init_colors, CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM, CP_DIVIDER, CP_REASONING, CP_BLUE
from cyberdeck_ssh import ssh_run
import cyberdeck_status
import cyberdeck_touch
import sys

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

REFRESH_INTERVAL = 45

HOSTS = [
    {"name": "nextcloud", "ssh": "nextcloud"},
    {"name": "web", "ssh": "web"},
    {"name": "mail",      "ssh": "mail"},
    {"name": "desktop",  "ssh": "desktop"},
    {"name": "home-pi",  "ssh": "home-pi"},
    {"name": "cyberdeck", "ssh": None},  # local
]

# Outputs three lines: cpu_percent, ram_used_mb ram_total_mb, disk_used_mb disk_total_mb.
# 0.1s sleep between /proc/stat reads for CPU delta.
STAT_CMD = (
    "read cpu a b c idle rest < /proc/stat; "
    "t1=$((a+b+c+idle)); i1=$idle; sleep 0.1; "
    "read cpu a b c idle rest < /proc/stat; "
    "t2=$((a+b+c+idle)); i2=$idle; "
    "d=$((t2-t1)); [ $d -eq 0 ] && d=1; "
    "echo $((100*(t2-t1-i2+i1)/d)); "
    "free -m | awk '/Mem:/{print $3,$2}'; "
    "df -m / | awk 'NR==2{print $3,$2}'"
)


def poll_host(host):
    """Poll a single host. Returns dict with up/cpu/ram or up=False."""
    try:
        if host["ssh"] is None:
            result = subprocess.run(
                ["bash", "-c", STAT_CMD],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return {"up": False}
            lines = result.stdout.strip().split("\n")
        else:
            returncode, stdout, _stderr = ssh_run(host["ssh"], STAT_CMD, timeout=10)
            if returncode != 0:
                return {"up": False}
            lines = stdout.strip().split("\n")
        if len(lines) < 2:
            return {"up": False}
        cpu = int(lines[0])
        ram_used, ram_total = lines[1].split()
        result = {
            "up": True, "cpu": cpu,
            "ram_used": int(ram_used), "ram_total": int(ram_total),
            "disk_used": 0, "disk_total": 1,
        }
        if len(lines) >= 3:
            parts = lines[2].split()
            if len(parts) >= 2:
                result["disk_used"] = int(parts[0])
                result["disk_total"] = int(parts[1])
        return result
    except Exception:
        return {"up": False}


def _metric_color(pct, warn=80, crit=90):
    """Return curses color pair for a percentage metric."""
    if pct >= crit:
        return CP_PINK_HEADER
    if pct >= warn:
        return CP_REASONING
    return CP_BLUE


def format_ram(mb):
    """Format MB as compact string: 512M, 1.2G, 16G."""
    if mb >= 1024:
        g = mb / 1024
        return f"{g:.0f}G" if g >= 10 else f"{g:.1f}G"
    return f"{mb}M"


class DashApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.data = {h["name"]: {"up": None} for h in HOSTS}
        self.lock = threading.Lock()
        self.last_poll = 0

    def run(self):
        curses.curs_set(0)
        try:
            curses.set_escdelay(50)
        except Exception:
            pass
        self.stdscr.nodelay(False)
        self.stdscr.timeout(1000)
        init_colors()

        self.poll_all()

        self.mouse_active = cyberdeck_touch.start_mouse_listener(
            lambda delta: None,  # dash has no scrolling
            on_tap=lambda: None,  # click does nothing in dash
        )

        while True:
            self.draw()
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                pass
            else:
                if ch in ("q", "Q", "\x03", "\x11"):
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
                elif ch in (27, '\x1b'):
                    rest = _read_esc_seq_raw()
                    if not rest:
                        break
                    seq = b"\x1b" + rest
                    key = _ESC_SEQ_MAP.get(seq)
                    if _handle_fkey(key):
                        break

            if time.time() - self.last_poll >= REFRESH_INTERVAL:
                self.poll_all()

    def poll_all(self):
        self.last_poll = time.time()
        for host in HOSTS:
            t = threading.Thread(target=self._poll_one, args=(host,), daemon=True)
            t.start()

    def _poll_one(self, host):
        result = poll_host(host)
        with self.lock:
            self.data[host["name"]] = result

    def draw(self):
        with self.lock:
            try:
                self.stdscr.erase()
                h, w = self.stdscr.getmaxyx()
                if h < 3 or w < 10:
                    return

                # Header: title + status bar (clock + battery)
                title = "cyberdeck monitor"
                self.stdscr.addnstr(0, 0, title, w - 1,
                                    curses.color_pair(CP_PINK_HEADER) | curses.A_BOLD)
                cyberdeck_status.draw_curses(self.stdscr, row=0, right=True,
                                             attr=curses.color_pair(CP_WHITE))

                # Top divider
                self.stdscr.addnstr(1, 0, "\u2500" * (w - 1), w - 1,
                                    curses.color_pair(CP_DIVIDER))

                # Host rows (two rows per host)
                for i, host in enumerate(HOSTS):
                    row = i * 2 + 2
                    if row + 1 >= h - 2:
                        break
                    name = host["name"]
                    info = self.data.get(name, {"up": None})

                    # Hostname (primary row)
                    self.stdscr.addnstr(row, 0, f"{name:<10}", min(10, w - 1),
                                        curses.color_pair(CP_WHITE))
                    if w < 14:
                        continue

                    if info.get("up") is None:
                        self.stdscr.addnstr(row, 11, "...", w - 12,
                                            curses.color_pair(CP_DIM))
                    elif info["up"]:
                        # Up dot
                        self.stdscr.addnstr(row, 11, "\u25cf", 1,
                                            curses.color_pair(CP_MINT) | curses.A_BOLD)
                        # CPU with threshold color
                        cpu_color = _metric_color(info['cpu'], warn=80, crit=95)
                        cpu_s = f"C:{info['cpu']:>3}%"
                        cpu_attr = curses.color_pair(cpu_color)
                        if info['cpu'] >= 95:
                            cpu_attr |= curses.A_BOLD
                        self.stdscr.addnstr(row, 13, cpu_s, w - 14, cpu_attr)
                        # Secondary row: RAM + disk
                        if row + 1 < h - 1:
                            ram_pct = int(info['ram_used'] * 100 / max(1, info['ram_total']))
                            ram_color = _metric_color(ram_pct, warn=75, crit=90)
                            ram_s = f"M:{format_ram(info['ram_used'])}/{format_ram(info['ram_total'])}"
                            ram_attr = curses.color_pair(ram_color)
                            if ram_pct >= 90:
                                ram_attr |= curses.A_BOLD
                            self.stdscr.addnstr(row + 1, 13, ram_s, w - 14, ram_attr)
                            disk_pct = int(info['disk_used'] * 100 / max(1, info['disk_total']))
                            disk_color = _metric_color(disk_pct, warn=80, crit=90)
                            disk_s = f" D:{disk_pct:>3}%"
                            disk_attr = curses.color_pair(disk_color)
                            if disk_pct >= 90:
                                disk_attr |= curses.A_BOLD
                            self.stdscr.addnstr(row + 1, 25, disk_s, w - 26, disk_attr)
                    else:
                        self.stdscr.addnstr(row, 11, "\u2717 offline", w - 12,
                                            curses.color_pair(CP_DIM))

                # Bottom divider
                div_row = len(HOSTS) * 2 + 2
                if div_row < h - 1:
                    self.stdscr.addnstr(div_row, 0, "\u2500" * (w - 1), w - 1,
                                        curses.color_pair(CP_DIVIDER))

                # Footer: countdown + quit hint
                foot_row = div_row + 1
                if foot_row < h:
                    elapsed = int(time.time() - self.last_poll)
                    remaining = max(0, REFRESH_INTERVAL - elapsed)
                    footer = f"refresh {remaining}s   q=quit  esc=back"
                    self.stdscr.addnstr(foot_row, 0, footer, w - 1,
                                        curses.color_pair(CP_DIVIDER))

                self.stdscr.refresh()
            except curses.error:
                pass


def main(stdscr):
    app = DashApp(stdscr)
    app.run()


if __name__ == "__main__":
    curses.wrapper(main)
