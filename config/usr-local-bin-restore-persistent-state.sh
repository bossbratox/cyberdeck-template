#!/bin/bash
# Deploy to: /usr/local/bin/restore-persistent-state.sh on Pi
#
# Then make executable:
#   sudo chmod +x /usr/local/bin/restore-persistent-state.sh
#
# What this does:
#   Copies persistent state from /boot/firmware/persistent/ (FAT32, always
#   writable under overlayFS) to ext4 system paths at boot. Run by the
#   restore-persistent-state.service systemd unit before ssh, bluetooth,
#   and NetworkManager start.
#
# Why: Under overlayFS (Phase 5), the root ext4 partition is read-only.
# /boot/firmware stays writable. This script copies persistent data
# from FAT32 to ext4 before dependent services start.
#
# FAT32 constraint: No Unix permissions on FAT32. Files inherit mount
# umask (077). After copy to ext4, chmod restores correct permissions.
#
# Verify service ordering after enabling:
#   systemctl list-dependencies ssh.service --before
#   -> should show restore-persistent-state.service
#
# Note: Assumption A2 from research — verify boot-firmware.mount unit name:
#   systemctl status boot-firmware.mount

set -euo pipefail

PERSIST=/boot/firmware/persistent

# SSH host keys
if [ -d "$PERSIST/ssh" ]; then
    cp -a "$PERSIST/ssh/." /etc/ssh/
    chmod 600 /etc/ssh/ssh_host_*_key 2>/dev/null || true
    chmod 644 /etc/ssh/ssh_host_*_key.pub 2>/dev/null || true
fi

# Bluetooth pairings (stored as tar.gz — FAT32 can't hold MAC-address dir names with colons)
if [ -f "$PERSIST/bluetooth.tar.gz" ]; then
    mkdir -p /var/lib/bluetooth
    tar -C /var/lib/bluetooth -xzf "$PERSIST/bluetooth.tar.gz"
    chmod 700 /var/lib/bluetooth
    find /var/lib/bluetooth -type d -exec chmod 700 {} +
    find /var/lib/bluetooth -type f -exec chmod 600 {} +
fi

