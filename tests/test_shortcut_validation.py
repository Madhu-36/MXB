import unittest
from engine.keyboard_ext import KeyboardExtended

class TestShortcutValidation(unittest.TestCase):

    def test_valid_shortcuts_string(self):
        v1 = KeyboardExtended.validate_shortcut_keys("ctrl+c")
        self.assertTrue(v1["valid"])
        self.assertEqual(v1["normalized_keys"], ["ctrl", "c"])
        self.assertEqual(v1["vk_codes"], [0x11, ord('C')])

        v2 = KeyboardExtended.validate_shortcut_keys("ctrl+shift+t")
        self.assertTrue(v2["valid"])
        self.assertEqual(v2["normalized_keys"], ["ctrl", "shift", "t"])

    def test_canonical_modifier_precedence(self):
        # Trigger key passed before modifier should be sorted so modifier executes first
        v = KeyboardExtended.validate_shortcut_keys("t", "ctrl")
        self.assertTrue(v["valid"])
        self.assertEqual(v["normalized_keys"], ["ctrl", "t"])

    def test_os_reserved_shortcuts_rejection(self):
        res1 = KeyboardExtended.validate_shortcut_keys("ctrl+alt+del")
        self.assertFalse(res1["valid"])
        self.assertIn("Ctrl+Alt+Del is reserved", res1["error"])

        res2 = KeyboardExtended.validate_shortcut_keys("control+alt+delete")
        self.assertFalse(res2["valid"])

    def test_unknown_key_rejection(self):
        res = KeyboardExtended.validate_shortcut_keys("ctrl+foobar")
        self.assertFalse(res["valid"])
        self.assertIn("Unknown key", res["error"])

    def test_empty_keys(self):
        res = KeyboardExtended.validate_shortcut_keys("")
        self.assertFalse(res["valid"])

if __name__ == "__main__":
    unittest.main()
