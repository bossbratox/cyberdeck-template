#!/bin/bash
set -e
HOST="<YOUR_USER>@<YOUR_CYBERDECK_TAILSCALE_IP>"
REMOTE_DIR="/opt/cyberdeck-pet"

PERSIST="/boot/firmware/persistent"

echo "=== Deploying pet to cyberdeck ==="
echo "NOTE: This deploys to tmpfs overlay (lost on reboot)."
echo "For persistent deploy, use: bash ../../deploy/sync-to-pi.sh --persist"
echo ""

# Ensure remote directories and temp dirs exist
ssh $HOST "sudo mkdir -p $REMOTE_DIR/fb_assets && sudo mkdir -p $PERSIST/cyberdeck-pet/fb_assets"
ssh $HOST "mkdir -p /tmp/pet-py /tmp/pet-assets"

# Copy Python files
echo "Copying Python files..."
scp pet_fb_main.py pet_fb_draw.py pet_fb_blitter.py pet_fb_progression.py pet_fb_friends.py pet_fb_anim.py $HOST:/tmp/pet-py/
ssh $HOST "sudo mv /tmp/pet-py/*.py $REMOTE_DIR/"

# Copy assets to overlay
echo "Copying assets to overlay..."
rsync -av --delete fb_assets/ $HOST:/tmp/pet-assets/
ssh $HOST "sudo mv /tmp/pet-assets/* $REMOTE_DIR/fb_assets/"

# Copy assets to persistent store (FAT32 — no chown needed, just cp)
echo "Copying assets to persistent store..."
rsync -av --delete fb_assets/ $HOST:/tmp/pet-assets-persist/
ssh $HOST "sudo mkdir -p $PERSIST/cyberdeck-pet/fb_assets && sudo cp -r /tmp/pet-assets-persist/* $PERSIST/cyberdeck-pet/fb_assets/"

# Fix permissions
ssh $HOST "sudo chown -R <YOUR_USER>:<YOUR_USER> $REMOTE_DIR && sudo chmod 755 $REMOTE_DIR/*.py && sudo chmod -R 644 $REMOTE_DIR/fb_assets/*"

# Persistent dir is FAT32 — chown will fail, that's expected
ssh $HOST "sudo chown <YOUR_USER>:<YOUR_USER> $PERSIST 2>/dev/null || true"

# Install systemd user service
ssh $HOST "mkdir -p ~/.config/systemd/user"
scp systemd/cyberdeck-pet.service $HOST:/tmp/pet.service
ssh $HOST "mv /tmp/pet.service ~/.config/systemd/user/cyberdeck-pet.service"

# Reload and enable
ssh $HOST "systemctl --user daemon-reload && systemctl --user enable cyberdeck-pet.service"

echo "=== Deploy complete ==="
echo "To start now:  ssh $HOST 'systemctl --user start cyberdeck-pet'"
echo "To check status: ssh $HOST 'systemctl --user status cyberdeck-pet'"
echo "To stop:       ssh $HOST 'systemctl --user stop cyberdeck-pet'"
echo ""
echo "Or run manually: ssh $HOST 'cd $REMOTE_DIR && python3 pet_fb_main.py'"
