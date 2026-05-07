# Storage & Power

SD card protection, persistent state strategy, OverlayFS lockdown, and power management. Deploy in order: power → SD protection → persistent paths → overlayFS.

---

## 1. Power Management

CPU governor, display blanking, WiFi power-save off (for SSH stability).

```bash
sudo apt update
sudo apt install -y cpufrequtils
```

### CPU governor (conservative)

```bash
sudo cp config/etc-default-cpufrequtils /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # conservative
```

### Display blanking (5 min idle)

Uses `setterm` (DPMS unreliable on DSI panels):

```bash
sudo cp config/etc-systemd-console-blanking.service /etc/systemd/system/console-blanking.service
sudo systemctl daemon-reload
sudo systemctl enable --now console-blanking.service
```

### WiFi power-save off

```bash
sudo mkdir -p /etc/NetworkManager/conf.d/
sudo cp config/etc-networkmanager-wifi-powersave.conf /etc/NetworkManager/conf.d/wifi-powersave.conf
sudo systemctl restart NetworkManager
iw wlan0 get power_save   # off
```

**OverlayFS note:** This file lives on root ext4 — under overlayFS it disappears on every reboot. See "Persistent paths" below to seed it on `/boot/firmware/persistent/nm-conf.d/`.

---

## 2. SD Card Protection (noatime + Log2Ram)

### Verify noatime (default on Bookworm)

```bash
cat /proc/mounts | grep ' / ' | grep noatime
```

If missing: edit `/etc/fstab` root line to `defaults,noatime`, then `sudo mount -o remount /`.

### Cap journald BEFORE installing Log2Ram

If `/var/log` exceeds 40MB when Log2Ram first starts, it fails silently.

```bash
# Set SystemMaxUse=20M in [Journal] section
sudo nano /etc/systemd/journald.conf

sudo journalctl --vacuum-size=32M
sudo systemctl restart systemd-journald
journalctl --disk-usage   # under 20M
du -sh /var/log           # MUST be under 40M
```

### Install Log2Ram

```bash
echo "deb [signed-by=/usr/share/keyrings/azlux-archive-keyring.gpg] http://packages.azlux.fr/debian/ bookworm main" \
  | sudo tee /etc/apt/sources.list.d/azlux.list
sudo wget -O /usr/share/keyrings/azlux-archive-keyring.gpg https://azlux.fr/repo.gpg
sudo apt update && sudo apt install -y log2ram rsync

sudo cp config/etc-log2ram.conf /etc/log2ram.conf
sudo reboot
```

After reboot:

```bash
df -h | grep log2ram          # 40M  /var/log
mount | grep log2ram          # type tmpfs
systemctl is-active log2ram   # active
```

If Log2Ram doesn't show in `df -h`: `/var/log` exceeded 40MB before install. Vacuum further (`--vacuum-size=10M`), reboot.

**After enabling overlayFS, disable Log2Ram** (it becomes redundant + actively breaks):

```bash
sudo systemctl disable --now log2ram.service log2ram-daily.timer
```

---

## 3. Persistent Paths Strategy

Under overlayFS, root ext4 becomes read-only. Services like sshd, bluetoothd, NetworkManager need their state on ext4 at startup. Solution: store on `/boot/firmware/persistent/` (FAT32, stays writable), copy to ext4 paths via systemd oneshot before dependent services start.

| Persistent source | Destination | Service |
|-------------------|-------------|---------|
| `/boot/firmware/persistent/ssh/` | `/etc/ssh/` | ssh.service |
| `/boot/firmware/persistent/bluetooth.tar.gz` | `/var/lib/bluetooth/` | bluetooth.service |
| `/boot/firmware/persistent/nm-conf.d/` | `/etc/NetworkManager/conf.d/` | NetworkManager.service |
| `/boot/firmware/persistent/nm-connections.tar.gz` | `/etc/NetworkManager/system-connections/` | NetworkManager.service |
| `/boot/firmware/persistent/tailscale/` | `/var/lib/tailscale/` | tailscaled.service |
| `/boot/firmware/persistent/ssh-user/` | `~/.ssh/` | (user) |

FAT32 has no Unix permissions — mount with `uid=0,gid=0,umask=077`. Restore script applies `chmod` after copy.

### Setup

