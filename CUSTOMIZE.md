# customization guide

Everything you need to fill in before deploying.

---

## 1. SSH config — `config/home-user-ssh-config`

Replace every `<YOUR_*_TAILSCALE_IP>` with your actual Tailscale IPs.  
Replace `<YOUR_*_PUBLIC_IP>` with public IPs (optional — only needed if you want non-Tailscale fallbacks).

```
Host nextcloud
    HostName <YOUR_NEXTCLOUD_TAILSCALE_IP>   ← your Tailscale IP
    User <YOUR_SSH_USER>
```

Run `tailscale status` on each machine to get its IP.

## 2. iPhone SSH config — `config/ish-iphone-ssh-config`

Same as above. Only Tailscale IPs needed (no public fallbacks required if your phone is always on Tailscale).

## 3. Vault sync — `config/usr-local-bin-vault-sync`

```bash
REMOTE="<YOUR_SYNC_SERVER>"        # SSH host alias from your ssh-config
REMOTE_PATH="<YOUR_REMOTE_VAULT_PATH>"   # e.g. /home/user/Vault/ or /mnt/ncdata/.../Vault/
LOCAL_PATH="$HOME/Vault/"
```

If not using Nextcloud, adjust the `occ files:scan` block or remove it entirely.

## 4. Deploy script — `deploy/sync-to-pi.sh`

```bash
PI="<YOUR_USER>@cyberdeck.local"   # or use a Tailscale IP
```

## 5. Pet deploy script — `config/opt-cyberdeck-pet/deploy.sh`

```bash
HOST="<YOUR_USER>@<YOUR_CYBERDECK_TAILSCALE_IP>"
```

## 6. Chat TUI — `config/opt-cyberdeck-chat/chat_tui.py`

Set your LLM API endpoint. The TUI expects an OpenAI-compatible `/v1/chat/completions` endpoint.

```python
API_URL = "http://<YOUR_LLM_HOST>:<PORT>/v1/chat/completions"
```

API key is read from the `LLM_API_KEY` env var — set it in `~/.bash_profile` on the Pi.

## 7. Dash TUI — `config/opt-cyberdeck-dash/dash_tui.py`

Update the list of SSH hosts to monitor:

```python
HOSTS = ["nextcloud", "myserver", "desktop"]
```

These must match host aliases in your SSH config.

## 8. Bluetooth keyboard MAC — `config/etc-systemd-bt-keyboard.service`

```ini
ExecStart=/usr/bin/bluetoothctl connect <YOUR_BBQ10_MAC>
```

## 9. Username

The autologin getty drop-in (`config/etc-systemd-getty-autologin.conf`) uses `<YOUR_USER>` as a placeholder. Replace with your actual Pi username before deploying.

---

## quick check

After customizing, verify no placeholders remain:

```bash
grep -rn YOUR_ config/ deploy/
```

Should return nothing before you deploy.
