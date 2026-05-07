#!/usr/bin/env python3
"""Transparent F-key interceptor for the cyberdeck terminal.

Runs inside fbterm, spawns bash in a PTY, and switches apps on F1-F7.
Everything else passes through unchanged — no status bar, no UI chrome.
"""

import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import tty

sys.path.insert(0, "/opt/cyberdeck-shell")
from cyberdeck_switch import switch_to

_ESC_SEQ_MAP = {
    # VT100 / SS3 style
    b"\x1bOP": "F1", b"\x1bOQ": "F2", b"\x1bOR": "F3", b"\x1bOS": "F4",
    # Linux console style
    b"\x1b[[A": "F1", b"\x1b[[B": "F2", b"\x1b[[C": "F3",
    b"\x1b[[D": "F4", b"\x1b[[E": "F5",
    # xterm style
    b"\x1b[11~": "F1", b"\x1b[12~": "F2", b"\x1b[13~": "F3",
    b"\x1b[14~": "F4", b"\x1b[15~": "F5", b"\x1b[17~": "F6",
    b"\x1b[18~": "F7", b"\x1b[19~": "F8", b"\x1b[20~": "F9",
    b"\x1b[21~": "F10", b"\x1b[23~": "F11", b"\x1b[24~": "F12",
}

FKEY_APP = {
    "F1": "term", "F2": "chat", "F3": "pet",
    "F4": "reader", "F5": "dash", "F6": "wifi", "F7": "bt",
}


def _read_esc_seq(fd):
    """Read the bytes after the leading ESC of an escape sequence.

    Recognized forms:
      SS3:            ESC O <letter>             e.g. \\x1bOP for F1
      CSI:            ESC [ <params>* <final>    e.g. \\x1b[11~ or \\x1b[A
      Linux console:  ESC [ [ <letter>           e.g. \\x1b[[A for F1

    Returns the bytes after ESC (i.e. without the leading ESC byte).
    Bare ESC returns b"".
    """
    if not select.select([fd], [], [], 0.05)[0]:
        return b""
    first = os.read(fd, 1)
    if not first:
        return b""

    if first == b"O":
        # SS3: one trailing byte (F1-F4 letter).
        if select.select([fd], [], [], 0.05)[0]:
            nxt = os.read(fd, 1)
            if nxt:
                return first + nxt
        return first

    if first != b"[":
        return first  # not a CSI/SS3 sequence; just return what we have

    buf = first
    # CSI: keep reading until a final byte (0x40-0x7E) appears, with one
    # special case — Linux console F1-F5 use the form ESC[[<letter> where
    # the second `[` after ESC is intermediate, not final.
    for i in range(16):
        if not select.select([fd], [], [], 0.05)[0]:
            break
        ch = os.read(fd, 1)
        if not ch:
            break
        buf += ch
        if i == 0 and ch == b"[":
            # Linux console: consume the final letter.
            if select.select([fd], [], [], 0.05)[0]:
                tail = os.read(fd, 1)
                if tail:
                    buf += tail
            return buf
        if 0x40 <= ch[0] <= 0x7E:
            break
    return buf


def _set_pty_size(master_fd, from_fd):
    """Copy window size from from_fd to the PTY master."""
    try:
        s = struct.pack("HHHH", 0, 0, 0, 0)
        size = fcntl.ioctl(from_fd, termios.TIOCGWINSZ, s)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def main():
    pid, master_fd = pty.fork()
    if pid == 0:
        # Child: run bash as a login shell
        os.environ["CYBERDECK_NO_DAEMON"] = "1"
        os.execl("/bin/bash", "bash", "-l")
        sys.exit(1)

    # Parent: forward data between stdin and PTY master
    old_tty = None
    try:
        old_tty = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
    except Exception:
        pass

    # Ensure TTY is restored on SIGTERM so the next app gets a sane console
    def _on_sigterm(signum, frame):
        if old_tty is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    # Forward window resizes to the child bash
    def _on_winch(signum, frame):
        _set_pty_size(master_fd, sys.stdin.fileno())
        try:
            os.kill(pid, signal.SIGWINCH)
        except OSError:
            pass

    signal.signal(signal.SIGWINCH, _on_winch)

    try:
        while True:
            ready, _, _ = select.select([sys.stdin, master_fd], [], [], 0.1)

            if master_fd in ready:
                data = os.read(master_fd, 4096)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.flush()

            if sys.stdin in ready:
                ch = os.read(sys.stdin.fileno(), 1)
                if not ch:
                    break
                if ch == b"\x1b":
                    seq = ch + _read_esc_seq(sys.stdin.fileno())
                    key = _ESC_SEQ_MAP.get(seq)
                    if key:
                        app = FKEY_APP.get(key)
                        if app:
                            switch_to(app)
                            continue
                    os.write(master_fd, seq)
                else:
                    os.write(master_fd, ch)
    finally:
        if old_tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        try:
            os.close(master_fd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
