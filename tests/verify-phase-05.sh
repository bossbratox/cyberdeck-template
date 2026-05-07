#!/bin/bash
# Phase 5: OverlayFS Lockdown verification script
# Run on the Pi after deploying all Phase 5 configs.
#
# Usage: bash tests/verify-phase-05.sh
#
# Two modes:
#   PRE-OVERLAY:  Run before enabling overlay to verify config deployment
#   POST-OVERLAY: Run after enabling overlay to verify full lockdown
#
# Checks marked [POST] only pass when overlay is active.

PASS=0
FAIL=0
SKIP=0

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

skip() {
    local desc="$1"
    echo "  SKIP: $desc"
    ((SKIP++))
}

# Detect overlay state
OVERLAY_ACTIVE=false
if mountpoint -q /media/root-ro 2>/dev/null; then
    OVERLAY_ACTIVE=true
fi

echo "=== Phase 5: OverlayFS Lockdown Verification ==="
echo ""
if [ "$OVERLAY_ACTIVE" = true ]; then
    echo "Mode: POST-OVERLAY (overlay is active)"
else
    echo "Mode: PRE-OVERLAY (overlay not yet enabled)"
fi
echo ""

echo "[PWR-02a] overlayroot package installed"
check "overlayroot package installed" dpkg -l overlayroot

echo ""
echo "[PWR-02b] overlayroot config deployed"
check "overlayroot.local.conf exists" test -f /etc/overlayroot.local.conf
check "overlayroot.local.conf has recurse=0" grep -q 'recurse=0' /etc/overlayroot.local.conf

echo ""
echo "[PWR-02c] Overlay state"
if [ "$OVERLAY_ACTIVE" = true ]; then
    check "[POST] root under overlay (root-ro mounted)" mountpoint -q /media/root-ro
    check "[POST] /boot/firmware is writable" bash -c 'sudo touch /boot/firmware/.write-test && sudo rm /boot/firmware/.write-test'
else
    skip "[POST] root under overlay — overlay not yet enabled"
    skip "[POST] /boot/firmware writable check — overlay not yet enabled"
fi

echo ""
echo "[PWR-02d] Swap disabled (D-04)"
check "no swap active" bash -c 'test "$(free -b | awk "/Swap:/{print \$2}")" -eq 0'
check "dphys-swapfile not installed" bash -c '! dpkg -l dphys-swapfile 2>/dev/null | grep -q "^ii"'

echo ""
echo "[D-05] Update workflow artifacts"
check "cyberdeck-update script exists" test -f /usr/local/bin/cyberdeck-update
check "cyberdeck-update is executable" test -x /usr/local/bin/cyberdeck-update
check "cyberdeck-update-apt.sh exists" test -f /usr/local/bin/cyberdeck-update-apt.sh
check "cyberdeck-update-apt.sh is executable" test -x /usr/local/bin/cyberdeck-update-apt.sh
check "cyberdeck-update-apt.service exists" test -f /etc/systemd/system/cyberdeck-update-apt.service
check "cyberdeck-update-apt.service enabled" systemctl is-enabled cyberdeck-update-apt.service
check "cyberdeck-update-apt.service has ConditionPathExists" grep -q 'ConditionPathExists=/boot/firmware/cyberdeck-update.flag' /etc/systemd/system/cyberdeck-update-apt.service

echo ""
echo "[D-10] Kill-switch recovery service"
check "overlay-killswitch.sh exists" test -f /usr/local/bin/overlay-killswitch.sh
check "overlay-killswitch.sh is executable" test -x /usr/local/bin/overlay-killswitch.sh
check "overlay-killswitch.service exists" test -f /etc/systemd/system/overlay-killswitch.service
check "overlay-killswitch.service enabled" systemctl is-enabled overlay-killswitch.service
check "overlay-killswitch.service has ConditionPathExists" grep -q 'ConditionPathExists=/boot/firmware/overlay.disable' /etc/systemd/system/overlay-killswitch.service

echo ""
echo "[D-07] MOTD overlay status"
check "motd.sh has overlay detection" grep -q 'root-ro' /etc/profile.d/motd.sh
check "motd.sh has unlock warning" grep -q 'OVERLAY UNLOCKED' /etc/profile.d/motd.sh

echo ""
echo "[Persistent paths] Phase 2/3 state survives under overlay"
check "/boot/firmware/persistent/ssh exists" test -d /boot/firmware/persistent/ssh
check "/boot/firmware/persistent/bluetooth exists" test -d /boot/firmware/persistent/bluetooth
check "/boot/firmware/persistent/tailscale exists" test -d /boot/firmware/persistent/tailscale
check "/boot/firmware/persistent/nm-conf.d exists" test -d /boot/firmware/persistent/nm-conf.d
check "restore-persistent-state.service active" systemctl is-active restore-persistent-state.service
if [ "$OVERLAY_ACTIVE" = true ]; then
    check "[POST] SSH host keys present after overlay boot" test -f /etc/ssh/ssh_host_ed25519_key
else
    skip "[POST] SSH host keys under overlay — overlay not yet enabled"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="

if [ "$FAIL" -gt 0 ]; then
    echo "PHASE 5 VERIFICATION: FAIL"
    exit 1
else
    if [ "$SKIP" -gt 0 ]; then
        echo "PHASE 5 VERIFICATION: PASS (with skips — enable overlay and re-run for full check)"
    else
        echo "PHASE 5 VERIFICATION: PASS"
    fi
    exit 0
fi
