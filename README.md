# 🌊 cyberdeck

> a pocket computer that lives in your bag and runs a fully customizable tamagotchi 🧜‍♀️

Raspberry Pi cyberdeck with a full TUI stack — no X11, no desktop, no nonsense. All UI is curses apps inside fbterm or direct framebuffer graphics. Runs on a USB battery bank with OverlayFS SD-card protection so hard power-offs don't corrupt anything.

The tamagotchi pet is **fully reskinnable** — swap in your own sprite art and she becomes whoever you want. Cat, robot, demon, whatever. See [custom art](#custom-art) for what files to make.

This repo is a template. Clone it, fill in your `<YOUR_*>` values, and deploy to your own Pi.

---

## hardware

| component | what |
|-----------|------|
| SBC | Raspberry Pi 3A+ (or any Pi — armv7l, RPi OS Lite Trixie) |
| display | 3.5" DSI panel, 640×480 framebuffer (`/dev/fb0`) |
| touchscreen | capacitive panel, evdev |
| keyboard | BBQ10 Bluetooth BLE HID-over-GATT (or any BT keyboard) |
| battery | USB battery bank |
| storage | microSD with OverlayFS protection |

---

## apps

| key | app | what it does |
|-----|-----|-------------|
| F1 | **term** | mint-green bash/tmux terminal |
| F2 | **chat** | LLM chat (OpenAI-compatible API, SSE streaming) |
| F3 | **pet** | mermaid tamagotchi — direct framebuffer renderer 🧜‍♀️ |
| F4 | **reader** | file browser + markdown/PDF reader |
| F5 | **dash** | server monitor — polls SSH hosts every 45s |
| F6 | **wifi** | wifi manager (nmcli wrapper) |
| F7 | **bt** | bluetooth manager (bluetoothctl wrapper) |

F-keys are intercepted at four layers: pet (evdev), `term_wrapper.py` (PTY escape parser), tmux (`bind -n F1..F7`), and all curses TUIs (`KEY_F1..F7` + fallback escape parser).

---

## architecture

```
tty1
└── shell_daemon.py           # session leader; owns the terminal
    ├── cyberdeck-pet.service # systemd user service; renders to fb0
    └── fbterm                # framebuffer terminal emulator
        ├── term_wrapper.py   # PTY fork; intercepts F-key escapes
        ├── chat_tui.py
        ├── reader_tui.py
        ├── dash_tui.py
        ├── bt_tui.py
        └── wifi_tui.py
```

App switching uses a Unix socket at `/run/user/{uid}/cyberdeck-shell.sock`. Any app calls `cyberdeck_switch.py SWITCH <app>` and the daemon handles the transition.

### shared libraries (`/opt/cyberdeck-shared/`)

| module | purpose |
|--------|---------|
| `cyberdeck_colors.py` | 8 curses color pairs, candy-pink fbterm palette |
| `cyberdeck_touch.py` | touch + trackpad listeners (EV_ABS / EV_REL), EVIOCGRAB, BT auto-reconnect |
| `cyberdeck_ssh.py` | SSH helper via ControlMaster multiplexing (<100ms after first call) |
| `cyberdeck_status.py` | shared status polling for dash |

---

## setup

### 1. customize your values

```bash
grep -r YOUR_ config/ deploy/
```

Every `<YOUR_*>` placeholder needs a real value. See [CUSTOMIZE.md](CUSTOMIZE.md).

Key things to fill in:
- Tailscale IPs for all your machines
- SSH server hostnames
- Vault sync remote path
- Your username and Pi hostname
- LLM API endpoint for chat

### 2. flash the Pi

```bash
# Raspberry Pi OS Lite (64-bit or 32-bit armv7l)
# Enable SSH in raspi-config
# Install Tailscale: https://tailscale.com/download/linux
# Install overlayroot: sudo apt install overlayroot fbterm python3-{curses,evdev}
```

### 3. deploy

```bash
# live deploy (writes to running system immediately)
bash deploy/sync-to-pi.sh

# deploy + write to FAT32 persistent store (survives overlayroot reboot)
bash deploy/sync-to-pi.sh --persist

# enable overlayroot SD card protection
bash deploy/sync-to-pi.sh --enable-overlay
```

Requires key-based SSH to the Pi. After deploy the Pi autologs into `dash` on tty1.

---

## overlayroot

Makes `/` copy-on-write — writes go to tmpfs, vanish on reboot. The persistent store is FAT32 at `/boot/firmware/persistent/`. `restore-persistent-state.service` copies it back to `/opt/`, `/usr/local/bin/`, etc. on every boot.

The deploy script handles enabling/disabling automatically — one command does live deploy + persist + re-enables overlay.

---

## pet lifecycle 🧜‍♀️

Renders via direct framebuffer blit (PNG → RGB565 raw → fb0). Save file: `~/.pet-save.json`.

| stage | trigger |
|-------|---------|
| egg | start |
| baby | tap egg + 3 days real-time |
| kid | 24 feeds + 3 days |
| adult | 24 feeds + 4 days — unlocks outfits, friends, backgrounds |

Stats: hunger, happiness, energy, cleanliness, health. Auto-saves every 60s and on quit.

Source art in `config/opt-cyberdeck-pet/fb_assets_source/`. After editing sprites:

```bash
cd config/opt-cyberdeck-pet
python3 build_assets.py   # PNG → RGB565 .raw
bash ../../deploy/sync-to-pi.sh
```

### custom art

All source files are **RGBA PNG** — transparency is required. Any input size works; `build_assets.py` resizes automatically. Missing files are skipped without errors, so you can replace just the pieces you want.

**character sprites — `mermaid-{mood}.png` + `mermaid-{mood}-blink.png`** (canvas: 240×336)

Each mood needs a base pose and an optional blink variant (same pose, eyes closed):

| file | when shown |
|------|-----------|
| `mermaid-happy.png` | default / good stats |
| `mermaid-sad.png` | low happiness |
| `mermaid-hungry.png` | low hunger |
| `mermaid-tired.png` | low energy |
| `mermaid-sick.png` | low health |
| `mermaid-dirty.png` | low cleanliness |
| `mermaid-clean.png` | after cleaning |
| `mermaid-excite.png` | interaction/feeding |
| `mermaid-pissed.png` | very neglected |
| `mermaid-sleep.png` | sleeping |
| `mermaid-wink.png` | treat received |

**lifecycle sprites** — same 240×336 canvas unless noted

| group | files needed |
|-------|-------------|
| egg (160×224) | `mermaid-egg.png`, `mermaid-egg-crack.png`, `mermaid-egg-hatch.png` + blinks |
| baby | `mermaid-baby.png` + variants: `happy`, `cry`, `excite`, `full`, `sleep`, `dirty` + blinks |
| kid | `mermaid-kid.png` + variants: `cry`, `excite`, `sleep`, `dirty` + blinks |

**outfits** — unlocked at adult stage, same 240×336 canvas

`mermaid-outfit-blue.png`, `mermaid-outfit-green.png`, `mermaid-outfit-galaxy.png`, `mermaid-outfit-rainbow.png` + blink variants

**backgrounds — `bg_{name}.png`** (640×480, fills the screen behind the pet)

`bg_atlantis`, `bg_beach`, `bg_castle`, `bg_coral`, `bg_lagoon`, `bg_night`, `bg_reef`, `bg_space`, `bg_sunset`

**friends — `friend-{name}.png`** (80×80, resized to 120×120)

`crab`, `dolphin`, `octopus`, `seahorse`, `starfish` — crab gets auto-rotated for perimeter walk, only one facing needed

**food — `food-{name}.png` + `food-{name}-eaten.png`** (80×80 animation, 48×48 menu icon)

`burger`, `cupcake`, `ice-cream`, `matcha`, `oyster`, `strawberry`, `sushi`

**treats — `treat-{name}.png`** (80×80)

`comb`, `crystal`, `fork`, `necklace`, `oyster`, `treasure`

**particles — `particle_{name}.png`** (64×64)

`particle_heart_pink.png`, `particle_heart_red.png`, `particle_heart_gold.png`

---

## vault sync

Bidirectional rsync between `~/Vault` on the Pi and a remote server (Nextcloud or any rsync target). Triggered automatically on wifi connect. Runs manually with `vault-sync`.

Configure `REMOTE`, `REMOTE_PATH`, and `LOCAL_PATH` in `config/usr-local-bin-vault-sync`.

---

## BBQ10 keyboard

BLE HID-over-GATT keyboard. If yours drops and won't reconnect:

```bash
sudo systemctl stop bt-keyboard.service
bluetoothctl disconnect <YOUR_BBQ10_MAC>
bluetoothctl connect <YOUR_BBQ10_MAC>
sudo systemctl start bt-keyboard.service
```

Full re-pair (nuclear option) — clear keyboard channels via Layer 2 + double-tap trackpad, then:

```bash
sudo systemctl stop bt-keyboard.service
bluetoothctl remove <YOUR_BBQ10_MAC>
sudo rm -rf "/var/lib/bluetooth/<YOUR_PI_BT_MAC>/<YOUR_BBQ10_MAC>"
sudo systemctl restart bluetooth
sleep 3
bluetoothctl scan on  # wait for device, then pair/trust
```

**GPM is permanently disabled.** It injects xterm mouse escape sequences that cause spurious F-key presses and display corruption. Do not re-enable.

---

## power optimizations

Applied at boot by `restore-persistent-state.service`:

- **CPU governor**: `powersave` — min frequency, imperceptible on 640×480
- **WiFi power management**: `iw dev set power_save on`
- **Console blanking**: blank 5 min, display off 6 min

---

## theme

Candy-pink and mint-green. Colors defined in `~/.fbtermrc` and applied per-app in `usr-local-bin-*` launchers.

---

## repo layout

```
config/          source files mirroring Pi filesystem layout
  opt-cyberdeck-*/   app code
  opt-cyberdeck-shared/  shared libs
  etc-systemd-*      systemd units
  usr-local-bin-*    launcher scripts
  home-user-*        dotfiles
  ish-iphone-ssh-config  SSH config for iSH (iOS)
deploy/
  sync-to-pi.sh                main deploy script
  cyberdeck-optimize.sh        runtime tuning (run after enabling overlayFS)
  README-display.md            display, fonts, theming, chat client
  README-connectivity.md       wifi, tailscale, ssh, bluetooth
  README-storage-and-power.md  power mgmt, sd protection, overlayfs lockdown
  README-shell.md              boot ux + daily usage reference
tests/
  test_*.py          pytest unit tests
  verify-phase-*.sh  integration smoke tests
```

Directory names under `config/` encode the destination path:  
`opt-cyberdeck-chat/chat_tui.py` → `/opt/cyberdeck-chat/chat_tui.py`

---

## contributing

Built yours? Show it off.

PRs welcome for:
- **custom pet skins** — drop your art in `config/opt-cyberdeck-pet/fb_assets_source/` and open a PR with screenshots
- **new TUI apps** — follow the same `opt-cyberdeck-*/` structure
- **bug fixes and improvements**
- **hardware variations** — different Pi models, displays, keyboards

## license

MIT — build your own deck 🏴‍☠️
