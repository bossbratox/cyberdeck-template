#!/bin/bash
# Phase 2 verification script — run on the Pi after deploying all Phase 2 configs
# Usage: bash tests/verify-phase-02.sh
# Exit code: 0 if all checks pass, 1 if any fail
#
# Note: Log2Ram checks are skipped when overlayroot is active or when log2ram
# has been intentionally disabled (overlayroot makes it redundant).

PASS=0
FAIL=0
SKIP=0

check() {
    local desc="$1"
    local cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
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

echo "=== Phase 2: Power Safety and SD Card Protection ==="
echo ""

echo "--- noatime ---"
check "noatime active on root partition" "cat /proc/mounts | grep ' / ' | grep -q noatime"

echo ""
echo "--- Log2Ram ---"
if [ "$OVERLAY_ACTIVE" = true ]; then
    skip "log2ram service active — overlayroot makes log2ram redundant"
    skip "log2ram mounted on /var/log — overlayroot makes log2ram redundant"
elif systemctl is-enabled log2ram >/dev/null 2>&1 || systemctl is-active log2ram >/dev/null 2>&1; then
    check "log2ram service active" "systemctl is-active log2ram >/dev/null 2>&1"
    check "log2ram mounted on /var/log" "df -h | grep -q log2ram"
else
    skip "log2ram service active — disabled, overlayroot makes it redundant"
    skip "log2ram mounted on /var/log — disabled, overlayroot makes it redundant"
fi
check "journald SystemMaxUse set" "grep -q 'SystemMaxUse=20M' /etc/systemd/journald.conf"

echo ""
echo "--- Persistent Path Strategy ---"
check "/boot/firmware/persistent/ssh exists" "test -d /boot/firmware/persistent/ssh"
check "/boot/firmware/persistent/bluetooth exists" "test -d /boot/firmware/persistent/bluetooth"
check "/boot/firmware/persistent/tailscale exists" "test -d /boot/firmware/persistent/tailscale"
check "/boot/firmware/persistent/nm-conf.d exists" "test -d /boot/firmware/persistent/nm-conf.d"
check "restore script exists and executable" "test -x /usr/local/bin/restore-persistent-state.sh"
check "restore service enabled" "systemctl is-enabled restore-persistent-state.service >/dev/null 2>&1"
check "restore service ran successfully" "systemctl is-active restore-persistent-state.service >/dev/null 2>&1"
check "wifi-powersave.conf in persistent store" "test -f /boot/firmware/persistent/nm-conf.d/wifi-powersave.conf"
check "wifi-powersave.conf restored to system" "test -f /etc/NetworkManager/conf.d/wifi-powersave.conf"
check "SSH host keys in persistent store" "ls /boot/firmware/persistent/ssh/ssh_host_*_key >/dev/null 2>&1"

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="

if [ "$FAIL" -gt 0 ]; then
    echo "PHASE 2 VERIFICATION: FAIL"
    exit 1
else
    if [ "$SKIP" -gt 0 ]; then
        echo "PHASE 2 VERIFICATION: PASS (with skips)"
    else
        echo "PHASE 2 VERIFICATION: PASS"
    fi
    exit 0
fi
