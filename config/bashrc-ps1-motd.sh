# PS1 prompt and sky blue background for ~/.bashrc
#
# APPEND this to ~/.bashrc on the Pi — do NOT replace the whole file.
# Append BEFORE the tmux-guard snippet so PS1 is set before tmux launches.
# Example: cat bashrc-ps1-motd.sh >> ~/.bashrc
#
# This MUST be appended before bashrc-tmux-guard.sh in ~/.bashrc ordering.
# PS1 and background are set inside the interactive shell guard.
#
# $PS1 check: ensures this only runs in interactive shells.
#   Scripts and non-interactive sessions (e.g., scp, rsync over SSH) will
#   not have $PS1 set, so they won't accidentally set terminal colors.

# Set sky blue background and PS1 on interactive login
if [ -n "$PS1" ]; then
    if [ -n "$FBTERM_ACTIVE" ]; then
        # fbterm sets TERM=linux by default (fbterm.1.in:177 / shell.cpp:82),
        # so we can't dispatch on $TERM. FBTERM_ACTIVE is exported from
        # ~/.profile before `exec fbterm` and inherited by the child shell.
        #
        # fbterm ignores 256-color SGR on the framebuffer console.
        # Use the linux-console OSC palette override (\e]P<n><rrggbb>) to
        # redefine the low 16 palette slots to the cyberdeck pastel theme,
        # then drive PS1 / bg with plain 16-color SGR which fbterm honors.
        # clear_param resets palette state on each \e], so consecutive
        # \e]P<7hex> sequences all take effect (vterm_states.cpp:53 +
        # vterm_action.cpp:91).
        # Palette slots remapped for the cyberdeck pastel theme:
        #   0=2A1F28 dark plum   1=E8A0BF pastel pink  2=C8E6A0 mint
        #   3=F5DEB3 wheat       4=B0C4DE steel blue   5=FF00CC DEEP PINK (PS1 accent)
        #   6=A5F2E5 cyan-mint   7=FFAFD7 CANDY PINK (bg via \e[47m)
        #   8=6B5466 dim purple  9=F8C0DF lighter pink A=D8F6C0 bright mint
        #   B=FFEDC3 cream-yellow C=D0E4EE pale blue   D=FF87C7 HOTTER PINK (chat bg)
        #   E=C5FFF5 pale cyan   F=FFFFFF WHITE (fg via bold+\e[37m = slot 7^8 = slot 15)
        printf '\e]P02A1F28\e]P1E8A0BF\e]P2C8E6A0\e]P3F5DEB3\e]P4B0C4DE\e]P5FF00CC\e]P6A5F2E5\e]P7FFAFD7\e]P86B5466\e]P9F8C0DF\e]PAD8F6C0\e]PBFFEDC3\e]PCD0E4EE\e]PDFF00CC\e]PEC5FFF5\e]PFFFFFFF'
        # candy pink bg (slot 7 via \e[47m) + white fg via bold+slot7 (\e[1;37m -> slot 7^8 = slot 15)
        # Note: fbterm only handles SGR 30-37/40-47; \e[97m is silently ignored.
        # Bold (intensity=2) XORs fcolor with 8 at render time (fbshell.cpp:706),
        # so \e[1;37m -> slot 7^8 = slot 15 = FFFFFF. This is the only way to get
        # white fg in fbterm without patching init_default_color's >7 clamp.
        printf '\e[47m\e[1;37m'
        printf '\e[H\e[J'

        # PS1: deep-pink \w + heart + dollar, then reset to white for typed text.
        # \e[35m = slot 5 (deep pink), \e[0m\e[47m\e[1;37m = candy-pink bg + bold white fg.
        PS1='\[\e[35m\]\w \[\e[35m\]♥ \[\e[35m\]$ \[\e[0m\e[47m\e[1;37m\]'

        # Top-row status bar (clock + battery) when running raw bash in F1.
        # tmux paints its own status bar, so skip when inside tmux.
        # Uses save-cursor / move-to-1,1 / restore-cursor so the bar repaints
        # on each prompt without disturbing typed input.
        _cyberdeck_statusbar() {
            [ -n "$TMUX" ] && return
            local cols s
            cols=${COLUMNS:-$(tput cols 2>/dev/null || echo 26)}
            s=$(PYTHONPATH=/opt/cyberdeck-shared python3 -m cyberdeck_status 2>/dev/null)
            [ -z "$s" ] && return
            local pad=$((cols - ${#s}))
            [ $pad -lt 0 ] && pad=0
            printf '\e7\e[1;1H\e[35m\e[47m%*s%s\e[0m\e[47m\e[1;37m\e8' "$pad" "" "$s"
        }
        PROMPT_COMMAND="_cyberdeck_statusbar${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
    else
        # SSH from another machine — leave terminal bg alone (don't fight the
        # caller's theme). Just set hot-pink PS1 so cyberdeck shells are
        # visually distinct in tmux/multi-window setups.
        # xterm-256 color 198 = hot pink. U+2665 (♥) requires a Nerd Font.
        # Fall back to > if heart renders as a box on the host terminal.
        PS1='\[\e[38;5;198m\]\w \[\e[38;5;198m\]♥ \[\e[38;5;198m\]$ \[\e[0m\]'
    fi
fi