```bash
sudo mkdir -p /boot/firmware/persistent/{ssh,bluetooth,tailscale,nm-conf.d,ssh-user}

# Seed SSH host keys
sudo cp /etc/ssh/ssh_host_* /boot/firmware/persistent/ssh/

# Seed wifi-powersave.conf
sudo cp /etc/NetworkManager/conf.d/wifi-powersave.conf /boot/firmware/persistent/nm-conf.d/

# Archive WiFi profiles + BT pairings
sudo tar -czf /boot/firmware/persistent/nm-connections.tar.gz \
  -C /etc/NetworkManager/system-connections .
sudo tar -czf /boot/firmware/persistent/bluetooth.tar.gz -C /var/lib/bluetooth .

# Deploy restore script + service
sudo cp config/usr-local-bin-restore-persistent-state.sh /usr/local/bin/restore-persistent-state.sh
sudo chmod +x /usr/local/bin/restore-persistent-state.sh
sudo cp config/etc-systemd-restore-persistent-state.service /etc/systemd/system/restore-persistent-state.service
sudo systemctl daemon-reload
sudo systemctl enable restore-persistent-state.service
```

### Verify after reboot

```bash
systemctl is-active restore-persistent-state          # active
ls -la /etc/ssh/ssh_host_*                            # original timestamps
test -f /etc/NetworkManager/conf.d/wifi-powersave.conf && echo PASS
systemctl list-dependencies ssh.service --before | grep restore
```

### Adding a new persistent path

1. Create source dir: `sudo mkdir -p /boot/firmware/persistent/<new-path>`
2. Add copy block in `/usr/local/bin/restore-persistent-state.sh`:
   ```bash
   if [ -d "$PERSIST/<new-path>" ]; then
       mkdir -p /target/path/on/ext4
       cp -a "$PERSIST/<new-path>/." /target/path/on/ext4/
   fi
   ```
3. Add the dependent service to `Before=` in the systemd unit.
4. `sudo systemctl daemon-reload`.

### overlayFS + raspi-config bug

**Do not use `raspi-config` to enable overlayFS.** Per Bookworm bug #137, raspi-config marks ALL partitions read-only including `/boot/firmware`, breaking the entire persistent path strategy. Use the `overlayroot` package method below instead.

---

## 4. OverlayFS Lockdown

Final hardening step. Root ext4 becomes copy-on-write — runtime writes go to a tmpfs overlay, vanishing on reboot. Survives hard power cuts without SD corruption.

**Strict sequence — don't skip soak/snapshot. A bad enable means reflashing from snapshot.**

### Disable swap (D-04)

SD card must not be used as swap.

```bash
sudo systemctl disable --now dphys-swapfile
sudo swapoff -a
sudo apt remove --purge -y dphys-swapfile

free -h | grep Swap     # 0B
cat /proc/swaps         # empty
```

### Install overlayroot

```bash
sudo apt update
sudo apt install -y overlayroot
dpkg -l overlayroot | grep '^ii'    # PASS
```

If `update-initramfs` errors during install (Bookworm initramfs-tools bug): check `/var/log/apt/term.log`. If the final initramfs update succeeded despite warnings, proceed.

### Deploy config files (DON'T reboot yet)

```bash
sudo cp config/etc-overlayroot-local.conf /etc/overlayroot.local.conf

sudo cp config/usr-local-bin-cyberdeck-update /usr/local/bin/cyberdeck-update
sudo chmod +x /usr/local/bin/cyberdeck-update

sudo cp config/usr-local-bin-cyberdeck-update-apt.sh /usr/local/bin/cyberdeck-update-apt.sh
sudo chmod +x /usr/local/bin/cyberdeck-update-apt.sh

sudo cp config/etc-systemd-cyberdeck-update-apt.service /etc/systemd/system/cyberdeck-update-apt.service

sudo cp config/usr-local-bin-overlay-killswitch.sh /usr/local/bin/overlay-killswitch.sh
sudo chmod +x /usr/local/bin/overlay-killswitch.sh

sudo cp config/etc-systemd-overlay-killswitch.service /etc/systemd/system/overlay-killswitch.service

sudo systemctl daemon-reload
sudo systemctl enable cyberdeck-update-apt.service overlay-killswitch.service

sudo cp config/etc-profile.d-motd.sh /etc/profile.d/motd.sh
sudo chmod +x /etc/profile.d/motd.sh
```

**Hold during soak period:**

