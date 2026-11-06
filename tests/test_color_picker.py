import unittest
from unittest.mock import patch
from engine.color_picker import ColorPicker

class TestColorPicker(unittest.TestCase):

    def test_approximate_color_naming(self):
        self.assertEqual(ColorPicker.get_approx_color_name(255, 255, 255), "White")
        self.assertEqual(ColorPicker.get_approx_color_name(0, 0, 0), "Black")
        self.assertEqual(ColorPicker.get_approx_color_name(255, 0, 0), "Red")
        self.assertEqual(ColorPicker.get_approx_color_name(0, 0, 255), "Blue")
        self.assertEqual(ColorPicker.get_approx_color_name(0, 255, 255), "Cyan")
        self.assertEqual(ColorPicker.get_approx_color_name(254, 250, 252), "White")

    def test_get_color_at_mocked_pixel(self):
        cp = ColorPicker()
        # 0x0000FF is red in COLORREF (0xBBGGRR format) -> R=0xFF, G=0x00, B=0x00
        with patch.object(cp.gdi32, 'GetPixel', return_value=0x0000FF), \
             patch.object(cp.user32, 'GetDC', return_value=1), \
             patch.object(cp.user32, 'ReleaseDC', return_value=1):
            res = cp.get_color_at(50, 50)
            self.assertEqual(res["hex"], "#FF0000")
            self.assertEqual(res["r"], 255)
            self.assertEqual(res["g"], 0)
            self.assertEqual(res["b"], 0)
            self.assertEqual(res["name"], "Red")
            self.assertIn("#FF0000", res["summary"])

    def test_live_cursor_color_structure(self):
        cp = ColorPicker()
        res = cp.get_color_at_cursor()
        self.assertIsInstance(res, dict)
        self.assertIn("hex", res)
        self.assertIn("name", res)
        self.assertIn("r", res)
        self.assertIn("g", res)
        self.assertIn("b", res)
        self.assertTrue(res["hex"].startswith("#"))
        self.assertEqual(len(res["hex"]), 7)

if __name__ == "__main__":
    unittest.main()
