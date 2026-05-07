#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-shared/cyberdeck_ssh.py on Pi
#
# SSH helper that benefits from ControlMaster socket reuse configured in
# ~/.ssh/config. Python code is identical to a plain subprocess call --
# the muxing is handled by OpenSSH client config, not Python.

import subprocess


def ssh_run(host, cmd, timeout=10):
    """Run cmd on host via SSH. Returns (returncode, stdout, stderr).

    SSH ControlMaster config in ~/.ssh/config handles connection reuse:
      - First call to a host: opens master socket at /tmp/ssh-ctrl-{host},
        authenticates, runs cmd (~1-3s on Tailscale).
      - Subsequent calls within ControlPersist=120s window: mux through
        existing socket (<100ms).
    BatchMode=yes ensures fast failure (no password prompt hang).
    ConnectTimeout is set to max(1, min(3, timeout-1)) to respect caller's budget.
    """
    connect_timeout = max(1, min(3, timeout - 1))
    result = subprocess.run(
        ["ssh",
         "-o", "BatchMode=yes",
         "-o", f"ConnectTimeout={connect_timeout}",
         host, cmd],
        stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr
