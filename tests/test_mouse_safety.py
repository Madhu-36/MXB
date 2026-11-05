import unittest
from engine.mouse import MouseController

class TestMouseSafety(unittest.TestCase):

    def setUp(self):
        self.mouse = MouseController()

    def test_virtual_bounds_are_positive_and_valid(self):
        min_x, min_y, max_x, max_y = self.mouse.get_virtual_bounds()
        self.assertLess(min_x, max_x)
        self.assertLess(min_y, max_y)

    def test_clip_coordinates_restricts_out_of_bounds(self):
        min_x, min_y, max_x, max_y = self.mouse.get_virtual_bounds()

        # Far beyond top-left
        cx, cy = self.mouse.clip_coordinates(-99999, -99999)
        self.assertEqual(cx, min_x)
        self.assertEqual(cy, min_y)

        # Far beyond bottom-right
        cx2, cy2 = self.mouse.clip_coordinates(99999, 99999)
        self.assertEqual(cx2, max_x)
        self.assertEqual(cy2, max_y)

    def test_within_bounds_remains_unchanged(self):
        min_x, min_y, max_x, max_y = self.mouse.get_virtual_bounds()
        mid_x = (min_x + max_x) // 2
        mid_y = (min_y + max_y) // 2
        cx, cy = self.mouse.clip_coordinates(mid_x, mid_y)
        self.assertEqual(cx, mid_x)
        self.assertEqual(cy, mid_y)

if __name__ == "__main__":
    unittest.main()
