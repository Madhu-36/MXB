"""
Unit tests for MXB IntentRouter Tier 1 Voice Fast-Path Extensions:
- Battery status & power monitoring
- Voice timer setting, status, and cancellation
- Cursor color picker / eyedropper
- Native lock screen & recycle bin
- Task manager & Terminal
- Window quadrant snap & aero shake
- Hardware-anchored DPAPI vault secrets
"""
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.router import IntentRouter

class TestRouterExtensions(unittest.TestCase):

    def setUp(self):
        self.mock_tts = MagicMock()
        self.mock_exec = MagicMock()
        self.router = IntentRouter(executor=self.mock_exec, tts=self.mock_tts)

    def test_battery_fastpath(self):
        self.mock_exec.execute_action.return_value = "Battery: 88% (AC Plugged In)"
        res = self.router.route("how much battery")
        self.assertIn("Battery: 88%", res)
        self.mock_exec.execute_action.assert_called_once_with("check_battery")

    def test_timer_start_fastpath(self):
        self.mock_exec.execute_action.return_value = "Timer 'Timer' set for 300 seconds."
        res = self.router.route("set a timer for 5 minutes")
        self.assertIn("Timer 'Timer' set for 300 seconds", res)
        self.mock_exec.execute_action.assert_called_once_with("timer_start", "5 minutes")

    def test_timer_cancel_fastpath(self):
        self.mock_exec.execute_action.return_value = "Timer 'Pasta' cancelled."
        res = self.router.route("cancel timer")
        self.assertIn("cancelled", res.lower())
        self.mock_exec.execute_action.assert_called_once_with("timer_cancel")

    def test_color_picker_fastpath(self):
        self.mock_exec.execute_action.return_value = "Pixel at (100, 200): #00FFCC (Cyan, RGB: 0, 255, 204)"
        res = self.router.route("what color is at my cursor")
        self.assertIn("#00FFCC", res)
        self.mock_exec.execute_action.assert_called_once_with("pick_color")

    def test_lock_screen_fastpath(self):
        self.mock_exec.execute_action.return_value = "Workstation locked successfully."
        res = self.router.route("lock screen")
        self.assertIn("locked successfully", res)
        self.mock_exec.execute_action.assert_called_once_with("lock_pc")

    def test_empty_recycle_bin_fastpath(self):
        self.mock_exec.execute_action.return_value = "Recycle bin emptied successfully."
        res = self.router.route("empty recycle bin")
        self.assertIn("emptied successfully", res)
        self.mock_exec.execute_action.assert_called_once_with("empty_recycle_bin")

    def test_open_task_manager_fastpath(self):
        self.mock_exec.execute_action.return_value = "Opened Windows Task Manager."
        res = self.router.route("open task manager")
        self.assertIn("task manager", res.lower())
        self.mock_exec.execute_action.assert_called_once_with("open_task_manager")

    def test_window_quadrant_fastpath(self):
        self.mock_exec.execute_action.return_value = "Snapped active window to top-left quadrant."
        res = self.router.route("snap top left")
        self.assertIn("top-left", res)
        self.mock_exec.execute_action.assert_called_once_with("manage_window", "top_left")

    def test_aero_shake_fastpath(self):
        self.mock_exec.execute_action.return_value = "Aero Shake: Minimized 3 background windows."
        res = self.router.route("shake window")
        self.assertIn("minimized", res.lower())
        self.mock_exec.execute_action.assert_called_once_with("manage_window", "shake")

    def test_vault_store_fastpath(self):
        self.mock_exec.execute_action.return_value = "Stored secret 'my_token' in encrypted vault."
        res = self.router.route("store secret my_token as secret123")
        self.assertIn("stored secret", res.lower())
        self.mock_exec.execute_action.assert_called_once_with("vault_store", "my_token::secret123")

    def test_vault_get_fastpath(self):
        self.mock_exec.execute_action.return_value = "Secret 'my_token': secret123"
        res = self.router.route("get secret my_token")
        self.assertIn("secret123", res)
        self.mock_exec.execute_action.assert_called_once_with("vault_get", "my_token")

if __name__ == "__main__":
    unittest.main()
