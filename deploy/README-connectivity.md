# Connectivity: WiFi, Tailscale, SSH, Bluetooth

Everything that gets the cyberdeck talking to other machines: WiFi via nmtui, Tailscale mesh enrollment, SSH client config, and Bluetooth keyboard pairing + auto-reconnect.

**Deployment order:** WiFi → Tailscale → SSH → Bluetooth keyboard. Tailscale needs WiFi, SSH config benefits from Tailscale being up first.

---

## 1. WiFi (nmtui)

`nmtui` ships with Pi OS Bookworm. Connections persist in `/etc/NetworkManager/system-connections/` across reboots.

```bash
sudo nmtui
# "Activate a connection" → "Add" → enter SSID/password → OK
```

### Verify

```bash
nmcli connection show
nmcli dev status
ls /etc/NetworkManager/system-connections/  # .nmconnection files persist
```

### overlayFS note

Before enabling overlayFS, archive WiFi profiles to the persistent store:

```bash
sudo tar -czf /boot/firmware/persistent/nm-connections.tar.gz \
  -C /etc/NetworkManager/system-connections .
```

Re-run after adding new networks. Without this, profiles are lost on every boot under overlayFS.

---

## 2. Tailscale Mesh

The deck connects to your Tailscale tailnet (or self-hosted Headscale). Once enrolled, `ssh nextcloud` works from anywhere on the mesh — no public IP, no open firewall ports.

### Why the restore-script pattern

Tailscale uses SQLite WAL for state. FAT32 (`/boot/firmware`) doesn't support POSIX advisory locks → silent corruption or daemon startup failures. Solution: store state in `/boot/firmware/persistent/tailscale/` as a cold backup; the restore script copies it to `/var/lib/tailscale/` (ext4) at boot before `tailscaled` starts.

### Install

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/bookworm.noarmor.gpg \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/bookworm.tailscale-keyring.list \
  | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update && sudo apt-get install -y tailscale

sudo cp config/etc-default-tailscaled /etc/default/tailscaled
```

### Restore-script ordering

```bash
sudo cp config/usr-local-bin-restore-persistent-state.sh /usr/local/bin/restore-persistent-state.sh
sudo chmod +x /usr/local/bin/restore-persistent-state.sh
sudo cp config/etc-systemd-restore-persistent-state.service /etc/systemd/system/restore-persistent-state.service
sudo systemctl daemon-reload
```

The service has `Before=tailscaled.service` so state restores before the daemon starts.

### Enroll

For Tailscale (default):

```bash
sudo tailscale up --hostname cyberdeck
# Open the URL it prints, log in
```

For Headscale (self-hosted):

```bash
# On your headscale server:
headscale preauthkeys create -u <USER> --reusable

# On the Pi:
sudo tailscale up --login-server https://<HEADSCALE_URL> --authkey <PREAUTHKEY> --hostname cyberdeck
```

### Verify + persist

```bash
tailscale status
tailscale ping <some-peer>

# Cold backup to FAT32 (do this immediately after successful enrollment)
sudo cp -a /var/lib/tailscale/. /boot/firmware/persistent/tailscale/
```

If Tailscale state is ever updated (re-enrollment), re-run the cold backup.

### Disable key expiry (Headscale only)

Without this, the cyberdeck node expires and loses mesh connectivity. Edit `/etc/headscale/config.yaml`:

```yaml
node:
  expiry: 0
