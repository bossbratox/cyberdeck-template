#!/bin/bash
# Cyberdeck runtime boot optimizations
# Run on the Pi after overlayroot is enabled (or during an unlock session).
#
# What this does:
#   - Disables log2ram (redundant under overlayroot; /var/log is already tmpfs-backed)
#   - Masks rpc-statd-notify.service (saves ~100ms if nfs-common is installed but unused)
#   - Cleans up stale /var/hdd.log bind mounts left by previous log2ram runs
#
# Safe to run multiple times — all changes are idempotent.
# No-op if optimizations are already applied.

set -euo pipefail

echo "=== cyberdeck boot optimizations ==="
echo ""

# 1. Disable log2ram — overlayroot already keeps /var/log in a tmpfs overlay.
# log2ram additionally tries to sync logs to /var/hdd.log, which becomes
# read-only under overlayroot, causing a 2-minute boot timeout.
if systemctl is-enabled log2ram.service >/dev/null 2>&1 || \
   systemctl is-active log2ram.service >/dev/null 2>&1; then
    echo "--- disabling log2ram (redundant with overlayroot) ---"
    sudo systemctl disable --now log2ram.service 2>/dev/null || true
    sudo systemctl disable --now log2ram-daily.timer 2>/dev/null || true
    if mountpoint -q /var/hdd.log 2>/dev/null; then
        echo "unmounting stale /var/hdd.log bind mount..."
        sudo umount /var/hdd.log 2>/dev/null || true
    fi
    echo "log2ram disabled"
else
    echo "log2ram already disabled — skipping"
fi

# 2. Mask unnecessary NFS peer-notification service.
# nfs-common is often pulled in as a dependency but the cyberdeck has no NFS mounts.
# rpc-statd-notify adds ~100ms to boot for zero benefit.
if ! systemctl show --property=LoadState rpc-statd-notify.service 2>/dev/null | grep -q "masked"; then
    echo "--- masking rpc-statd-notify.service (no NFS in use) ---"
    sudo systemctl mask rpc-statd-notify.service
    echo "rpc-statd-notify masked"
else
    echo "rpc-statd-notify already masked — skipping"
fi

# 3. Set CPU scaling governor to powersave.
# Raspberry Pi defaults to 'ondemand' or 'schedutil' which can boost to 1.4GHz
# for burst workloads. The cyberdeck UI is latency-insensitive; powersave
# locks at minimum frequency (~600MHz) for a significant battery saving.
echo "--- setting CPU governor to powersave ---"
_gov_ok=0
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    if [ -f "$gov" ]; then
        echo powersave > "$gov" 2>/dev/null && _gov_ok=1 || true
    fi
done
if [ "$_gov_ok" -eq 1 ]; then
    echo "CPU governor: powersave ($(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo unknown) kHz)"
else
    echo "CPU governor: could not set (no cpufreq? kernel config?)"
fi

# 4. Enable WiFi power management via iw (kernel-level, immediate).
# NetworkManager's wifi-powersave.conf handles this persistently at NM level,
# but iw sets it unconditionally so it takes effect before NM starts.
echo "--- enabling WiFi power management ---"
if command -v iw >/dev/null 2>&1; then
    _iface=$(iw dev 2>/dev/null | awk '/Interface/{print $2; exit}')
    if [ -n "$_iface" ]; then
        iw dev "$_iface" set power_save on 2>/dev/null && \
            echo "WiFi power_save on ($iface)" || \
            echo "WiFi power_save: set failed (may already be on)"
    else
        echo "WiFi power_save: no wireless interface found"
    fi
else
    echo "WiFi power_save: iw not found"
fi

echo ""
echo "=== optimizations applied ==="
if command -v systemd-analyze >/dev/null 2>&1; then
    echo "current boot time:"
    systemd-analyze 2>/dev/null || true
fi
echo ""
echo "reboot to confirm improved boot time."
