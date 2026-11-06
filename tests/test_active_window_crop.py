import unittest
from unittest.mock import patch, MagicMock
from PIL import Image
from engine.screen import ScreenVision

class TestActiveWindowCrop(unittest.TestCase):

    def setUp(self):
        self.vision = ScreenVision()

    def test_get_active_window_rect_structure(self):
        rect = ScreenVision.get_active_window_rect()
        if rect is not None:
            self.assertIsInstance(rect, tuple)
            self.assertEqual(len(rect), 4)
            x, y, w, h = rect
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)

    @patch.object(ScreenVision, 'get_active_window_rect', return_value=(50, 60, 200, 150))
    def test_capture_active_window_with_rect(self, mock_rect):
        mock_img = Image.new("RGB", (800, 600), color=(0, 255, 0))
        with patch.object(self.vision, 'capture_screen_image', return_value=mock_img):
            result = self.vision.capture_active_window()
            self.assertIsNotNone(result)
            self.assertEqual(result.size, (200, 150))

    @patch.object(ScreenVision, 'get_active_window_rect', return_value=None)
    def test_capture_active_window_fallback(self, mock_rect):
        mock_img = Image.new("RGB", (1920, 1080), color=(0, 0, 255))
        with patch.object(self.vision, 'capture_screen_image', return_value=mock_img):
            result = self.vision.capture_active_window()
            self.assertIsNotNone(result)
            self.assertEqual(result.size, (1920, 1080))

    @patch.object(ScreenVision, 'get_active_window_rect', return_value=(10, 20, 100, 50))
    def test_read_active_window_text_delegation(self, mock_rect):
        with patch.object(self.vision, 'read_roi_text', return_value="Active Window Sample Text"):
            text = self.vision.read_active_window_text()
            self.assertEqual(text, "Active Window Sample Text")

if __name__ == "__main__":
    unittest.main()
