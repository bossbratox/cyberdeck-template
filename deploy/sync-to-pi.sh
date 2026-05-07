#!/bin/bash
# Sync cyberdeck config from repo to Pi over SSH.
#
# Usage:
#   bash deploy/sync-to-pi.sh                    # deploy to live system (ephemeral if overlay active)
#   bash deploy/sync-to-pi.sh --persist          # deploy to FAT32 persistent store (survives reboot)
#   bash deploy/sync-to-pi.sh --enable-overlay   # write overlayroot config + enable killswitch, then reboot
#   bash deploy/sync-to-pi.sh --test-killswitch  # set overlay.disable flag; reboot to trigger
#
# Requires: SSH access to <YOUR_USER>@cyberdeck.local (key-based auth, no password)
# Per D-11, D-12, D-13, D-14 from Phase 7 CONTEXT.md.

set -euo pipefail

PI="<YOUR_USER>@cyberdeck.local"
PERSIST="/boot/firmware/persistent"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-overlay}"
STAGING="$HOME/pet-assets-staging"

echo "=== cyberdeck deploy ==="
echo "target: $PI"
echo "mode:   $MODE"
echo ""

# Verify SSH connectivity
if ! ssh -o ConnectTimeout=5 "$PI" "true" 2>/dev/null; then
    echo "ERROR: cannot reach $PI -- check network/VPN"
    exit 1
fi

if [ "$MODE" = "--enable-overlay" ]; then
    echo "--- enable overlay ---"

    if ssh "$PI" "mountpoint -q /media/root-ro 2>/dev/null"; then
        echo "OverlayFS is already ACTIVE — nothing to do."
        echo "To test the killswitch: bash deploy/sync-to-pi.sh --test-killswitch"
        exit 0
    fi

    if ! ssh "$PI" "dpkg -l overlayroot 2>/dev/null | grep -q '^ii'"; then
        echo "ERROR: 'overlayroot' package not installed on Pi."
        echo "       SSH in and run: sudo apt install overlayroot"
        exit 1
    fi

    # Write config to ext4 (root is writable because overlay is inactive)
    scp "$REPO_DIR/config/etc-overlayroot-local.conf" "$PI:/tmp/overlayroot.local.conf"
    ssh "$PI" "sudo cp /tmp/overlayroot.local.conf /etc/overlayroot.local.conf"
    echo "overlayroot.local.conf deployed."

    # Deploy and enable killswitch service + script
    scp "$REPO_DIR/config/etc-systemd-overlay-killswitch.service" "$PI:/tmp/overlay-killswitch.service"
    scp "$REPO_DIR/config/usr-local-bin-overlay-killswitch.sh" "$PI:/tmp/overlay-killswitch.sh"
    ssh "$PI" "sudo cp /tmp/overlay-killswitch.service /etc/systemd/system/overlay-killswitch.service \
        && sudo cp /tmp/overlay-killswitch.sh /usr/local/bin/overlay-killswitch.sh \
        && sudo chmod +x /usr/local/bin/overlay-killswitch.sh \
        && sudo systemctl daemon-reload \
        && sudo systemctl enable overlay-killswitch.service"
    echo "overlay-killswitch: deployed and enabled."

    echo ""
    echo "Overlay activates on next boot:"
    echo "  ssh <YOUR_USER>@cyberdeck.local 'sudo reboot'"
    echo ""
    echo "After reboot, verify:"
    echo "  ssh <YOUR_USER>@cyberdeck.local 'mountpoint -q /media/root-ro && echo OVERLAY ACTIVE || echo OVERLAY DISABLED'"
    exit 0

