# APPEND this to ~/.profile on the Pi — do NOT replace the whole file.
# This auto-launches fbterm on tty1 (the 3.5" DSI console) after agetty
# autologin. fbterm replaces kmscon because kmscon has zero xterm mouse
# support compiled in — tmux selection + nmtui touch via the
# touch-to-mouse translator only work under fbterm.
#
# Guards:
#   - only fires on tty1 (SSH, tty2+, and tmux sessions are untouched)
#   - only if fbterm is installed and executable
#   - FBTERM_ACTIVE prevents re-entry if fbterm itself re-sources .profile
#
# Rollback: remove this block from ~/.profile, reboot.
#
# Deploy: tail -5 ~/.profile should match this block; re-running the
#         install is idempotent (grep-guarded).

if [ "$(tty)" = "/dev/tty1" ] && [ -z "$FBTERM_ACTIVE" ] && command -v fbterm >/dev/null 2>&1; then
    export FBTERM_ACTIVE=1
    exec fbterm
fi
