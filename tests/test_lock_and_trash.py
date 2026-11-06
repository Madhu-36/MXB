"""
Unit tests for MXB OS Execution Manager Native Windows System Actions:
- Lock Workstation
- Empty Recycle Bin
- Open Task Manager & Terminal
- Native Multimedia Virtual-Key Media Controls
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.executor import OSExecutionManager

class TestLockAndTrash(unittest.TestCase):

    def setUp(self):
        self.executor = OSExecutionManager()

    @patch.object(OSExecutionManager, "_lock_workstation_native")
    def test_lock_workstation(self, mock_lock):
        mock_lock.return_value = True
        res = self.executor.execute_action("lock_pc")
        self.assertIn("locked successfully", res.lower())
        mock_lock.assert_called_once()

    @patch.object(OSExecutionManager, "_empty_recycle_bin_native")
    def test_empty_recycle_bin(self, mock_empty):
        mock_empty.return_value = 0
        res = self.executor.execute_action("empty_recycle_bin")
        self.assertIn("emptied successfully", res.lower())
        mock_empty.assert_called_once()

    @patch("subprocess.Popen")
    def test_open_task_manager(self, mock_popen):
        res = self.executor.execute_action("open_task_manager")
        self.assertIn("task manager", res.lower())
        mock_popen.assert_called_once_with(["taskmgr.exe"])

    @patch("subprocess.Popen")
    def test_open_terminal(self, mock_popen):
        res = self.executor.execute_action("open_terminal")
        self.assertIn("terminal", res.lower())
        mock_popen.assert_called()

    @patch.object(OSExecutionManager, "control_volume")
    def test_media_control_forwarding(self, mock_vol):
        mock_vol.return_value = "Volume increased"
        res = self.executor.execute_action("media_control", "volume_up")
        self.assertEqual(res, "Volume increased")
        mock_vol.assert_called_once_with("volume_up")

    def test_control_volume_multimedia_keys(self):
        self.executor.keyboard.tap_key = MagicMock()

        # Volume Up
        res = self.executor.control_volume("volume_up")
        self.assertIn("increased", res.lower())
        self.assertEqual(self.executor.keyboard.tap_key.call_count, 4)
        self.executor.keyboard.tap_key.assert_called_with("volume_up")

        # Volume Down
        self.executor.keyboard.tap_key.reset_mock()
        res = self.executor.control_volume("volume_down")
        self.assertIn("decreased", res.lower())
        self.assertEqual(self.executor.keyboard.tap_key.call_count, 4)
        self.executor.keyboard.tap_key.assert_called_with("volume_down")

        # Mute
        self.executor.keyboard.tap_key.reset_mock()
        res = self.executor.control_volume("mute")
        self.assertIn("mute", res.lower())
        self.executor.keyboard.tap_key.assert_called_once_with("volume_mute")

        # Media Play/Pause
        self.executor.keyboard.tap_key.reset_mock()
        res = self.executor.control_volume("play")
        self.assertIn("playback", res.lower())
        self.executor.keyboard.tap_key.assert_called_once_with("media_play_pause")

        # Media Next & Prev
        self.executor.keyboard.tap_key.reset_mock()
        self.executor.control_volume("next")
        self.executor.keyboard.tap_key.assert_called_once_with("media_next")

        self.executor.keyboard.tap_key.reset_mock()
        self.executor.control_volume("prev")
        self.executor.keyboard.tap_key.assert_called_once_with("media_prev")

if __name__ == "__main__":
    unittest.main()
