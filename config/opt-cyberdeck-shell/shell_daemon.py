#!/usr/bin/env python3
"""Cyberdeck Shell Daemon — owns the active app slot on tty1."""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

_xdg = os.environ.get("XDG_RUNTIME_DIR", "")
RUN_DIR = _xdg if (_xdg and os.path.isdir(_xdg)) else f"/tmp/cyberdeck-{os.getuid()}"
SOCK_PATH = os.path.join(RUN_DIR, "cyberdeck-shell.sock")
STATE_PATH = os.path.join(RUN_DIR, "cyberdeck-shell.state")

APPS = {
    "pet":    {"type": "systemd", "service": "cyberdeck-pet"},
    "chat":   {"type": "fbterm",  "launcher": "/usr/local/bin/chat"},
    "dash":   {"type": "fbterm",  "launcher": "/usr/local/bin/dash"},
    "reader": {"type": "fbterm",  "launcher": "/usr/local/bin/reader"},
    "bt":     {"type": "fbterm",  "launcher": "/usr/local/bin/bt"},
    "wifi":   {"type": "fbterm",  "launcher": "/usr/local/bin/wifi"},
    "term":   {"type": "fbterm",  "launcher": "/usr/local/bin/term"},
}

FB_W, FB_H = 640, 480
FB_BPP = 2


_KDSETMODE = 0x4B3A
_KD_GRAPHICS = 1
_KD_TEXT = 0


def _set_tty1_graphics(enable=True):
    """Switch tty1 between KD_GRAPHICS and KD_TEXT.

    Must be called from the tty1 session leader (this daemon) — the ioctl
    requires that. The pet systemd service can't do it because it has no
    controlling tty.
    """
    import fcntl
    mode = _KD_GRAPHICS if enable else _KD_TEXT
    try:
        with open("/dev/tty1", "w") as tty:
            fcntl.ioctl(tty, _KDSETMODE, mode)
    except Exception:
        pass


def _clear_fb():
    """Clear framebuffer to black for clean transitions."""
    try:
        with open("/dev/fb0", "wb") as fb:
            fb.write(b"\x00\x00" * (FB_W * FB_H))
    except Exception:
        pass


def _reset_tty():
    """Reset tty to sane state before launching fbterm."""
    try:
        subprocess.run(["stty", "sane"], check=False, capture_output=True)
        # Hide console cursor — fbterm may leave it visible
        with open("/dev/tty1", "w") as tty:
            tty.write("\033[?25l")
    except Exception:
        pass


