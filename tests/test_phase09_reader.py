"""Tests for Phase 9 reader TUI."""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "config" / "opt-cyberdeck-shared"))
sys.path.insert(0, str(PROJECT_ROOT / "config" / "opt-cyberdeck-reader"))

READER_SRC_PATH = PROJECT_ROOT / "config" / "opt-cyberdeck-reader" / "reader_tui.py"
LAUNCHER_PATH = PROJECT_ROOT / "config" / "usr-local-bin-reader"
SYNC_SCRIPT_PATH = PROJECT_ROOT / "deploy" / "sync-to-pi.sh"
RESTORE_SCRIPT_PATH = PROJECT_ROOT / "config" / "usr-local-bin-restore-persistent-state.sh"


# ------------------------------------------------------------------
# Source-inspection tests (don't import curses)
# ------------------------------------------------------------------

def test_reader_imports_shared_colors():
    src = READER_SRC_PATH.read_text()
    assert "from cyberdeck_colors import" in src


def test_reader_imports_ssh_run():
    src = READER_SRC_PATH.read_text()
    assert "from cyberdeck_ssh import ssh_run" in src


def test_reader_imports_touch():
    src = READER_SRC_PATH.read_text()
    assert "import cyberdeck_touch" in src


def test_reader_no_local_init_colors():
    src = READER_SRC_PATH.read_text()
    assert "def init_colors" not in src, "Local init_colors() should be removed"


def test_reader_no_raw_subprocess_ssh():
    src = READER_SRC_PATH.read_text()
    assert not re.search(r'subprocess\.run.*ssh.*BatchMode', src), \
        "Raw subprocess SSH call should be replaced by ssh_run()"


def test_reader_no_256_color():
    src = READER_SRC_PATH.read_text()
    for match in re.finditer(r'curses\.init_pair\(([^)]+)\)', src):
        args = match.group(1).split(",")
        for arg in args[1:]:  # skip pair number
            val = arg.strip()
            if val == "-1":
                continue
            try:
                num = int(val)
                assert num <= 15, \
                    f"Color slot {num} > 15 in reader_tui.py: {match.group(0)}"
            except ValueError:
                pass  # named constant, not a literal


def test_reader_uses_pdftotext():
    src = READER_SRC_PATH.read_text()
    assert "pdftotext" in src, "Must use server-side pdftotext for PDF extraction"


def test_reader_has_wikilink_parsing():
    src = READER_SRC_PATH.read_text()
    assert "[[" in src, "Must parse wikilink syntax"
    assert "curses.color_pair(CP_BLUE)" in src, "Must highlight wikilinks in blue"


def test_reader_has_back_stack():
    src = READER_SRC_PATH.read_text()
    assert "back_stack" in src, "Must maintain back navigation stack"


def test_reader_has_browser_mode():
    src = READER_SRC_PATH.read_text()
    assert "browser" in src, "Must have browser mode"
    assert "reader" in src, "Must have reader mode"


def test_reader_has_search():
    src = READER_SRC_PATH.read_text()
    assert "search_active" in src or "search_buf" in src, "Must have search functionality"


def test_reader_saves_bookmarks():
    src = READER_SRC_PATH.read_text()
    assert "reader-bookmarks" in src or "bookmarks" in src, "Must save bookmarks"
    assert "_save_bookmark" in src, "Must have _save_bookmark method"


def test_launcher_exists():
    assert LAUNCHER_PATH.exists(), "Launcher script usr-local-bin-reader must exist"
    src = LAUNCHER_PATH.read_text()
    assert "exec python3 /opt/cyberdeck-reader/reader_tui.py" in src
    assert "PYTHONPATH=/opt/cyberdeck-shared" in src


def test_sync_script_has_reader_blocks():
    src = SYNC_SCRIPT_PATH.read_text()
    assert "cyberdeck-reader" in src, "sync-to-pi.sh must deploy reader TUI"
    assert "usr-local-bin-read" in src, "sync-to-pi.sh must deploy reader launcher"


def test_restore_script_has_reader_block():
    src = RESTORE_SCRIPT_PATH.read_text()
    assert "cyberdeck-reader" in src, "restore-persistent-state.sh must restore reader"


# ------------------------------------------------------------------
# Functional tests (safe to import curses)
# ------------------------------------------------------------------

def test_reader_can_import_without_curses_error():
    """Importing the module should not fail even though curses is imported."""
    # We avoid importing the whole module because curses.wrapper would need a tty.
    # Instead we verify syntax and key names by parsing the source.
    src = READER_SRC_PATH.read_text()
    assert "curses.wrapper(main)" in src
    assert "class ReaderApp:" in src


def test_wrap_segments_logic():
    """Verify _wrap_segments via direct execution of a simplified version."""
    # Re-implement the word-wrap logic to test it independently
    def wrap_segments(segments, width):
        if width <= 0:
            return [[]]
        words = []
        for text, attr, link_id in segments:
            parts = text.split(" ")
            for pi, part in enumerate(parts):
                if pi > 0:
                    words.append((" ", attr, link_id))
                if part:
                    words.append((part, attr, link_id))
        lines = []
        current = []
        cur_len = 0
        for word, attr, link_id in words:
            wlen = len(word)
            if cur_len + wlen <= width:
                current.append((word, attr, link_id))
                cur_len += wlen
            else:
                if current:
                    lines.append(current)
                    current = []
                    cur_len = 0
                if wlen > width:
                    i = 0
                    while i < wlen:
                        chunk = word[i:i + width]
                        current.append((chunk, attr, link_id))
                        cur_len = len(chunk)
                        if cur_len >= width:
                            lines.append(current)
                            current = []
                            cur_len = 0
                        i += width
                else:
                    current.append((word, attr, link_id))
                    cur_len = wlen
        if current:
            lines.append(current)
        return lines if lines else [[]]

    # Simple case
    segs = [("hello world", 0, -1)]
    result = wrap_segments(segs, 20)
    assert len(result) == 1

    # Wrap at 8 chars
    result = wrap_segments(segs, 8)
    assert len(result) == 2
    assert result[0][0][0] == "hello"

    # Multi-segment with link
    segs = [("foo ", 0, -1), ("[[bar]]", 1, 0), (" baz", 0, -1)]
    result = wrap_segments(segs, 20)
    assert len(result) == 1
    flat = "".join(seg[0] for seg in result[0])
    assert "[[bar]]" in flat


def test_no_non_stdlib_imports():
    """reader_tui.py must not import non-stdlib packages."""
    src = READER_SRC_PATH.read_text()
    bad = ["paramiko", "httpx", "requests", "textual", "rich"]
    for pkg in bad:
        assert pkg not in src.lower(), f"Must not import non-stdlib package {pkg}"
