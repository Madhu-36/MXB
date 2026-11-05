import unittest
from engine.keyboard_ext import KeyboardExtended

class TestKeyboardMacros(unittest.TestCase):

    def setUp(self):
        self.kb = KeyboardExtended()

    def test_empty_macro_returns_zero(self):
        count = self.kb.execute_macro([])
        self.assertEqual(count, 0)

    def test_multi_step_macro_execution(self):
        macro = [
            {"type": "wait", "delay": 0.05},
            {"type": "tap", "key": "shift"},
            {"type": "wait", "delay": 0.05}
        ]
        executed = self.kb.execute_macro(macro)
        self.assertEqual(executed, 3)

    def test_unknown_macro_step_is_skipped(self):
        macro = [
            {"type": "unknown_action"},
            {"type": "wait", "delay": 0.02}
        ]
        executed = self.kb.execute_macro(macro)
        self.assertEqual(executed, 1)

if __name__ == "__main__":
    unittest.main()
