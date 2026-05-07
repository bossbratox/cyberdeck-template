"""Tests for Phase 6 shared infrastructure modules."""

import re
import sys
from pathlib import Path

# Add shared module to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "config" / "opt-cyberdeck-shared"))


def test_color_constants_in_range():
    """All CP_* constants are 1-8, all init_pair color args are 0-15."""
    from cyberdeck_colors import (
        CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM,
        CP_DIVIDER, CP_REASONING, CP_SELECTED_BG, CP_BLUE,
    )
    constants = [CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM,
                 CP_DIVIDER, CP_REASONING, CP_SELECTED_BG, CP_BLUE]
    for c in constants:
        assert 1 <= c <= 8, f"Color pair constant {c} out of range 1-8"

    # Read source and verify no init_pair call uses a color arg > 15
    src = (PROJECT_ROOT / "config" / "opt-cyberdeck-shared" / "cyberdeck_colors.py").read_text()
    for match in re.finditer(r"curses\.init_pair\(([^)]+)\)", src):
        args = match.group(1).split(",")
        # args: pair_number, fg, bg
        for arg in args[1:]:  # skip pair number
            val = arg.strip()
            if val == "-1":
                continue
            num = int(val)
            assert num <= 15, f"Color slot {num} > 15 in init_pair call: {match.group(0)}"


def test_touch_exports():
    """Touch module exports find_touch_device and start_touch_listener."""
    from cyberdeck_touch import find_touch_device, start_touch_listener, VIRTUAL_MOUSE_NAME
    assert callable(find_touch_device)
    assert callable(start_touch_listener)
    assert VIRTUAL_MOUSE_NAME == "cyberdeck-touch-mouse"


def test_ssh_run_signature():
    """ssh_run has params (host, cmd, timeout) with timeout default 10."""
    import inspect
    from cyberdeck_ssh import ssh_run
    sig = inspect.signature(ssh_run)
    params = list(sig.parameters.keys())
    assert params == ["host", "cmd", "timeout"], f"Expected [host, cmd, timeout], got {params}"
    assert sig.parameters["timeout"].default == 10, "timeout default should be 10"


def test_ssh_config_has_controlmaster():
    """SSH config contains ControlMaster stanza for 5 hosts."""
    ssh_config = (PROJECT_ROOT / "config" / "home-user-ssh-config").read_text()
    assert "ControlMaster auto" in ssh_config
    assert "ControlPath /tmp/ssh-ctrl-%h" in ssh_config
    assert "ControlPersist 120s" in ssh_config
    assert "Host nextcloud web mail desktop home-pi" in ssh_config


def test_restore_script_has_reader_bookmarks():
    """Restore script contains reader bookmarks persistence block."""
    script = (PROJECT_ROOT / "config" / "usr-local-bin-restore-persistent-state.sh").read_text()
    assert "reader-bookmarks" in script
    assert "cyberdeck-reader/bookmarks" in script


def test_chat_tui_no_local_init_colors():
    """chat_tui.py imports shared init_colors, has no local definition."""
    src = (PROJECT_ROOT / "config" / "opt-cyberdeck-chat" / "chat_tui.py").read_text()
    assert "from cyberdeck_colors import" in src, "Missing shared color import"
    assert "def init_colors" not in src, "Local init_colors() should be removed"


def test_dash_tui_uses_ssh_run():
    """dash_tui.py uses shared ssh_run, not raw subprocess SSH calls."""
    src = (PROJECT_ROOT / "config" / "opt-cyberdeck-dash" / "dash_tui.py").read_text()
    assert "from cyberdeck_ssh import ssh_run" in src, "Missing shared SSH import"
    assert not re.search(r'subprocess\.run.*ssh.*BatchMode', src), \
        "Raw subprocess SSH call should be replaced by ssh_run()"


def test_bt_tui_no_256_color():
    """bt_tui.py imports shared colors, has no local init_colors or 256-color refs."""
    src = (PROJECT_ROOT / "config" / "opt-cyberdeck-bt" / "bt_tui.py").read_text()
    assert "from cyberdeck_colors import" in src, "Missing shared color import"
    assert "def init_colors" not in src, "Local init_colors() should be removed"
    # Verify no init_pair calls with color slots > 15
    for match in re.finditer(r"curses\.init_pair\(([^)]+)\)", src):
        args = match.group(1).split(",")
        for arg in args[1:]:
            val = arg.strip()
            if val == "-1":
                continue
            num = int(val)
            assert num <= 15, f"Color slot {num} > 15 in bt_tui.py: {match.group(0)}"
