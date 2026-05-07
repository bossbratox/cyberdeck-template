#!/bin/bash
# Phase 3: Connectivity verification script
# Run on the Pi after deploying all Phase 3 configs.
#
# Usage: bash tests/verify-phase-03.sh
#
# Checks NET-01 through NET-04 and HW-04.
# Some checks are smoke tests (service active, command exists).
# Full connectivity tests (SSH to nextcloud) require network access.

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        ((PASS++))
    else
        echo "  FAIL: $desc"
        ((FAIL++))
    fi
}

echo "=== Phase 3: Connectivity Verification ==="
echo ""

echo "[NET-01] WiFi management"
check "nmtui is available" command -v nmtui
check "NetworkManager is active" systemctl is-active NetworkManager
check "WiFi device managed by NM" nmcli dev status

echo ""
echo "[NET-02] Tailscale"
check "tailscale binary installed" command -v tailscale
check "tailscaled service active" systemctl is-active tailscaled
check "tailscale has peers" tailscale status
check "restore script has Tailscale block" grep -q 'var/lib/tailscale' /usr/local/bin/restore-persistent-state.sh
check "tailscale state in persistent store" test -d /boot/firmware/persistent/tailscale
check "restore service Before= includes tailscaled" grep -q 'tailscaled.service' /etc/systemd/system/restore-persistent-state.service

echo ""
echo "[NET-03] SSH via Tailscale"
check "SSH config exists" test -f ~/.ssh/config
check "SSH config has nextcloud alias" grep -q 'Host nextcloud$' ~/.ssh/config
check "ed25519 private key exists" test -f ~/.ssh/id_ed25519
check "ed25519 key permissions correct (600)" test "$(stat -c %a ~/.ssh/id_ed25519)" = "600"

echo ""
echo "[NET-04] SSH fallback via public IP"
check "SSH config has nextcloud-pub alias" grep -q 'Host nextcloud-pub' ~/.ssh/config

echo ""
echo "[HW-04] Bluetooth keyboard"
check "bt-keyboard service enabled" systemctl is-enabled bt-keyboard.service
check "BT pairings in persistent store" test -d /boot/firmware/persistent/bluetooth
check "BT pairings backup exists" test -f /boot/firmware/persistent/bluetooth.tar.gz

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo "PHASE 3 VERIFICATION: FAIL"
    exit 1
else
    echo "PHASE 3 VERIFICATION: PASS"
    exit 0
fi
