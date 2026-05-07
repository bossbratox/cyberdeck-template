#!/bin/bash
# Deploy to: /usr/local/bin/overlay-killswitch.sh on Pi
#
# Then make executable:
#   sudo chmod +x /usr/local/bin/overlay-killswitch.sh
#
# What this does:
#   Checks for /boot/firmware/overlay.disable at boot.
#   If found: disables overlayroot on the REAL ext4 filesystem
#   (not the overlay upper layer), removes the flag, reboots
#   into writable root.
#
#   Recovery use case (D-10):
#     1. Pull SD card from dead/broken cyberdeck
#     2. Insert into any computer (Windows/Mac/Linux)
#     3. Open the FAT32 boot partition (shows up as a drive)
#     4. Create an empty file called "overlay.disable"
#     5. Re-insert SD card into Pi, power on
#     6. Pi boots with writable root — fix whatever broke
#
# Triggered by: overlay-killswitch.service (ConditionPathExists)
# This script only runs when the flag file exists — zero overhead on normal boots.

set -euo pipefail

FLAG=/boot/firmware/overlay.disable

# Double-guard — ConditionPathExists in .service also gates this
[ -f "$FLAG" ] || exit 0

logger -t overlay-killswitch "Kill-switch flag detected at $FLAG — disabling overlay"

# Write overlayroot=disabled to the REAL ext4 filesystem.
# When overlay is active, / is an overlay mount — writes go to tmpfs and are
# lost on reboot. We must write to the lower (real) ext4 at /media/root-ro.
if mountpoint -q /media/root-ro 2>/dev/null; then
    # Overlay is active — remount lower FS read-write, write config, remount read-only
    mount -o remount,rw /media/root-ro
    echo 'overlayroot=disabled' > /media/root-ro/etc/overlayroot.local.conf
    mount -o remount,ro /media/root-ro
else
    # Overlay not active — write normally
    echo 'overlayroot=disabled' > /etc/overlayroot.local.conf
fi

# Remove flag so this doesn't fire again on subsequent boots
rm -f "$FLAG"

logger -t overlay-killswitch "Overlay disabled. Rebooting into writable root."

# Reboot into writable state
systemctl reboot