class ShellDaemon:
    def __init__(self):
        self.active_app = None
        self.active_proc = None  # subprocess.Popen for fbterm apps
        self._lock = threading.Lock()
        self._running = True
        self._sock = None
        self._default_app = "pet"

    def _write_state(self):
        try:
            os.makedirs(RUN_DIR, exist_ok=True)
            with open(STATE_PATH, "w") as f:
                json.dump({"active": self.active_app}, f)
        except Exception:
            pass

    def _is_service_active(self, service):
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            check=False, capture_output=True
        )
        return result.returncode == 0

    def stop_current(self):
        with self._lock:
            app = self.active_app
            proc = self.active_proc
            self.active_app = None
            self.active_proc = None

        if not app:
            return

        cfg = APPS.get(app)
        if not cfg:
            return

        if cfg["type"] == "systemd":
            subprocess.run(
                ["systemctl", "--user", "stop", cfg["service"]],
                check=False, capture_output=True,
            )
            # wait up to 3s for the service to stop
            for _ in range(30):
                if not self._is_service_active(cfg["service"]):
                    break
                time.sleep(0.1)
        elif cfg["type"] == "fbterm" and proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass

        self._write_state()

    def start_app(self, app_name):
        cfg = APPS.get(app_name)
        if not cfg:
            return

        # avoid double-start
        with self._lock:
            if self.active_app == app_name:
                return

        self.stop_current()

        with self._lock:
            self.active_app = app_name

        if cfg["type"] == "systemd":
            subprocess.run(
                ["systemctl", "--user", "start", cfg["service"]],
                check=False, capture_output=True,
            )
            self.active_proc = None
        elif cfg["type"] == "fbterm":
            _clear_fb()
            _reset_tty()
            env = os.environ.copy()
            env["FBTERM_ACTIVE"] = "1"
            env["TERM"] = "fbterm"
            # fbterm MUST inherit the tty — do not redirect stdio
            launcher = cfg.get("launcher")
            fbterm_opts = cfg.get("fbterm_opts", [])
            if launcher:
                proc = subprocess.Popen(
                    ["fbterm"] + fbterm_opts + ["--", launcher],
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    ["fbterm"] + fbterm_opts,
                    env=env,
                )
            with self._lock:
                self.active_proc = proc

        self._write_state()

    def _pet_monitor(self):
        """Keep pet in sync with active_app state.

        - Stops pet if another app is active (prevents ghost renders).
        - Starts pet if active_app is 'pet' but the service died or lost the
          boot race against the user session manager (silent systemctl failure
          at daemon startup).
        """
        while self._running:
            time.sleep(1.0)
            with self._lock:
                app = self.active_app
            if app and app != "pet":
                if self._is_service_active("cyberdeck-pet"):
                    subprocess.run(
                        ["systemctl", "--user", "stop", "cyberdeck-pet"],
                        check=False, capture_output=True,
                    )
            elif app == "pet" and not self._is_service_active("cyberdeck-pet"):
                # Pet is the intended app but isn't running — start it directly,
                # bypassing start_app's double-start guard.
                subprocess.run(
                    ["systemctl", "--user", "start", "cyberdeck-pet"],
                    check=False, capture_output=True,
                )

    def _fbterm_monitor(self):
        """Wait for fbterm processes to exit, then return to default app."""
        while self._running:
            time.sleep(0.3)
            with self._lock:
                app = self.active_app
                proc = self.active_proc

            if app and proc is not None:
                ret = proc.poll()
                if ret is not None:
                    # fbterm exited — brief pause then go home
                    try:
                        with open("/tmp/shell_daemon.log", "a") as f:
                            f.write(f"[{time.time()}] {app} exited code={ret}\n")
                    except Exception:
                        pass
                    with self._lock:
                        self.active_app = None
                        self.active_proc = None
                    time.sleep(0.5)
                    self.start_app(self._default_app)

    def _handle_client(self, conn):
        try:
            conn.settimeout(2.0)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(256)
                if not chunk:
                    break
                data += chunk

            msg = data.decode("utf-8", "replace").strip()
            parts = msg.split()
            cmd = parts[0].upper() if parts else ""

            if cmd == "SWITCH" and len(parts) >= 2:
                target = parts[1].lower()
                if target in APPS:
                    self.start_app(target)
                    response = f"OK switched to {target}\n"
                else:
                    response = f"ERR unknown app: {target}\n"
            elif cmd == "STATUS":
                with self._lock:
                    current = self.active_app or "none"
                response = f"OK {current}\n"
            else:
                response = f"ERR unknown command: {msg}\n"

            conn.sendall(response.encode())
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _socket_listener(self):
        os.makedirs(RUN_DIR, exist_ok=True)
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCK_PATH)
        self._sock.listen(5)
        os.chmod(SOCK_PATH, 0o666)

        while self._running:
            try:
                self._sock.settimeout(1.0)
                conn, _ = self._sock.accept()
                threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    time.sleep(0.5)

    def run(self):
        threading.Thread(target=self._fbterm_monitor, daemon=True).start()
        threading.Thread(target=self._pet_monitor, daemon=True).start()
        threading.Thread(target=self._socket_listener, daemon=True).start()

        # Start default app
        self.start_app(self._default_app)

        while self._running:
            time.sleep(1)

    def shutdown(self, *_):
        self._running = False
        self.stop_current()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        sys.exit(0)


if __name__ == "__main__":
    daemon = ShellDaemon()
    signal.signal(signal.SIGTERM, daemon.shutdown)
    signal.signal(signal.SIGINT, daemon.shutdown)
    daemon.run()