```bash
echo 'overlayroot=disabled' | sudo tee /etc/overlayroot.local.conf
```

### Soak (2-3 sessions)

Catch persistence paths the strategy missed.

```bash
sudo touch /tmp/soak-marker
# Use device normally for a session, then:
sudo find / -newer /tmp/soak-marker -xdev 2>/dev/null \
  | grep -v -E '^(/proc|/sys|/dev|/tmp|/run|/var/log|/var/tmp|/home)' \
  | sort
```

Expected (safe): `/var/cache/apt/*`, `/var/lib/logrotate/*`, `/var/lib/systemd/*`.
Unexpected = new persistent path needed (see Section 3).

### Snapshot

Recovery baseline. Stream to a remote server:

```bash
sudo dd if=/dev/mmcblk0 bs=4M status=progress \
  | gzip -1 \
  | ssh <YOUR_USER>@<YOUR_BACKUP_HOST> "cat > /backup/cyberdeck-$(date +%Y%m%d).img.gz"

ssh <YOUR_USER>@<YOUR_BACKUP_HOST> "ls -lh /backup/cyberdeck-*.img.gz"
# 3-5GB compressed for a 16GB card
```

**Do not enable overlay until snapshot is confirmed.**

### Enable overlay

Pre-flight: all verify-phase tests pass, soak clean, snapshot confirmed, swap removed, all persistent paths present.

```bash
echo 'overlayroot="tmpfs:recurse=0"' | sudo tee /etc/overlayroot.local.conf
sudo reboot
```

After reboot:

```bash
mountpoint -q /media/root-ro && echo "OVERLAY ACTIVE" || echo "OVERLAY DISABLED"
mount | grep overlay

# /boot/firmware must still be writable
touch /boot/firmware/.write-test && rm /boot/firmware/.write-test && echo "FAT32 WRITABLE"

# Persistent state survived
systemctl is-active restore-persistent-state
ls /etc/ssh/ssh_host_*_key
tailscale status
```

### Updates under overlay

One command, two reboots:

```bash
sudo cyberdeck-update
```

What happens: writes flag to `/boot/firmware/cyberdeck-update.flag`, sets `overlayroot=disabled`, reboots; `cyberdeck-update-apt.service` detects flag, runs `apt upgrade`, re-enables overlay, removes flag, reboots.

Monitor:

```bash
journalctl -u cyberdeck-update-apt.service -f
```

### Manual unlock (config changes)

```bash
echo 'overlayroot=disabled' | sudo tee /etc/overlayroot.local.conf
sudo reboot
# ... make changes ...
echo 'overlayroot="tmpfs:recurse=0"' | sudo tee /etc/overlayroot.local.conf
sudo reboot
```

For simple file edits without reboot:

```bash
sudo overlayroot-chroot
# ... edit files in lower (real) ext4 ...
exit
```

### Recovery

**FAT32 kill-switch (works from any OS):**
1. Power off, remove SD card
2. Insert into any computer (FAT32 boot partition shows up as removable drive)
3. Create empty file `overlay.disable` in the partition root (no `.txt` extension on Windows)
4. Re-insert into Pi, power on
5. `overlay-killswitch.service` detects flag, disables overlay, reboots
6. Pi boots writable — fix what broke
7. `rm /boot/firmware/overlay.disable` then re-enable overlay normally

**Direct edit (Linux machine with ext4):**
Mount the ext4 root partition, edit `/etc/overlayroot.local.conf` to `overlayroot=disabled`, unmount, boot.

**Full reflash from snapshot:**
```bash
ssh <YOUR_USER>@<YOUR_BACKUP_HOST> "cat /backup/cyberdeck-YYYYMMDD.img.gz" \
  | gunzip -c | sudo dd of=/dev/sdX bs=4M status=progress
```

### Troubleshooting

- **`/boot/firmware` is read-only after enable**: `recurse=0` not applied. Verify config has exactly `overlayroot="tmpfs:recurse=0"` (not `overlayroot="tmpfs"` without recurse). Use kill-switch to recover.
- **MOTD shows "OVERLAY UNLOCKED" after enable**: overlay didn't activate. Check `dmesg | grep overlay`. May need `sudo update-initramfs -u && sudo reboot`.
- **Kill-switch flag ignored**: `systemctl is-enabled overlay-killswitch.service`. Ensure file is in FAT32 root (not subdirectory) with no `.txt` extension.
