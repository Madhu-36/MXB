import unittest
import time
from utils.timer_manager import TimerManager

class TestTimerManager(unittest.TestCase):

    def setUp(self):
        self.tm = TimerManager()

    def test_natural_duration_parsing(self):
        self.assertEqual(TimerManager.parse_duration("5 minutes"), 300)
        self.assertEqual(TimerManager.parse_duration("1 minute 30 seconds"), 90)
        self.assertEqual(TimerManager.parse_duration("45 seconds"), 45)
        self.assertEqual(TimerManager.parse_duration("2 hours"), 7200)
        self.assertEqual(TimerManager.parse_duration("1h 10m 5s"), 4205)
        self.assertEqual(TimerManager.parse_duration("60"), 60)
        self.assertEqual(TimerManager.parse_duration("random string"), 0)

    def test_start_and_cancel_timer(self):
        res = self.tm.start_timer("TeaTimer", 120)
        self.assertTrue(res["success"])
        self.assertEqual(res["duration_sec"], 120)

        rem = self.tm.get_remaining_seconds("TeaTimer")
        self.assertIsNotNone(rem)
        self.assertGreaterEqual(rem, 118)

        active = self.tm.list_active_timers()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["label"], "TeaTimer")

        self.assertTrue(self.tm.cancel_timer("TeaTimer"))
        self.assertIsNone(self.tm.get_remaining_seconds("TeaTimer"))

    def test_timer_completion_callback(self):
        completed = []
        def on_done(label):
            completed.append(label)

        self.tm.start_timer("FastTimer", 1, on_complete=on_done)
        time.sleep(1.3)
        self.assertIn("FastTimer", completed)

if __name__ == "__main__":
    unittest.main()
