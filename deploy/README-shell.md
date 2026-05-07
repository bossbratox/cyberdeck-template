# Shell: Boot UX & Daily Usage

Auto-login + tmux on boot, plus the daily-use reference for all the apps.

---

## 1. Boot UX (autologin + tmux)

After this guide, the Pi boots directly into a tmux session named `main` — no login prompt.

### Auto-login on tty1

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d/
sudo cp config/etc-systemd-getty-autologin.conf \
    /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo systemctl daemon-reload
```

The deployed file contains `--autologin <YOUR_USER>` — replace with your actual username:

```bash
sudo sed -i 's/<YOUR_USER>/your_actual_username/g' \
    /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo systemctl daemon-reload
```

### tmux config

```bash
cp config/tmux.conf ~/.tmux.conf
```

### tmux guard (append to ~/.bashrc)

**APPEND only — don't replace `~/.bashrc`.** The guard auto-launches tmux on interactive login but prevents nesting.

```bash
cat config/bashrc-tmux-guard.sh >> ~/.bashrc
tail -10 ~/.bashrc    # verify
```

### Verify

```bash
sudo reboot
```

After reboot, inside the auto-launched session:

```bash
echo $TMUX                       # non-empty
tput colors                      # 256
tmux display-message -p '#S'     # main
```

Open a new tmux window (`Ctrl-a c`):

```bash
echo $TMUX                       # still non-empty, no new session spawned
```

### Troubleshooting

- **Login prompt still appears**: `systemctl cat getty@tty1` should show `[Service]` from drop-in with `--autologin`. Verify `/etc/systemd/system/getty@tty1.service.d/autologin.conf` exists.
- **Blank screen on boot**: Don't mask `userconfig.service`. Check `systemctl status userconfig.service` — getty drop-in needs it to complete first.
- **Nested tmux**: Guard not in `.bashrc`. Re-append `bashrc-tmux-guard.sh`.
- **`tput colors` returns 8**: `~/.tmux.conf` should have `set -g default-terminal "tmux-256color"`. Reload: `tmux source-file ~/.tmux.conf`.

---

## 2. Daily Usage Reference

### App switching

| Key | App |
|-----|-----|
| **F1** | Pet (mermaid tamagotchi) |
| **F2** | Chat (LLM) |
| **F3** | Dash (server monitor) |
| **F4** | Reader (wiki / books) |
| **F5** | Bluetooth |
| **F6** | Wi-Fi |
| **F7** | Terminal (tmux shell) |

F-keys work directly from Pet, Chat, Dash, Bluetooth, Wi-Fi, Terminal. From Reader, press `q` to quit back to the pet first.

---

### Pet

#### Keys

| Key | Action |
|-----|--------|
| `f` | Feed |
| `c` | Clean |
| `s` | Sleep / Wake |
| `t` | Stats page |
| `b` | Change background |
| `o` | Change outfit (adult only) |
| `r` | Save now |
| `0` | Reset game (fresh egg) |
| `Tab` | Speedrun mode |
| `q` | Quit |

#### Touch

| Area | Action |
|------|--------|
| Tap mermaid | Play / comfort |
| Tap bottom-left | Feed |
| Tap bottom-center | Clean |
| Tap bottom-right | Sleep / Wake |
| Tap top-right "i" | Open stats |
| Tap anywhere on stats | Close stats |

#### Lifecycle

- **Egg** → tap 48 times to hatch (or 2s in speedrun)
- **Baby** → 24 feeds + 3 days real-time
- **Kid** → 24 feeds + 3 days
- **Adult** → permanent, unlocks outfits & backgrounds

Stats: hunger, happiness, energy, cleanliness, health. Auto-saves every 60s and on quit.

#### Deploying updated assets

Source art lives in `config/opt-cyberdeck-pet/fb_assets_source/`:

```bash
cd config/opt-cyberdeck-pet
python3 build_assets.py    # PNG → RGB565 .raw
bash ../../deploy/sync-to-pi.sh --persist
bash ../../deploy/sync-to-pi.sh
```

| Step | What it does |
|------|-------------|
| `build_assets.py` | Resizes source art, hyphens → underscores, generates `.raw` RGB565+alpha files |
| `sync-to-pi.sh --persist` | Copies to `/boot/firmware/persistent/cyberdeck-pet/fb_assets/` (FAT32, survives reboot) |
| `sync-to-pi.sh` | Copies to `/opt/cyberdeck-pet/fb_assets/` (live immediately) |

The deploy script stages assets under `~/pet-assets-staging` on the Pi (root filesystem) instead of `/tmp` — avoids tmpfs space exhaustion with large background PNGs.

---

### Chat

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `↑` / `↓` | Scroll history |
| `Ctrl+C` or `Ctrl+Q` | Quit |

---

### Dash

Live CPU / RAM / disk for all servers. Refreshes every 45 seconds.

| Key | Action |
|-----|--------|
| `q` | Quit |

---

### Reader

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate / scroll |
| `Enter` | Open file |
| `/` | Search |
| `PgUp` / `PgDn` | Fast scroll |
| `q` | Quit (returns to pet) |

---

### Bluetooth

| Key | Action |
|-----|--------|
| `s` | Scan |
| `p` | Show paired |
| `c` | Connect selected |
| `d` | Disconnect selected |
| `t` | Trust selected |
| `r` | Remove selected |
| `↑` / `↓` | Select |
| `q` | Quit |

---

### Wi-Fi

Whiptail menu: Connect (scan + select), Disconnect, Status. Use `↑` / `↓` / `Enter`.

---

### Terminal

Full tmux shell with scrollback, copy mode, mouse support. F1–F7 to switch apps.

> **Tip:** From Pet, press F5 (BT) or F6 (WiFi) first, then F7 to reach terminal. All other apps support F7 directly.

---

### Power

- **Hard power cut:** OverlayFS protects the SD card — no corruption
- **Persistent data:** `/boot/firmware/persistent/` (FAT32), restored on boot
- **Low battery:** if using a LiPo SHIM with GPIO low-battery signal, configure `cleanshutd`. USB battery banks have no GPIO signal — graceful shutdown isn't possible. Hard cuts are safe under overlayFS.
