#!/usr/bin/env python3
"""Quick tests for WiFi TUI crash fixes."""

import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "config/opt-cyberdeck-shared")
sys.path.insert(0, "config/opt-cyberdeck-wifi")

import cyberdeck_touch
from wifi_tui import (
    nmcli,
    scan_networks,
    connect_new,
    connect_saved,
    forget_network,
)


class TestNmcliStdin(unittest.TestCase):
    """Ensure nmcli never inherits stdin (prevents interactive hangs)."""

    @patch("wifi_tui.subprocess.run")
    def test_nmcli_uses_devnull_stdin(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        nmcli("device", "wifi", "list")
        call_kwargs = mock_run.call_args.kwargs
        self.assertEqual(call_kwargs.get("stdin"), subprocess.DEVNULL)


class TestScanNetworksSignalParsing(unittest.TestCase):
    """Ensure scan_networks handles non-numeric signal values."""

    @patch("wifi_tui.nmcli")
    @patch("wifi_tui.time.sleep", return_value=None)
    def test_non_numeric_signal_does_not_crash(self, _mock_sleep, mock_nmcli):
        mock_nmcli.return_value = (
            0,
            "Net1:65:WPA2\nNet2:--:WPA2\nNet3::WPA2\n",
            "",
        )
        result = scan_networks()
        ssids = [r[0] for r in result]
        self.assertIn("Net1", ssids)
        self.assertIn("Net2", ssids)
        # Net3 has empty SSID, so it should be skipped
        self.assertNotIn("", ssids)
        # Should not crash and should still sort (Net2 treated as 0 signal)


class TestNmcliDashProtection(unittest.TestCase):
    """Ensure SSIDs starting with '-' are not treated as nmcli options."""

    @patch("wifi_tui.subprocess.run")
    def test_connect_saved_does_not_use_double_dash(self, mock_run):
        # nmcli connection up does not support -- before the ID;
        # it interprets -- as the connection name itself.
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        connect_saved("home wifi")
        args = mock_run.call_args.args[0]
        self.assertNotIn("--", args)

    @patch("wifi_tui.subprocess.run")
    def test_connect_new_does_not_use_double_dash(self, mock_run):
        # subprocess.run passes each list element as a single arg;
        # -- is unnecessary and breaks some nmcli subcommands.
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        connect_new("home wifi", "secret")
        first_call_args = mock_run.call_args_list[0].args[0]
        self.assertNotIn("--", first_call_args)

    @patch("wifi_tui.subprocess.run")
    def test_forget_network_does_not_use_double_dash(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        forget_network("home wifi")
        args = mock_run.call_args.args[0]
        self.assertNotIn("--", args)


class TestStopTouchListener(unittest.TestCase):
    """Ensure cyberdeck_touch.stop_touch_listener exists and is safe to call."""

    def test_stop_touch_listener_exists(self):
        self.assertTrue(hasattr(cyberdeck_touch, "stop_touch_listener"))

    def test_stop_touch_listener_is_callable(self):
        self.assertTrue(callable(cyberdeck_touch.stop_touch_listener))

    def test_stop_touch_listener_does_not_raise(self):
        # Should be a no-op and not crash even if start was never called
        try:
            cyberdeck_touch.stop_touch_listener()
        except Exception as e:
            self.fail(f"stop_touch_listener() raised {e}")


if __name__ == "__main__":
    unittest.main()
