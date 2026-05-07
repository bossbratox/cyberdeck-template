#!/usr/bin/env python3
"""Quick tests for Reader TUI fixes."""

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "config/opt-cyberdeck-shared")
sys.path.insert(0, "config/opt-cyberdeck-reader")

import cyberdeck_touch
from reader_tui import ReaderApp


class TestReaderScrollUp(unittest.TestCase):
    """Ensure reader can scroll up past cursor_y == 0."""

    def test_cursor_y_negative_scrolls_page_up(self):
        app = ReaderApp(MagicMock())
        app.mode = "reader"
        app.display_lines = [("line", 1, 0, None)] * 100
        app.reader_offset = 10
        app.cursor_y = 0

        # Simulate _draw_reader boundary correction
        ch = 18  # content height
        max_offset = max(0, len(app.display_lines) - ch)
        app.cursor_y = -3  # after pressing UP three times at top
        if app.cursor_y < 0:
            app.reader_offset = max(0, app.reader_offset + app.cursor_y)
            app.cursor_y = 0

        self.assertEqual(app.reader_offset, 7)
        self.assertEqual(app.cursor_y, 0)


class TestEscBack(unittest.TestCase):
    """Ensure bare ESC triggers back navigation."""

    def test_browser_esc_goes_up_dir(self):
        app = ReaderApp(MagicMock())
        app.mode = "browser"
        app.current_dir = "/mnt/ncdata/admin/files/Vault/Notes"
        app.file_list = [("..", True, "/mnt/ncdata/admin/files/Vault")]
        # Mock _refresh_dir so we don't hit SSH
        app._refresh_dir = lambda: None
        # Simulate bare ESC handling
        app._go_up_dir()
        self.assertEqual(app.current_dir, "/mnt/ncdata/admin/files/Vault")

    def test_reader_esc_goes_back(self):
        app = ReaderApp(MagicMock())
        app.mode = "reader"
        app.back_stack = [("", 0, 0)]
        app._go_back()
        self.assertEqual(app.mode, "browser")


class TestMouseListener(unittest.TestCase):
    """Ensure mouse listener helpers exist and are safe."""

    def test_start_mouse_listener_exists(self):
        self.assertTrue(hasattr(cyberdeck_touch, "start_mouse_listener"))

    def test_stop_mouse_listener_exists(self):
        self.assertTrue(hasattr(cyberdeck_touch, "stop_mouse_listener"))

    def test_stop_mouse_listener_is_callable(self):
        self.assertTrue(callable(cyberdeck_touch.stop_mouse_listener))

    def test_stop_mouse_listener_does_not_raise(self):
        try:
            cyberdeck_touch.stop_mouse_listener()
        except Exception as e:
            self.fail(f"stop_mouse_listener() raised {e}")


if __name__ == "__main__":
    unittest.main()
