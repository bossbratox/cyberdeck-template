#!/bin/bash
# Deploy to: /etc/profile.d/motd.sh on Pi
#
# Then make executable:
#   sudo chmod +x /etc/profile.d/motd.sh
#
# What this does:
#   Prints branded MOTD on every interactive login.
#   Shows greeting, date/time, location, and WiFi network.

# Clear screen so MOTD + prompt start at the top of the display.
# On the 15-row fbterm terminal, every line counts.
printf '\e[H\e[J'

DATETIME=$(date '+%B %d, %Y %H:%M')
WIFI=$(nmcli -t -f NAME connection show --active 2>/dev/null | head -1)

# Colors use 16-color SGR (fbterm silently drops 256-color).
#   \e[35m = slot 5 = deep pink
#   \e[97m = slot 15 = white
printf '\e[97m'
printf '%s\n' "$DATETIME"
printf '%s\n' "$(cat /etc/timezone 2>/dev/null || echo "unknown")"
printf '%s\n' "${WIFI:-not connected}"
printf '\e[1;35m'
echo "${MOTD_GREETING:-welcome to cyberdeck}"
printf '\e[0m\e[97m'

# Overlay status (Phase 5 — D-07)
if mountpoint -q /media/root-ro 2>/dev/null; then
    printf '\e[35mFS:  \e[97mread-only (overlay active)\n'
else
    printf '\e[1;31m*** OVERLAY UNLOCKED — ROOT IS WRITABLE ***\e[0m\e[97m\n'
fi
