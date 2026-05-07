# tmux auto-launch snippet for ~/.bashrc
#
# APPEND this to ~/.bashrc on the Pi — do NOT replace the whole file.
# Example: cat bashrc-tmux-guard.sh >> ~/.bashrc
#
# $PS1 check: ensures this only runs in interactive shells.
#   Scripts and non-interactive sessions (e.g., scp, rsync over SSH) will
#   not have $PS1 set, so they won't accidentally launch tmux.
#
# $TMUX check: prevents nesting (tmux-in-tmux).
#   When you open a new window/pane inside tmux, it spawns a new shell.
#   That shell would re-run .bashrc — without this guard, you'd get
#   tmux sessions inside tmux sessions recursively.
#
# -A flag: attach to existing session 'main' if it exists, create if not.
#   Means reconnecting via SSH drops you back into the same session you
#   were using before — work survives disconnects.
#
# Session name 'main': stable and predictable across reboots and reconnects.

# Auto-launch tmux on interactive login, avoid nesting
if [ -n "$PS1" ] && [ -z "$TMUX" ]; then
    tmux new-session -A -s main
fi
