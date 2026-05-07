"""Helper for Cyberdeck apps to request switching via the shell daemon."""

import os
import socket

_xdg = os.environ.get("XDG_RUNTIME_DIR", "")
SOCK_PATH = os.path.join(
    _xdg if (_xdg and os.path.isdir(_xdg)) else f"/tmp/cyberdeck-{os.getuid()}",
    "cyberdeck-shell.sock",
)


def switch_to(app_name):
    """Request daemon to switch to app_name.

    Returns True if daemon acknowledged, False on error.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(SOCK_PATH)
            sock.sendall(f"SWITCH {app_name}\n".encode())
            response = sock.recv(256).decode("utf-8", "replace").strip()
            return response.startswith("OK")
    except Exception:
        return False


def current_app():
    """Query daemon for current active app."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(SOCK_PATH)
            sock.sendall(b"STATUS\n")
            response = sock.recv(256).decode("utf-8", "replace").strip()
            parts = response.split()
            if len(parts) >= 2 and parts[0] == "OK":
                return parts[1]
            return None
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "status":
            app = current_app()
            print(app if app else "none")
            sys.exit(0)
        else:
            ok = switch_to(cmd)
            sys.exit(0 if ok else 1)
    print("Usage: cyberdeck_switch.py <app>|status")
    sys.exit(1)