elif [ "$MODE" = "--test-killswitch" ]; then
    echo "--- killswitch test ---"

    if ! ssh "$PI" "mountpoint -q /media/root-ro 2>/dev/null"; then
        echo "ERROR: OverlayFS is not active — killswitch only exercises the real path under overlay."
        echo "       Enable overlay first:"
        echo "         bash deploy/sync-to-pi.sh --enable-overlay"
        echo "         ssh <YOUR_USER>@cyberdeck.local 'sudo reboot'"
        exit 1
    fi

    ssh "$PI" "touch /boot/firmware/overlay.disable"
    echo "Flag set: /boot/firmware/overlay.disable"
    echo ""
    echo "Reboot to trigger the killswitch:"
    echo "  ssh <YOUR_USER>@cyberdeck.local 'sudo reboot'"
    echo ""
    echo "On boot, overlay-killswitch.service will:"
    echo "  1. Write 'overlayroot=disabled' to the real ext4 /etc/overlayroot.local.conf"
    echo "  2. Remove the flag"
    echo "  3. Reboot into writable root"
    echo ""
    echo "After the double-reboot, verify:"
    echo "  ssh <YOUR_USER>@cyberdeck.local 'cat /etc/overlayroot.local.conf'"
    echo "  # expected: overlayroot=disabled"
    echo ""
    echo "To re-enable overlay:"
    echo "  bash deploy/sync-to-pi.sh --enable-overlay"
    echo "  ssh <YOUR_USER>@cyberdeck.local 'sudo reboot'"
    exit 0

