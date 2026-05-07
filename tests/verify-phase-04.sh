#!/bin/bash
# Phase 4: cyberdeck Theming and Chat Client verification script
# Run on the Pi after deploying all Phase 4 configs.
#
# Usage: bash tests/verify-phase-04.sh
#
# Checks BTH-01 through BTH-07 and CHAT-01 through CHAT-03.
# BTH-06 (legibility) is manual — not automatable.

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        ((PASS++))
    else
        echo "  FAIL: $desc"
        ((FAIL++))
    fi
}

echo "=== Phase 4: cyberdeck Theming and Chat Client Verification ==="
echo ""

echo "[BTH-01] PS1 hot pink branding"
check "PS1 hot pink escape in bashrc" grep -q '38;5;198m' ~/.bashrc
check "heart symbol in bashrc" grep -q '♥' ~/.bashrc

echo ""
echo "[BTH-02] Candy pink background on login"
# fbterm 16-color palette: slot 7 (\e[47m) = candy pink bg; slot 15 (\e[97m) = cream fg
check "candy pink bg escape in bashrc" grep -qE '\\e\[47(;[0-9]+)*m|\\e\[[0-9]+;47m' ~/.bashrc

echo ""
echo "[BTH-03] Chat client pink background"
# fbterm 16-color palette: \e[47m = candy pink bg (slot 7), \e[105m = hotter pink (slot D)
check "pink bg escape in chat wrapper" grep -qE '\\e\[(47|105)(;[0-9]+)*m|\\e\[[0-9]+;(47|105)m' /usr/local/bin/chat
check "EXIT trap in chat wrapper" grep -q 'trap' /usr/local/bin/chat

echo ""
echo "[BTH-04] WiFi/nmtui palette (NEWT_COLORS)"
check "NEWT_COLORS exported in wifi wrapper" grep -q 'NEWT_COLORS' /usr/local/bin/wifi
check "magenta newt palette in wifi wrapper" grep -q 'magenta' /usr/local/bin/wifi
check "EXIT trap in wifi wrapper" grep -q 'trap' /usr/local/bin/wifi

echo ""
echo "[BTH-05] Color palette across TUI programs"
check "chat wrapper exists" test -f /usr/local/bin/chat
check "wifi wrapper exists" test -f /usr/local/bin/wifi
check "tmux status bar has hot pink" grep -q 'colour198' ~/.tmux.conf

echo ""
echo "[BTH-06] Text legibility (MANUAL)"
echo "  SKIP: Visual inspection required on physical 3.5\" hardware"

echo ""
echo "[BTH-07] Branded MOTD with system stats"
check "MOTD script exists" test -f /etc/profile.d/motd.sh
check "MOTD script is executable" test -x /etc/profile.d/motd.sh
check "MOTD has greeting" grep -qE 'MOTD_GREETING|welcome to cyberdeck' /etc/profile.d/motd.sh
check "MOTD has IP stat" grep -q 'hostname -I' /etc/profile.d/motd.sh
check "MOTD has uptime stat" grep -q 'uptime -p' /etc/profile.d/motd.sh
check "MOTD has VPN stat" grep -q 'tailscale status' /etc/profile.d/motd.sh
check "MOTD has battery note" grep -q 'Battery status unavailable' /etc/profile.d/motd.sh

echo ""
echo "[CHAT-01] Chat client connects to endpoint"
check "chat_tui.py has correct endpoint" grep -q '<YOUR_LLM_HOST>' /opt/cyberdeck-chat/chat_tui.py

echo ""
echo "[CHAT-02] Full-screen TUI with history and input"
check "textual importable" /opt/cyberdeck-chat/venv/bin/python -c "import textual; print('OK')"
check "httpx importable" /opt/cyberdeck-chat/venv/bin/python -c "import httpx; print('OK')"
check "chat_tui.py has ChatApp class" grep -q 'class ChatApp' /opt/cyberdeck-chat/chat_tui.py

echo ""
echo "[CHAT-03] Pink background for chat (shared with BTH-03)"
check "chat wrapper has pink bg" grep -qE '\\e\[(47|105)(;[0-9]+)*m|\\e\[[0-9]+;(47|105)m' /usr/local/bin/chat

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo "PHASE 4 VERIFICATION: FAIL"
    exit 1
else
    echo "PHASE 4 VERIFICATION: PASS"
    exit 0
fi