# NetworkManager conf.d (wifi-powersave.conf per D-05, resolves Phase 1 WR-04)
if [ -d "$PERSIST/nm-conf.d" ]; then
    mkdir -p /etc/NetworkManager/conf.d
    cp -a "$PERSIST/nm-conf.d/." /etc/NetworkManager/conf.d/
    chmod 644 /etc/NetworkManager/conf.d/*.conf 2>/dev/null || true
fi

# NetworkManager wifi profiles (stored as tar.gz — FAT32 can't hold emoji filenames)
if [ -f "$PERSIST/nm-connections.tar.gz" ]; then
    mkdir -p /etc/NetworkManager/system-connections
    tar -C /etc/NetworkManager/system-connections -xzf "$PERSIST/nm-connections.tar.gz"
    chmod 600 /etc/NetworkManager/system-connections/*.nmconnection 2>/dev/null || true
fi

# Polkit rules (allow user to manage wifi without sudo)
if [ -f "$PERSIST/polkit-network.pkla" ]; then
    mkdir -p /etc/polkit-1/localauthority/50-local.d
    cp "$PERSIST/polkit-network.pkla" /etc/polkit-1/localauthority/50-local.d/10-network.pkla
    chmod 644 /etc/polkit-1/localauthority/50-local.d/10-network.pkla
fi

# Tailscale state (Phase 3 — NET-02)
# SQLite WAL mode requires POSIX locks — FAT32 cannot provide them.
# State lives on FAT32 persistent store, copied to ext4 before tailscaled starts.
if [ -d "$PERSIST/tailscale" ] && [ "$(ls -A $PERSIST/tailscale 2>/dev/null)" ]; then
    mkdir -p /var/lib/tailscale
    cp -a "$PERSIST/tailscale/." /var/lib/tailscale/
    chmod 700 /var/lib/tailscale
    chmod 600 /var/lib/tailscale/tailscaled.state 2>/dev/null || true
fi

# User SSH keys and config (Phase 3 — NET-03, NET-04)
# ed25519 keypair + config with host aliases. Per D-06, user copies existing
# keypair to persistent store; this restores it to ~/.ssh/ at boot.
if [ -d "$PERSIST/ssh-user" ] && [ "$(ls -A $PERSIST/ssh-user 2>/dev/null)" ]; then
    USER_HOME=$(getent passwd 1000 | cut -d: -f6)
    USER_NAME=$(getent passwd 1000 | cut -d: -f1)
    mkdir -p "$USER_HOME/.ssh"
    cp -a "$PERSIST/ssh-user/." "$USER_HOME/.ssh/"
    chmod 700 "$USER_HOME/.ssh"
    chmod 600 "$USER_HOME/.ssh/id_ed25519" 2>/dev/null || true
    chmod 644 "$USER_HOME/.ssh/id_ed25519.pub" 2>/dev/null || true
    chmod 644 "$USER_HOME/.ssh/config" 2>/dev/null || true
    chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.ssh"
fi

# Launcher scripts and TUI code (Phase 7 -- CHAT-04)
# Deploy script writes launchers + TUI code to FAT32 persistent store.
# Restore them to ext4 at boot so overlayFS devices have current versions.
if [ -d "$PERSIST/launchers" ] && [ "$(ls -A $PERSIST/launchers 2>/dev/null)" ]; then
    cp -a "$PERSIST/launchers/." /usr/local/bin/
    chmod +x /usr/local/bin/chat /usr/local/bin/bt /usr/local/bin/dash /usr/local/bin/c 2>/dev/null || true
fi
if [ -d "$PERSIST/cyberdeck-chat" ]; then
    mkdir -p /opt/cyberdeck-chat
    cp -a "$PERSIST/cyberdeck-chat/." /opt/cyberdeck-chat/
fi
if [ -d "$PERSIST/cyberdeck-shared" ]; then
    mkdir -p /opt/cyberdeck-shared
    cp -a "$PERSIST/cyberdeck-shared/." /opt/cyberdeck-shared/
fi
if [ -d "$PERSIST/cyberdeck-dash" ]; then
    mkdir -p /opt/cyberdeck-dash
    cp -a "$PERSIST/cyberdeck-dash/." /opt/cyberdeck-dash/
fi

# Reader TUI code (Phase 9 -- READ-01..05)
if [ -d "$PERSIST/cyberdeck-reader" ]; then
    mkdir -p /opt/cyberdeck-reader
    cp -a "$PERSIST/cyberdeck-reader/." /opt/cyberdeck-reader/
fi

# Reader bookmarks (Phase 6 -- INFRA-03)
if [ -d "$PERSIST/reader-bookmarks" ]; then
    USER_HOME=$(getent passwd 1000 | cut -d: -f6)
    USER_NAME=$(getent passwd 1000 | cut -d: -f1)
    mkdir -p "$USER_HOME/.local/share/cyberdeck-reader/bookmarks"
    cp -a "$PERSIST/reader-bookmarks/." "$USER_HOME/.local/share/cyberdeck-reader/bookmarks/"
    chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.local/share/cyberdeck-reader"
fi

# Pet framebuffer app + assets (Phase 10 -- PET-01)
if [ -d "$PERSIST/cyberdeck-pet" ]; then
    mkdir -p /opt/cyberdeck-pet
    cp -a "$PERSIST/cyberdeck-pet/." /opt/cyberdeck-pet/
    chmod 755 /opt/cyberdeck-pet/*.py 2>/dev/null || true
    chmod -R 644 /opt/cyberdeck-pet/fb_assets/* 2>/dev/null || true
fi

# BT TUI code
if [ -d "$PERSIST/cyberdeck-bt" ]; then
    mkdir -p /opt/cyberdeck-bt
    cp -a "$PERSIST/cyberdeck-bt/." /opt/cyberdeck-bt/
fi

# WiFi TUI code
if [ -d "$PERSIST/cyberdeck-wifi" ]; then
    mkdir -p /opt/cyberdeck-wifi
    cp -a "$PERSIST/cyberdeck-wifi/." /opt/cyberdeck-wifi/
fi

# Term TUI code
if [ -d "$PERSIST/cyberdeck-term" ]; then
    mkdir -p /opt/cyberdeck-term
    cp -a "$PERSIST/cyberdeck-term/." /opt/cyberdeck-term/
fi

# Shell daemon (app switcher)
if [ -d "$PERSIST/cyberdeck-shell" ]; then
    mkdir -p /opt/cyberdeck-shell
    cp -a "$PERSIST/cyberdeck-shell/." /opt/cyberdeck-shell/
    chmod 755 /opt/cyberdeck-shell/*.py 2>/dev/null || true
fi

# User .bash_profile (launches shell daemon on tty1)
if [ -f "$PERSIST/home-profile/.bash_profile" ]; then
    USER_HOME=$(getent passwd 1000 | cut -d: -f6)
    USER_NAME=$(getent passwd 1000 | cut -d: -f1)
    cp "$PERSIST/home-profile/.bash_profile" "$USER_HOME/.bash_profile"
    chown "$USER_NAME:$USER_NAME" "$USER_HOME/.bash_profile"
fi

# User .fbtermrc (fbterm palette — slot 5 deep pink #ff00cc, slot 7 candy pink bg, etc.)
if [ -f "$PERSIST/home-profile/.fbtermrc" ]; then
    USER_HOME=$(getent passwd 1000 | cut -d: -f6)
    USER_NAME=$(getent passwd 1000 | cut -d: -f1)
    cp "$PERSIST/home-profile/.fbtermrc" "$USER_HOME/.fbtermrc"
    chown "$USER_NAME:$USER_NAME" "$USER_HOME/.fbtermrc"
fi

# CPU powersave governor — lock CPU at min freq (~600 MHz) for battery saving.
# The cyberdeck UI is latency-insensitive so the performance loss is invisible.
for _gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [ -f "$_gov" ] && echo powersave > "$_gov" 2>/dev/null || true
done

# WiFi power management — kernel-level belt-and-suspenders alongside NM conf.d.
_iface=$(iw dev 2>/dev/null | awk '/Interface/{print $2; exit}')
[ -n "$_iface" ] && iw dev "$_iface" set power_save on 2>/dev/null || true

# Console blanking: blank after 5 min idle, power off display after 6 min.
# Equivalent to console-blanking.service; inlined here so it survives overlayFS.
TERM=linux /usr/bin/setterm -blank 5 -powerdown 6 > /dev/tty1 2>/dev/null || true
