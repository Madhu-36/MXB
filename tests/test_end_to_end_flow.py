"""
End-to-end: utterance -> CommandBus -> IntentRouter -> OSExecutionManager -> mouse/keyboard.
Only the lowest-level Windows primitives (mouse, keyboard, screen capture, UIA tree,
app index, TTS) are mocked, so routing, safety, confirmation and threading are real.
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from PySide6.QtWidgets import QApplication
from engine.ui_automation import UIElement
from safety.permissions import FileAccessManager


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()  # deliver queued cross-thread signals (reply_ready)
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        patches = [
            patch("engine.executor.MouseController"),
            patch("engine.executor.KeyboardExtended"),
            patch("engine.executor.ScreenVision"),
            patch("engine.executor.SmartAppLauncher"),
            patch("engine.executor.get_file_access",
                  return_value=FileAccessManager(store_path=self.home / "p.json", default_roots=[self.home], protected_roots=[])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        from engine.executor import OSExecutionManager
        from engine.router import IntentRouter
        from engine.command_bus import CommandBus

        self.executor = OSExecutionManager(config={})
        self.executor._uia = MagicMock()
        self.executor._uia.available.return_value = True
        self.executor._uia.find_search_box.return_value = UIElement(
            name="Search YouTube", control_type="Edit", rect=(400, 100, 800, 140))
        self.router = IntentRouter(executor=self.executor, tts=MagicMock())
        self.bus = CommandBus({"listening": {"mode": "wake_word"}}, router=self.router)
        self.replies = []
        self.bus.reply_ready.connect(lambda t, s: self.replies.append(t))
        self.addCleanup(self.bus.shutdown)
        self.addCleanup(self.tmp.cleanup)

    def test_voice_search_box_flow(self):
        outcome = self.bus.submit("MXB, go to the search box and enter Cute Cats and press Enter.", "voice")
        self.assertEqual(outcome, "action")
        kb = self.executor.keyboard
        self.assertTrue(wait_for(lambda: kb.tap_key.called))
        self.executor._uia.find_search_box.assert_called_once_with("")
        self.executor.mouse.left_click.assert_called_once_with(600, 120)  # centre of the search box
        kb.select_all.assert_called_once()
        kb.type_text.assert_called_once_with("Cute Cats")
        kb.tap_key.assert_called_once_with("enter")

    def test_search_falls_back_to_keyboard_shortcut(self):
        self.executor._uia.find_search_box.return_value = None
        self.executor.screen.find_text_coordinates.return_value = None
        self.executor._uia.foreground_title.return_value = "New Tab - Google Chrome"
        res = self.executor.execute_action("search_on_screen", "weather in Bengaluru")
        self.executor.keyboard.shortcut.assert_called_with("ctrl", "l")
        self.assertIn("address bar", res)

    def test_delete_requires_spoken_yes(self):
        f = self.home / "old_notes.txt"
        f.write_text("bye")
        self.bus.submit(f"delete the file {f}", "text")
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.assertTrue(f.exists())  # nothing happens before the answer
        self.assertEqual(self.bus.submit("no", "voice"), "denied")
        self.assertTrue(wait_for(lambda: any("Cancelled" in r for r in self.replies)))
        self.assertTrue(f.exists())

    def test_delete_confirmed(self):
        f = self.home / "junk.txt"
        f.write_text("bye")
        self.bus.submit(f"permanently delete the file {f}", "text")
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.bus.submit("yes", "text")
        self.assertTrue(wait_for(lambda: not f.exists()))

    def test_delete_by_name_finds_file_and_names_it_in_question(self):
        sub = self.home / "Projects"
        sub.mkdir()
        f = sub / "old_draft.txt"
        f.write_text("x")
        questions = []
        self.bus.confirmation_requested.connect(questions.append)
        self.bus.submit("delete the file old_draft.txt", "text")
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.assertTrue(wait_for(lambda: questions))
        self.assertIn(str(f), questions[0])
        self.bus.submit("no", "text")

    def test_stop_during_confirmation_cancels(self):
        f = self.home / "keep.txt"
        f.write_text("x")
        self.bus.submit(f"permanently delete the file {f}", "text")
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.bus.submit("stop", "voice")
        self.assertTrue(wait_for(lambda: not self.bus.confirm.has_pending()))
        time.sleep(0.2)
        self.assertTrue(f.exists())

    def test_reminder_round_trip_through_bus(self):
        from datetime import datetime, timedelta
        from engine.scheduler import Scheduler
        clock = {"now": datetime(2026, 11, 7, 21, 15)}
        sched = Scheduler(self.home / "s.json", fire=self.bus._fire_job, clock=lambda: clock["now"])
        self.bus.scheduler = sched
        self.executor.services["scheduler"] = sched
        self.bus.submit("remind me in 20 minutes to stretch", "text")
        self.assertTrue(wait_for(lambda: any("remind you at 9:35 PM today to stretch" in r for r in self.replies)))
        clock["now"] += timedelta(minutes=21)
        sched.tick()
        self.assertTrue(wait_for(lambda: "Reminder: stretch" in self.replies))

    def test_undo_after_voice_move(self):
        src = self.home / "report.txt"
        src.write_text("x")
        (self.home / "Archive").mkdir()
        self.executor.journal.store_path = self.home / "journal.json"
        self.executor.journal.entries = []
        self.bus.submit(f"move {src} to {self.home / 'Archive'}", "text")
        self.assertTrue(wait_for(lambda: (self.home / "Archive" / "report.txt").exists()))
        self.bus.submit("undo the move", "text")
        self.assertTrue(wait_for(src.exists))

    def test_input_lock_serializes_parallel_typing(self):
        order = []
        kb = self.executor.keyboard

        def slow_type(text, *a, **k):
            order.append(("start", text))
            time.sleep(0.2)
            order.append(("end", text))
        kb.type_text.side_effect = slow_type
        t1 = threading.Thread(target=lambda: self.executor.execute_action("type_text", "first"))
        t2 = threading.Thread(target=lambda: self.executor.execute_action("type_text", "second"))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(2)
        t2.join(2)
        self.assertEqual(order[1], ("end", "first"))  # second never started inside first


if __name__ == "__main__":
    unittest.main()
