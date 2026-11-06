import unittest
from utils.clipboard_monitor import ClipboardMonitor

class TestClipboardMonitor(unittest.TestCase):

    def setUp(self):
        self.monitor = ClipboardMonitor(max_items=10)

    def test_add_and_retrieve_recent_items(self):
        self.monitor.add_item("First copied line")
        self.monitor.add_item("Second copied line")
        recent = self.monitor.get_recent(limit=5)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["text"], "Second copied line")
        self.assertEqual(recent[1]["text"], "First copied line")

    def test_duplicate_consecutive_suppression(self):
        self.monitor.add_item("Same copied text")
        added_again = self.monitor.add_item("Same copied text")
        self.assertFalse(added_again)
        self.assertEqual(len(self.monitor.get_recent()), 1)

    def test_fuzzy_search_clipboard(self):
        self.monitor.add_item("https://github.com/Madhu-36/MXB.git")
        self.monitor.add_item("Meeting notes from project review")
        results = self.monitor.search("github repo")
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("github.com", results[0]["text"])

    def test_clear_clipboard_history(self):
        self.monitor.add_item("Temp note")
        self.monitor.clear()
        self.assertEqual(len(self.monitor.get_recent()), 0)

if __name__ == "__main__":
    unittest.main()