elif [ "$MODE" = "--persist" ]; then
    echo "--- persistent deploy (FAT32 store) ---"

    # Shared modules -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-shared"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_colors.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_touch.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_ssh.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_status.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/cyberdeck_colors.py /tmp/cyberdeck_touch.py /tmp/cyberdeck_ssh.py /tmp/cyberdeck_status.py $PERSIST/cyberdeck-shared/"

    # Chat TUI -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-chat"
    scp "$REPO_DIR/config/opt-cyberdeck-chat/chat_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/chat_tui.py $PERSIST/cyberdeck-chat/"

    # WiFi TUI -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-wifi"
    scp "$REPO_DIR/config/opt-cyberdeck-wifi/wifi_tui.py" "$PI:/tmp/wifi_tui.py"
    ssh "$PI" "sudo cp /tmp/wifi_tui.py $PERSIST/cyberdeck-wifi/"

    # BT TUI -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-bt"
    scp "$REPO_DIR/config/opt-cyberdeck-bt/bt_tui.py" "$PI:/tmp/bt_tui.py"
    ssh "$PI" "sudo cp /tmp/bt_tui.py $PERSIST/cyberdeck-bt/"

    # Dash TUI -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-dash"
    scp "$REPO_DIR/config/opt-cyberdeck-dash/dash_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/dash_tui.py $PERSIST/cyberdeck-dash/"

    # Reader TUI -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-reader"
    scp "$REPO_DIR/config/opt-cyberdeck-reader/reader_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/reader_tui.py $PERSIST/cyberdeck-reader/"

    # Pet -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-pet/fb_assets"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_main.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_draw.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_blitter.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_progression.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_friends.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_anim.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/pet_fb_*.py $PERSIST/cyberdeck-pet/"
    rsync -av --delete "$REPO_DIR/config/opt-cyberdeck-pet/fb_assets/" "$PI:$STAGING/"
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-pet/fb_assets && sudo cp -r $STAGING/* $PERSIST/cyberdeck-pet/fb_assets/ && rm -rf $STAGING"
    # Pet systemd service
    scp "$REPO_DIR/config/opt-cyberdeck-pet/systemd/cyberdeck-pet.service" "$PI:/tmp/cyberdeck-pet.service"
    ssh "$PI" "sudo cp /tmp/cyberdeck-pet.service $PERSIST/cyberdeck-pet/"

    # Shell daemon -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/cyberdeck-shell"
    scp "$REPO_DIR/config/opt-cyberdeck-shell/shell_daemon.py" "$PI:/tmp/shell_daemon.py"
    scp "$REPO_DIR/config/opt-cyberdeck-shell/cyberdeck_switch.py" "$PI:/tmp/cyberdeck_switch.py"
    scp "$REPO_DIR/config/opt-cyberdeck-shell/term_wrapper.py" "$PI:/tmp/term_wrapper.py"
    ssh "$PI" "sudo cp /tmp/shell_daemon.py /tmp/cyberdeck_switch.py /tmp/term_wrapper.py $PERSIST/cyberdeck-shell/"

    # .bash_profile -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/home-profile"
    scp "$REPO_DIR/config/dot-bash_profile" "$PI:/tmp/bash_profile"
    ssh "$PI" "sudo cp /tmp/bash_profile $PERSIST/home-profile/.bash_profile"

    # .fbtermrc -> persistent store (fbterm palette + cyberdeck theme)
    scp "$REPO_DIR/config/home-user-fbtermrc" "$PI:/tmp/fbtermrc"
    ssh "$PI" "sudo cp /tmp/fbtermrc $PERSIST/home-profile/.fbtermrc"

    # Launcher scripts -> persistent store
    ssh "$PI" "sudo mkdir -p $PERSIST/launchers"
    scp "$REPO_DIR/config/usr-local-bin-chat" "$PI:/tmp/chat"
    scp "$REPO_DIR/config/usr-local-bin-bt" "$PI:/tmp/bt"
    scp "$REPO_DIR/config/usr-local-bin-dash" "$PI:/tmp/dash"
    scp "$REPO_DIR/config/usr-local-bin-read" "$PI:/tmp/read"
    scp "$REPO_DIR/config/usr-local-bin-reader" "$PI:/tmp/reader"
    scp "$REPO_DIR/config/usr-local-bin-wifi" "$PI:/tmp/wifi"
    scp "$REPO_DIR/config/usr-local-bin-term" "$PI:/tmp/term"
    scp "$REPO_DIR/config/usr-local-bin-vault-sync" "$PI:/tmp/vault-sync"
    ssh "$PI" "sudo cp /tmp/chat /tmp/bt /tmp/dash /tmp/read /tmp/reader /tmp/wifi /tmp/term /tmp/vault-sync $PERSIST/launchers/ && sudo cp /tmp/chat $PERSIST/launchers/c && sudo chmod +x $PERSIST/launchers/*"

    # Restore script -> persistent store (self-updating)
    scp "$REPO_DIR/config/usr-local-bin-restore-persistent-state.sh" "$PI:/tmp/restore-persistent-state.sh"
    ssh "$PI" "sudo cp /tmp/restore-persistent-state.sh $PERSIST/"

    # SSH config -> persistent store (user-owned)
    scp "$REPO_DIR/config/home-user-ssh-config" "$PI:/tmp/ssh-config"
    ssh "$PI" "sudo mkdir -p $PERSIST/ssh-user && sudo cp /tmp/ssh-config $PERSIST/ssh-user/config && sudo chown <YOUR_USER>:<YOUR_USER> $PERSIST/ssh-user/config 2>/dev/null || true"

    echo ""
    echo "Persistent store updated. Files will be restored on next boot."
    echo "To apply NOW, also run without --persist (overlay mode)."

else
    echo "--- live deploy (active immediately) ---"

    # Auto-disable overlay if active so writes land on real ext4.
    # /media/root-ro is the read-only lower layer; mounting the underlying
    # block device a second time inherits that read-only flag, so a plain
    # `mount + tee` silently fails. Use overlayroot-chroot instead — it
    # handles the remount and writes to the real ext4 reliably.
    if ssh "$PI" "mountpoint -q /media/root-ro 2>/dev/null"; then
        echo "overlay: ACTIVE — disabling for clean deploy (rebooting Pi)..."
        ssh "$PI" "sudo /usr/sbin/overlayroot-chroot bash -c 'echo overlayroot=disabled > /etc/overlayroot.local.conf'" \
            || { echo "ERROR: overlayroot-chroot disable write failed"; exit 1; }
        # Verify the disable actually landed on real ext4
        if ! ssh "$PI" "sudo /usr/sbin/overlayroot-chroot grep -q '^overlayroot=disabled' /etc/overlayroot.local.conf"; then
            echo "ERROR: /etc/overlayroot.local.conf on real ext4 did not get the disable directive"
            exit 1
        fi
        echo "overlay-disable directive verified on real ext4."
        ssh "$PI" "sudo reboot"
        echo "Waiting for Pi to come back up without overlay..."
        sleep 10
        until ssh -o ConnectTimeout=5 "$PI" "true" 2>/dev/null; do sleep 3; done
        if ssh "$PI" "mountpoint -q /media/root-ro 2>/dev/null"; then
            echo "ERROR: overlay is STILL active after reboot — disable did not take"
            exit 1
        fi
        echo "Pi is up — overlay disabled, ext4 is writable."
    else
        echo "overlay: INACTIVE — writes go directly to ext4"
    fi
    echo ""

    # Ensure target directories exist
    ssh "$PI" "sudo mkdir -p /opt/cyberdeck-shared /opt/cyberdeck-chat /opt/cyberdeck-dash /opt/cyberdeck-reader /opt/cyberdeck-pet /opt/cyberdeck-shell /opt/cyberdeck-wifi"

    # Required system packages (overlay disabled here, apt writes to real ext4)
    if ! ssh "$PI" "command -v pdftotext >/dev/null"; then
        echo "--- installing poppler-utils (pdftotext for reader) ---"
        ssh "$PI" "sudo apt-get update -qq && sudo apt-get install -y poppler-utils" \
            || echo "WARN: poppler-utils install failed (offline?). PDFs in reader will error."
    fi

    # Shared modules -> /opt/cyberdeck-shared/
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_colors.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_touch.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_ssh.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-shared/cyberdeck_status.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/cyberdeck_colors.py /tmp/cyberdeck_touch.py /tmp/cyberdeck_ssh.py /tmp/cyberdeck_status.py /opt/cyberdeck-shared/"

    # Chat TUI -> /opt/cyberdeck-chat/
    scp "$REPO_DIR/config/opt-cyberdeck-chat/chat_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/chat_tui.py /opt/cyberdeck-chat/"

    # WiFi TUI -> /opt/cyberdeck-wifi/
    scp "$REPO_DIR/config/opt-cyberdeck-wifi/wifi_tui.py" "$PI:/tmp/wifi_tui.py"
    ssh "$PI" "sudo cp /tmp/wifi_tui.py /opt/cyberdeck-wifi/"

    # BT TUI -> /opt/cyberdeck-bt/
    scp "$REPO_DIR/config/opt-cyberdeck-bt/bt_tui.py" "$PI:/tmp/bt_tui.py"
    ssh "$PI" "sudo cp /tmp/bt_tui.py /opt/cyberdeck-bt/"

    # Dash TUI -> /opt/cyberdeck-dash/
    scp "$REPO_DIR/config/opt-cyberdeck-dash/dash_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/dash_tui.py /opt/cyberdeck-dash/"

    # Reader TUI -> /opt/cyberdeck-reader/
    scp "$REPO_DIR/config/opt-cyberdeck-reader/reader_tui.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/reader_tui.py /opt/cyberdeck-reader/"

    # Shell daemon -> /opt/cyberdeck-shell/
    scp "$REPO_DIR/config/opt-cyberdeck-shell/shell_daemon.py" "$PI:/tmp/shell_daemon.py"
    scp "$REPO_DIR/config/opt-cyberdeck-shell/cyberdeck_switch.py" "$PI:/tmp/cyberdeck_switch.py"
    scp "$REPO_DIR/config/opt-cyberdeck-shell/term_wrapper.py" "$PI:/tmp/term_wrapper.py"
    ssh "$PI" "sudo cp /tmp/shell_daemon.py /tmp/cyberdeck_switch.py /tmp/term_wrapper.py /opt/cyberdeck-shell/"

    # .bash_profile -> /home/<YOUR_USER>/
    scp "$REPO_DIR/config/dot-bash_profile" "$PI:/tmp/bash_profile"
    ssh "$PI" "cp /tmp/bash_profile ~/.bash_profile"

    # .fbtermrc -> /home/<YOUR_USER>/ (fbterm palette: slot 5 deep pink #ff00cc, etc.)
    scp "$REPO_DIR/config/home-user-fbtermrc" "$PI:/tmp/fbtermrc"
    ssh "$PI" "cp /tmp/fbtermrc ~/.fbtermrc"

    # Pet -> /opt/cyberdeck-pet/
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_main.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_draw.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_blitter.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_progression.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_friends.py" "$PI:/tmp/"
    scp "$REPO_DIR/config/opt-cyberdeck-pet/pet_fb_anim.py" "$PI:/tmp/"
    ssh "$PI" "sudo cp /tmp/pet_fb_*.py /opt/cyberdeck-pet/ && sudo chmod 755 /opt/cyberdeck-pet/*.py"
    ssh "$PI" "sudo rm -rf /opt/cyberdeck-pet/__pycache__"
    rsync -av --delete "$REPO_DIR/config/opt-cyberdeck-pet/fb_assets/" "$PI:$STAGING/"
    ssh "$PI" "sudo mkdir -p /opt/cyberdeck-pet/fb_assets && sudo cp -r $STAGING/* /opt/cyberdeck-pet/fb_assets/ && rm -rf $STAGING"
    # Pet systemd service
    scp "$REPO_DIR/config/opt-cyberdeck-pet/systemd/cyberdeck-pet.service" "$PI:/tmp/cyberdeck-pet.service"
    ssh "$PI" "sudo cp /tmp/cyberdeck-pet.service ~/.config/systemd/user/cyberdeck-pet.service && systemctl --user daemon-reload"

    # Launcher scripts -> /usr/local/bin/
    scp "$REPO_DIR/config/usr-local-bin-chat" "$PI:/tmp/chat"
    scp "$REPO_DIR/config/usr-local-bin-bt" "$PI:/tmp/bt"
    scp "$REPO_DIR/config/usr-local-bin-dash" "$PI:/tmp/dash"
    scp "$REPO_DIR/config/usr-local-bin-read" "$PI:/tmp/read"
    scp "$REPO_DIR/config/usr-local-bin-reader" "$PI:/tmp/reader"
    scp "$REPO_DIR/config/usr-local-bin-wifi" "$PI:/tmp/wifi"
    scp "$REPO_DIR/config/usr-local-bin-term" "$PI:/tmp/term"
    scp "$REPO_DIR/config/usr-local-bin-vault-sync" "$PI:/tmp/vault-sync"
    ssh "$PI" "sudo cp /tmp/chat /tmp/bt /tmp/dash /tmp/read /tmp/reader /tmp/wifi /tmp/term /tmp/vault-sync /usr/local/bin/ && sudo ln -sf /usr/local/bin/chat /usr/local/bin/c && sudo chmod +x /usr/local/bin/chat /usr/local/bin/bt /usr/local/bin/dash /usr/local/bin/read /usr/local/bin/reader /usr/local/bin/wifi /usr/local/bin/term /usr/local/bin/vault-sync"

    # Vault persistent storage on real ext4 (/data/Vault).
    # Under overlayroot, ~/Vault would land on the 214M tmpfs upper layer and
    # fill instantly. Bind-mount /data/Vault -> ~/Vault so writes hit the SD.
    # Overlay is disabled here, so / IS the real fs — /data writes persist.
    ssh "$PI" "sudo mkdir -p /data/Vault && sudo chown <YOUR_USER>:<YOUR_USER> /data/Vault"
    # Migrate any pre-existing ~/Vault contents onto real fs (one-time).
    ssh "$PI" "if [ -d ~/Vault ] && ! mountpoint -q ~/Vault && [ -n \"\$(ls -A ~/Vault 2>/dev/null)\" ]; then sudo rsync -aH ~/Vault/ /data/Vault/ && sudo chown -R <YOUR_USER>:<YOUR_USER> /data/Vault && rm -rf ~/Vault/*; fi"
    ssh "$PI" "mkdir -p ~/Vault"
    # Live bind for this deploy session so the seed sync writes to real disk.
    ssh "$PI" "mountpoint -q ~/Vault || sudo mount --bind /data/Vault ~/Vault"

    # vault-mount.service: re-establishes the bind on every boot under overlay
    scp "$REPO_DIR/config/etc-systemd-vault-mount.service" "$PI:/tmp/vault-mount.service"
    ssh "$PI" "sudo cp /tmp/vault-mount.service /etc/systemd/system/vault-mount.service \
        && sudo systemctl daemon-reload \
        && sudo systemctl enable vault-mount.service"
    echo "vault-mount: deployed and enabled"

    echo "--- initial vault seed (this may take a minute) ---"
    ssh "$PI" "vault-sync" || echo "vault-sync: skipped (nextcloud unreachable)"

    # Restore script -> /usr/local/bin/
    scp "$REPO_DIR/config/usr-local-bin-restore-persistent-state.sh" "$PI:/tmp/restore-persistent-state.sh"
    ssh "$PI" "sudo cp /tmp/restore-persistent-state.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/restore-persistent-state.sh"

    # SSH config -> ~/.ssh/config
    scp "$REPO_DIR/config/home-user-ssh-config" "$PI:~/.ssh/config"
    ssh "$PI" "chmod 644 ~/.ssh/config"

    # Console blanking service
    scp "$REPO_DIR/config/etc-systemd-console-blanking.service" "$PI:/tmp/console-blanking.service"
    ssh "$PI" "sudo cp /tmp/console-blanking.service /etc/systemd/system/console-blanking.service \
        && sudo systemctl daemon-reload \
        && sudo systemctl enable console-blanking.service \
        && sudo systemctl start console-blanking.service"
    echo "console-blanking: deployed and started"

    # Apply power optimizations immediately (restore script handles boot persistence)
    echo "--- applying power optimizations ---"
    ssh "$PI" "for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do [ -f \"\$g\" ] && echo powersave | sudo tee \"\$g\" > /dev/null; done; echo CPU governor: powersave" 2>/dev/null || true
    ssh "$PI" "iface=\$(iw dev 2>/dev/null | awk '/Interface/{print \$2; exit}'); [ -n \"\$iface\" ] && sudo iw dev \"\$iface\" set power_save on && echo WiFi power_save on || true" 2>/dev/null || true

    echo ""
    echo "Live deploy complete. Running persist pass..."
    bash "$0" --persist

    # Re-enable overlay now that both passes are done
    if ssh "$PI" "dpkg -l overlayroot 2>/dev/null | grep -q '^ii'"; then
        echo ""
        echo "--- re-enabling overlay ---"
        scp "$REPO_DIR/config/etc-overlayroot-local.conf" "$PI:/tmp/overlayroot.local.conf"
        ssh "$PI" "sudo cp /tmp/overlayroot.local.conf /etc/overlayroot.local.conf"
        if ssh "$PI" "grep -q '^overlayroot=\"tmpfs' /etc/overlayroot.local.conf"; then
            echo "overlay re-enabled — reboot Pi to activate"
        else
            echo "ERROR: overlay re-enable directive missing from /etc/overlayroot.local.conf"
            exit 1
        fi
    fi

    # Restart shell daemon (pet will be managed by daemon)
    ssh "$PI" "sudo systemctl restart getty@tty1" 2>/dev/null || true
fi

# Post-deploy verify
echo ""
echo "--- verify ---"
ssh "$PI" "head -3 /opt/cyberdeck-chat/chat_tui.py"
ssh "$PI" "head -3 /opt/cyberdeck-dash/dash_tui.py"
ssh "$PI" "head -3 /opt/cyberdeck-reader/reader_tui.py"
ssh "$PI" "head -3 /opt/cyberdeck-wifi/wifi_tui.py"
# term TUI removed — plain fbterm used instead
ssh "$PI" "head -1 /opt/cyberdeck-shared/cyberdeck_colors.py"
ssh "$PI" "head -2 /opt/cyberdeck-pet/pet_fb_main.py"
echo ""
echo "deploy complete"