```

Then `sudo systemctl restart headscale`.

---

## 3. SSH Client

Sets up `~/.ssh/config` with host aliases for your servers (Tailscale primary + public-IP fallbacks). Keys live in `/boot/firmware/persistent/ssh-user/` so they survive overlayFS.

**Security:** SSH keys must NEVER be committed. The repo template only has placeholders; you copy real keys at deploy time.

### Persistent store + keys

```bash
sudo mkdir -p /boot/firmware/persistent/ssh-user
```

From your host machine (not the Pi):

```bash
scp ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub <YOUR_USER>@<PI_IP>:/tmp/
```

On the Pi:

```bash
sudo mv /tmp/id_ed25519 /tmp/id_ed25519.pub /boot/firmware/persistent/ssh-user/
```

Restore script applies correct perms (`700` dir, `600` private key, `644` public).

### Fill in SSH config

```bash
cp config/home-user-ssh-config config/home-user-ssh-config.local
# Edit: replace every <YOUR_*> placeholder with real values
```

| Placeholder | Value |
|-------------|-------|
| `<YOUR_*_TAILSCALE_IP>` | run `tailscale ip` on each host |
| `<YOUR_*_PUBLIC_IP>` | `curl -4 ifconfig.me` on each host |
| `<YOUR_SSH_USER>` | non-root SSH user |

Add the `.local` to `.gitignore`:

```bash
echo "config/home-user-ssh-config.local" >> .gitignore
```

Copy to persistent store:

```bash
sudo cp config/home-user-ssh-config.local /boot/firmware/persistent/ssh-user/config
sudo /usr/local/bin/restore-persistent-state.sh
```

### Verify

```bash
ssh -o BatchMode=yes nextcloud whoami    # Returns your SSH user
ls -la ~/.ssh/                            # 700 dir, 600 key, 644 pub
```

---

## 4. Bluetooth Keyboard

Pairs a BT keyboard and configures auto-connect at boot via systemd.

**Single USB port constraint:** The Pi 3A+ has one USB port. Pair over an SSH session from another machine — you can't use a wired keyboard during pairing.

### Pair via bluetoothctl

```bash
ssh <YOUR_USER>@<PI_IP>
bluetoothctl
```

Inside bluetoothctl:

```
power on
agent on
default-agent
scan on
```

Put the keyboard into pairing mode (hold pairing button until LED blinks rapidly). Watch for `[NEW] Device AA:BB:CC:DD:EE:FF`. Then:

```
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
quit
```

Note the MAC: `bluetoothctl devices`.

### Deploy auto-reconnect service

Edit `config/etc-systemd-bt-keyboard.service` — replace `<YOUR_BBQ10_MAC>` with the MAC from above.

```bash
sudo cp config/etc-systemd-bt-keyboard.service /etc/systemd/system/bt-keyboard.service
sudo install -m 0755 config/usr-local-bin-bt-reconnect.sh /usr/local/bin/bt-reconnect
sudo systemctl daemon-reload
sudo systemctl enable --now bt-keyboard.service
```

### Persist pairing data

FAT32 can't store directory names with colons (BlueZ uses them). Use tar.gz:

```bash
sudo tar -czf /boot/firmware/persistent/bluetooth.tar.gz -C /var/lib/bluetooth .
```

Re-run after re-pairing.

### Verify

```bash
sudo reboot
# After ~30s reconnect:
journalctl -u bt-keyboard.service
systemctl is-active bt-keyboard.service  # active
```

### Reconnect (manual)

If keyboard drops and won't reconnect:

```bash
sudo systemctl stop bt-keyboard.service
bluetoothctl disconnect <YOUR_BBQ10_MAC>
bluetoothctl connect <YOUR_BBQ10_MAC>
sudo systemctl start bt-keyboard.service
```

Full re-pair (nuclear):

```bash
sudo systemctl stop bt-keyboard.service
bluetoothctl remove <YOUR_BBQ10_MAC>
sudo rm -rf "/var/lib/bluetooth/<YOUR_PI_BT_MAC>/<YOUR_BBQ10_MAC>"
sudo systemctl restart bluetooth
sleep 3
bluetoothctl scan on
# pair/trust/connect again
```

**GPM is permanently disabled.** It injects xterm mouse escape sequences that cause spurious F-key presses.

### Bluetooth TUI (`bt`)

Curses-based BT manager. No external Python deps.

```bash
sudo mkdir -p /opt/cyberdeck-bt
sudo cp config/opt-cyberdeck-bt/bt_tui.py /opt/cyberdeck-bt/bt_tui.py
sudo chmod +x /opt/cyberdeck-bt/bt_tui.py
sudo cp config/usr-local-bin-bt /usr/local/bin/bt
sudo chmod +x /usr/local/bin/bt
```

Launch: `bt`. Keys: `s` scan, `p` paired, `c`/Enter connect, `d` disconnect, `a` pair+trust, `t` trust, `r` remove, `q` quit.
