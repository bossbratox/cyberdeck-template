# Display, Fonts, Theming & Chat Client

Covers the visual stack: DSI panel + touch + console font, the fbterm framebuffer terminal that replaces kmscon, and the candy-pink/mint theme + Textual chat TUI.

---

## 1. Display & Touch

### Deploy `config.txt` additions

Append (don't replace) the contents of `config/boot-firmware-config.txt` to `/boot/firmware/config.txt`:

```bash
# SD card mounted on your machine, before first boot:
cat config/boot-firmware-config.txt >> /Volumes/bootfs/config.txt

# Or after first boot, over SSH:
scp config/boot-firmware-config.txt <YOUR_USER>@cyberdeck.local:/tmp/
ssh <YOUR_USER>@cyberdeck.local
cat /tmp/boot-firmware-config.txt | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

### Verify display

```bash
cat /sys/class/drm/card*/*/modes
# Or:
fbset -s
```

Expected `640x480` for the 3.5" DSI panel (`800x480` for 4.3").

If blank: check DSI ribbon seating, confirm `dtoverlay=vc4-kms-v3d` and the panel-specific overlay are uncommented in `/boot/firmware/config.txt`, check `dmesg | grep -i dsi`.

### Verify touch

```bash
sudo apt install evtest
sudo evtest
```

Pick the touchscreen device, tap the screen, watch for `EV_ABS` events. If no touch device appears, uncomment `dtoverlay=rpi-ft5406` in `config.txt` and reboot. If touch is erratic with both overlays active, remove `rpi-ft5406` — newer kernels handle touch natively via the DSI driver.

### Console font

```bash
sudo cp config/etc-default-console-setup /etc/default/console-setup
sudo setupcon
```

Font switches to Terminus 12x24 immediately.

Deploy the KMS font-fix service (prevents font reset on reboot — `vc4-kms-v3d` resets the font to VGA default otherwise):

```bash
sudo cp config/etc-systemd-console-font-fix.service /etc/systemd/system/console-font-fix.service
sudo systemctl daemon-reload
sudo systemctl enable --now console-font-fix.service
```

Available sizes: `ls /usr/share/consolefonts/ | grep Terminus`.
- `10x20` — 64×24, smaller text
- `12x24` — 53×20, balanced (default)
- `14x28` — 45×17, larger text

---

## 2. fbterm (replaces kmscon)

**Why:** kmscon v9 (Bookworm/Trixie armhf) is compiled without xterm mouse-event forwarding. tmux selection and the touch-to-mouse translator can't work under it. fbterm is a 107KB framebuffer terminal with native xterm SGR mouse-mode forwarding.

`kmscon` is NOT uninstalled — kept as emergency fallback.

### Deploy

```bash
ssh <YOUR_USER>@cyberdeck.local 'sudo apt-get update && sudo apt-get install -y fbterm'

scp config/home-user-fbtermrc <YOUR_USER>@cyberdeck.local:~/.fbtermrc

# Append fbterm autolaunch to ~/.profile (idempotent)
scp config/home-user-profile-fbterm-append.sh <YOUR_USER>@cyberdeck.local:/tmp/fbterm-append.sh
ssh <YOUR_USER>@cyberdeck.local '
  if ! grep -q "FBTERM_ACTIVE" ~/.profile; then
    echo "" >> ~/.profile
    cat /tmp/fbterm-append.sh >> ~/.profile
  fi
  rm /tmp/fbterm-append.sh
'

# Flip tty1 from kmscon to getty
ssh <YOUR_USER>@cyberdeck.local '
  sudo systemctl disable kmsconvt@tty1.service
  sudo systemctl enable getty@tty1.service
  sudo systemctl daemon-reload
'
```

### Cutover (on the Pi)

```bash
sudo systemctl stop kmsconvt@tty1.service
sudo systemctl start getty@tty1.service
```

tty1 restarts, auto-logs in, launches fbterm.

### Rollback

```bash
ssh <YOUR_USER>@cyberdeck.local '
  sudo systemctl disable getty@tty1.service
  sudo systemctl enable kmsconvt@tty1.service
  sudo systemctl daemon-reload
  sed -i "/FBTERM_ACTIVE/,+3d" ~/.profile
  sudo systemctl restart kmsconvt@tty1.service
'
```

### Gotchas

- **Font size 20 is a guess for 640×480.** Edit `~/.fbtermrc` `font-size=` and restart tty1 if too small/sparse.
- **fbterm needs `/dev/fb0` exclusive access.** Check `lsof /dev/fb0` if it exits immediately.
- **fbterm 16-color palette only** — 256-color SGR escapes are silently dropped. Theme code in `bashrc-ps1-motd.sh` uses the OSC palette override (`\e]P<n><rrggbb>`) to remap the 16 slots.

---

## 3. Theming + Chat Client

Hot pink PS1, candy-pink terminal background, branded MOTD, Textual-based chat TUI (OpenAI-compatible SSE streaming).

### Install Python venv for chat

```bash
sudo apt install -y python3-venv
sudo mkdir -p /opt/cyberdeck-chat
sudo python3 -m venv /opt/cyberdeck-chat/venv
sudo /opt/cyberdeck-chat/venv/bin/pip install textual httpx
```

Verify: `/opt/cyberdeck-chat/venv/bin/python -c "import textual, httpx; print('OK')"`

### Deploy chat TUI + wrappers

```bash
sudo cp config/opt-cyberdeck-chat/chat_tui.py /opt/cyberdeck-chat/chat_tui.py
sudo cp config/usr-local-bin-chat /usr/local/bin/chat && sudo chmod +x /usr/local/bin/chat
sudo cp config/usr-local-bin-wifi /usr/local/bin/wifi && sudo chmod +x /usr/local/bin/wifi
```

Set `chat_tui.py` `ENDPOINT` to your LLM endpoint (OpenAI-compatible `/v1/chat/completions`). API key reads from `LLM_API_KEY` env var — set it in `~/.bash_profile`:

```bash
echo 'export LLM_API_KEY="..."' >> ~/.bash_profile
```

### Deploy MOTD + PS1 + tmux theme

```bash
sudo cp config/etc-profile.d-motd.sh /etc/profile.d/motd.sh
sudo chmod +x /etc/profile.d/motd.sh

# Append PS1/bg config to ~/.bashrc (do NOT replace the file)
cat config/bashrc-ps1-motd.sh >> ~/.bashrc

# Tmux pink status bar
cp config/tmux.conf ~/.tmux.conf
tmux source-file ~/.tmux.conf 2>/dev/null || true
```

Customize MOTD greeting via env var (set in `~/.bash_profile`):

```bash
echo 'export MOTD_GREETING="welcome back, captain"' >> ~/.bash_profile
```

### Verify on hardware

1. Re-login on the Pi console
2. Candy-pink bg appears, hot pink PS1 with heart symbol
3. MOTD displays
4. `chat` — pink bg fills screen, TUI launches, response streams from your endpoint
5. `wifi` — mint bg fills screen, nmtui launches
6. Exit each — terminal colors reset
