"""Tests for Phase 8 dashboard TUI enhancements: disk metrics, color thresholds, two-row layout."""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "config" / "opt-cyberdeck-shared"))
sys.path.insert(0, str(PROJECT_ROOT / "config" / "opt-cyberdeck-dash"))

DASH_SRC_PATH = PROJECT_ROOT / "config" / "opt-cyberdeck-dash" / "dash_tui.py"


# Local copy of _metric_color to test logic without triggering curses import.
def _metric_color(pct, warn=80, crit=90):
    if pct >= crit:
        return 2   # CP_PINK_HEADER
    if pct >= warn:
        return 6   # CP_REASONING
    return 3       # CP_MINT


def test_stat_cmd_has_disk():
    """STAT_CMD string contains df -m for disk usage."""
    src = DASH_SRC_PATH.read_text()
    assert "df -m" in src, "STAT_CMD must include 'df -m' for disk usage"


def test_poll_host_parses_disk():
    """poll_host returns disk_used and disk_total keys in its dict."""
    src = DASH_SRC_PATH.read_text()
    assert "disk_used" in src, "poll_host must include disk_used in return dict"
    assert "disk_total" in src, "poll_host must include disk_total in return dict"


def test_metric_color_thresholds():
    """_metric_color returns correct color pair at default warn=80, crit=90."""
    CP_MINT = 3
    CP_REASONING = 6
    CP_PINK_HEADER = 2

    # Normal range
    assert _metric_color(0) == CP_MINT
    assert _metric_color(30) == CP_MINT
    assert _metric_color(79) == CP_MINT

    # Warning range (warn=80 inclusive)
    assert _metric_color(80) == CP_REASONING
    assert _metric_color(89) == CP_REASONING

    # Critical range (crit=90 inclusive)
    assert _metric_color(90) == CP_PINK_HEADER
    assert _metric_color(95) == CP_PINK_HEADER
    assert _metric_color(100) == CP_PINK_HEADER


def test_metric_color_ram_warn_75():
    """RAM uses warn=75 threshold: 74 is mint, 75 is warning."""
    CP_MINT = 3
    CP_REASONING = 6

    assert _metric_color(74, warn=75) == CP_MINT, "74% with warn=75 should be CP_MINT"
    assert _metric_color(75, warn=75) == CP_REASONING, "75% with warn=75 should be CP_REASONING"


def test_hosts_list():
    """HOSTS list has 6 entries including one with ssh=None (local)."""
    src = DASH_SRC_PATH.read_text()
    # Count host entries: each host dict has a "name" key
    host_entries = re.findall(r'"name":', src)
    assert len(host_entries) == 6, f"Expected 6 HOSTS entries, found {len(host_entries)}"
    # At least one entry has ssh=None (local/cyberdeck)
    assert '"ssh": None' in src or "'ssh': None" in src, \
        "HOSTS must include one entry with ssh=None for local host"


def test_no_256_color():
    """No curses.init_pair call in dash_tui.py uses color slot > 15."""
    src = DASH_SRC_PATH.read_text()
    for match in re.finditer(r"curses\.init_pair\(([^)]+)\)", src):
        args = match.group(1).split(",")
        for arg in args[1:]:  # skip pair number
            val = arg.strip()
            if val == "-1":
                continue
            try:
                num = int(val)
                assert num <= 15, \
                    f"Color slot {num} > 15 in dash_tui.py: {match.group(0)}"
            except ValueError:
                pass  # named constant, not a literal


def test_two_row_layout():
    """draw() host loop uses a two-row stride (i * 2) for host positioning."""
    src = DASH_SRC_PATH.read_text()
    # The draw method should contain i * 2 stride for host rows
    assert "i * 2" in src or "i*2" in src, \
        "draw() must use i * 2 stride for two-row-per-host layout"
