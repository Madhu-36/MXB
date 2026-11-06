import unittest
from unittest.mock import patch, MagicMock
from engine.window_manager import WindowManager

class TestWindowGeometry(unittest.TestCase):

    def test_quadrant_geometry_calculations(self):
        sw, sh = 1920, 1080

        tl = WindowManager.calculate_snap_rect("top_left", sw, sh)
        self.assertEqual(tl, (0, 0, 960, 540))

        tr = WindowManager.calculate_snap_rect("top_right", sw, sh)
        self.assertEqual(tr, (960, 0, 960, 540))

        bl = WindowManager.calculate_snap_rect("bottom_left", sw, sh)
        self.assertEqual(bl, (0, 540, 960, 540))

        br = WindowManager.calculate_snap_rect("bottom_right", sw, sh)
        self.assertEqual(br, (960, 540, 960, 540))

    def test_halves_and_center_calculations(self):
        sw, sh = 2560, 1440

        left = WindowManager.calculate_snap_rect("left", sw, sh)
        self.assertEqual(left, (0, 0, 1280, 1440))

        right = WindowManager.calculate_snap_rect("right", sw, sh)
        self.assertEqual(right, (1280, 0, 1280, 1440))

        center = WindowManager.calculate_snap_rect("center", sw, sh)
        expected_w = int(2560 * 0.70)
        expected_h = int(1440 * 0.70)
        self.assertEqual(center, ((2560 - expected_w) // 2, (1440 - expected_h) // 2, expected_w, expected_h))

    def test_format_variations_normalization(self):
        sw, sh = 1920, 1080
        res1 = WindowManager.calculate_snap_rect("top-left", sw, sh)
        res2 = WindowManager.calculate_snap_rect("top left", sw, sh)
        res3 = WindowManager.calculate_snap_rect("TOP_LEFT", sw, sh)
        self.assertEqual(res1, res2)
        self.assertEqual(res2, res3)

    def test_snap_active_window_no_foreground(self):
        wm = WindowManager()
        with patch.object(wm.user32, 'GetForegroundWindow', return_value=0):
            res = wm.snap_active_window("top_left")
            self.assertIn("No active window", res)

    def test_snap_active_window_success(self):
        wm = WindowManager()
        with patch.object(wm.user32, 'GetForegroundWindow', return_value=12345), \
             patch.object(wm.user32, 'GetSystemMetrics', side_effect=[1920, 1080]), \
             patch.object(wm.user32, 'MoveWindow', return_value=True):
            res = wm.snap_active_window("top_right")
            self.assertIn("Snapped window to top_right", res)

if __name__ == "__main__":
    unittest.main()
