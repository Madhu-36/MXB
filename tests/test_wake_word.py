import unittest

import tests._stubs  # noqa: F401
from engine.wake_word import WakeWordGate


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestWakeWord(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.gate = WakeWordGate(mode="wake_word", follow_up_seconds=10, clock=self.clock)

    def test_ignores_background_speech(self):
        self.assertIsNone(self.gate.process("I think we should order pizza tonight"))

    def test_strips_wake_word_and_keeps_case(self):
        self.assertEqual(self.gate.process("MXB, open Google Chrome"), "open Google Chrome")
        self.gate.disengage()
        self.assertEqual(self.gate.process("Hey M.X.B. type Hello"), "type Hello")
        self.gate.disengage()
        self.assertEqual(self.gate.process("m x b what's the time"), "what's the time")

    def test_wake_word_alone(self):
        self.assertEqual(self.gate.process("Hey MXB"), "")

    def test_follow_up_window(self):
        self.gate.process("MXB open notepad")
        self.clock.now += 5
        self.assertEqual(self.gate.process("now type hello"), "now type hello")
        self.clock.now += 11
        self.assertIsNone(self.gate.process("and save it"))

    def test_always_mode(self):
        gate = WakeWordGate(mode="always")
        self.assertEqual(gate.process("open chrome"), "open chrome")

    def test_custom_name(self):
        gate = WakeWordGate(wake_words=["jarvis"], clock=self.clock)
        self.assertEqual(gate.process("Jarvis, lock the screen"), "lock the screen")
        self.assertIsNone(WakeWordGate(wake_words=["jarvis"], clock=self.clock).process("MXB lock the screen"))


if __name__ == "__main__":
    unittest.main()
