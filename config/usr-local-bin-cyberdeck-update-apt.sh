#!/bin/bash
# Deploy to: /usr/local/bin/cyberdeck-update-apt.sh on Pi
#
# Then make executable:
#   sudo chmod +x /usr/local/bin/cyberdeck-update-apt.sh
#
# What this does:
#   Phase 2 of the two-reboot update workflow (D-05).
#   Runs automatically on boot when /boot/firmware/cyberdeck-update.flag exists.
#   Triggered by cyberdeck-update-apt.service (ConditionPathExists).
#
#   1. Verifies network connectivity (ping check)
#   2. Runs apt-get update && apt-get upgrade -y && apt-get autoremove -y
#   3. Re-enables overlay (writes overlayroot="tmpfs:recurse=0" to config)
#   4. Removes the flag file
#   5. Reboots (system returns to locked state)
#
# Per D-06: Scope is apt upgrade only. No config redeploy.

set -euo pipefail

FLAG=/boot/firmware/cyberdeck-update.flag

# Double-guard — ConditionPathExists in .service also gates this
[ -f "$FLAG" ] || exit 0

logger -t cyberdeck-update "Starting automated apt upgrade"

# Pre-flight network check with retry counter (RESEARCH.md Open Question 3)
# After 3 failed boot attempts, re-lock overlay to restore SD card protection.
RETRY_FILE=/boot/firmware/cyberdeck-update-retries
if ! ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
    RETRIES=$(cat "$RETRY_FILE" 2>/dev/null || echo 0)
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge 3 ]; then
        logger -t cyberdeck-update "No internet after $RETRIES attempts — re-locking overlay"
        echo 'overlayroot="tmpfs:recurse=0"' > /etc/overlayroot.local.conf
        rm -f "$FLAG" "$RETRY_FILE"
        systemctl reboot
        exit 0
    fi
    echo "$RETRIES" > "$RETRY_FILE"
    logger -t cyberdeck-update "No internet — attempt $RETRIES/3. Flag preserved for next boot."
    exit 1
fi
rm -f "$RETRY_FILE"

# Run apt upgrade
apt-get update
apt-get upgrade -y
apt-get autoremove -y

# Re-enable overlay for next boot
echo 'overlayroot="tmpfs:recurse=0"' > /etc/overlayroot.local.conf

# Remove flag so this service does not fire on subsequent boots
rm -f "$FLAG"

logger -t cyberdeck-update "Upgrade complete. Re-enabling overlay and rebooting."

# Second reboot — system returns to locked state
systemctl reboot
