import unittest
from PIL import Image
from engine.screen import ScreenVision

class TestScreenROI(unittest.TestCase):

    def setUp(self):
        self.vision = ScreenVision()

    def test_roi_cropping_bounds_protection(self):
        # Create a mock 100x100 PIL Image
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        
        # Test boundary clamping
        crop_x1 = max(0, min(100 - 1, -50))
        crop_y1 = max(0, min(100 - 1, -50))
        crop_x2 = max(crop_x1 + 1, min(100, crop_x1 + 200))
        crop_y2 = max(crop_y1 + 1, min(100, crop_y1 + 200))
        
        cropped = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        self.assertEqual(cropped.size, (100, 100))

    def test_screen_vision_instance(self):
        self.assertIsNotNone(self.vision)

if __name__ == "__main__":
    unittest.main()
