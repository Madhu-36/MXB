"""CommandBus: voice + text entry, stop, confirmations, wake word, parallel lanes."""
import threading
import time
import unittest
from unittest.mock import MagicMock

import tests._stubs  # noqa: F401
from PySide6.QtWidgets import QApplication
from engine.command_bus import CommandBus, is_info_query, is_stop_command, format_result
from engine.tts import ModalityTTS


class FakeRouter:
    def __init__(self):
        self.executor = MagicMock()
        self.executor.confirm_callback = None
        self.executor.feedback_callback = None
        self.executor.planner.current_step = ""
        self.executor.planner.abort_event = threading.Event()
        self.tts = MagicMock()
        self.calls = []
        self.block = threading.Event()
        self.block.set()

    def route(self, text, feedback_callback=None):
        self.calls.append((text, threading.current_thread().name))
        if text.startswith("slow"):
            self.block.wait(3)
        return f"MXB: done {text}"


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class TestHelpers(unittest.TestCase):
    def test_stop_detection(self):
        for s in ("stop", "Stop.", "MXB stop", "cancel", "shut up"):
            self.assertTrue(is_stop_command(s), s)
        self.assertFalse(is_stop_command("stop the timer"))

    def test_info_query(self):
        self.assertTrue(is_info_query("what's the weather in Bengaluru"))
        self.assertTrue(is_info_query("Is it going to rain?"))
        self.assertFalse(is_info_query("open chrome"))
        self.assertFalse(is_info_query("search for cats"))

    def test_format_result(self):
        self.assertEqual(format_result("MXB: Opening chrome\nAction: Launched 'chrome'"), "Opening chrome\nAction: Launched 'chrome'")


class TestCommandBus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.router = FakeRouter()
        self.bus = CommandBus({"listening": {"mode": "wake_word"}}, router=self.router)
        self.replies = []
        self.bus.reply_ready.connect(lambda text, src: self.replies.append(text))

    def tearDown(self):
        self.router.block.set()
        self.bus.shutdown()

    def test_wraps_tts_and_wires_executor(self):
        self.assertIsInstance(self.router.tts, ModalityTTS)
        self.assertEqual(self.router.executor.confirm_callback, self.bus.request_confirmation)

    def test_text_needs_no_wake_word(self):
        self.assertEqual(self.bus.submit("open notepad", "text"), "action")
        self.assertTrue(wait_for(lambda: self.router.calls))
        self.assertEqual(self.router.calls[0][0], "open notepad")

    def test_voice_without_wake_word_ignored(self):
        self.assertEqual(self.bus.submit("open notepad", "voice"), "ignored")
        time.sleep(0.1)
        self.assertEqual(self.router.calls, [])

    def test_voice_with_wake_word_routes_remainder(self):
        self.bus.submit("MXB, Type Hello", "voice")
        self.assertTrue(wait_for(lambda: self.router.calls))
        self.assertEqual(self.router.calls[0][0], "Type Hello")

    def test_stop_aborts_and_clears_queue(self):
        self.router.block.clear()
        self.bus.submit("slow task", "text")
        self.assertTrue(wait_for(lambda: self.bus.busy))
        self.bus.submit("open paint", "text")
        self.assertEqual(self.bus.action_queue.qsize(), 1)
        self.assertEqual(self.bus.submit("stop", "voice"), "stopped")  # no wake word needed
        self.router.executor.abort_current_action.assert_called()
        self.assertEqual(self.bus.action_queue.qsize(), 0)

    def test_question_answered_in_parallel_while_busy(self):
        self.router.block.clear()
        self.bus.submit("slow task", "text")
        self.assertTrue(wait_for(lambda: self.bus.busy))
        self.assertEqual(self.bus.submit("what is the capital of France?", "text"), "info")
        self.assertTrue(wait_for(lambda: len(self.router.calls) == 2))
        lanes = {name for _, name in self.router.calls}
        self.assertEqual(lanes, {"MXB-Action-Lane", "MXB-Info-Lane"})

    def test_confirmation_via_voice_yes(self):
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("v", self.bus.request_confirmation("Delete a.txt?")))
        t.start()
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.assertEqual(self.bus.submit("yes", "voice"), "confirmed")  # works without wake word
        t.join(2)
        self.assertTrue(result["v"])

    def test_confirmation_via_button_no(self):
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("v", self.bus.request_confirmation("Shut down?")))
        t.start()
        self.assertTrue(wait_for(self.bus.confirm.has_pending))
        self.bus.resolve_confirmation(False)
        t.join(2)
        self.assertFalse(result["v"])

    def test_status_query(self):
        self.assertEqual(self.bus.submit("what are you doing", "text"), "status")
        QApplication.processEvents()
        self.assertTrue(any("free" in r for r in self.replies))

    def test_dispatch_latency_metrics_tracking(self):
        self.assertEqual(self.bus.dispatch_metrics["total_dispatches"], 0)
        self.assertEqual(self.bus.average_dispatch_latency, 0.0)

        self.bus.submit("open notepad", "text")
        self.assertTrue(wait_for(lambda: self.bus.dispatch_metrics["total_dispatches"] >= 1, timeout=3.0))

        metrics = self.bus.dispatch_metrics
        self.assertGreaterEqual(metrics["total_dispatches"], 1)
        self.assertGreaterEqual(metrics["total_dispatch_time"], 0.0)
        self.assertGreaterEqual(self.bus.average_dispatch_latency, 0.0)


class TestModalityTTS(unittest.TestCase):
    def test_thread_local_speaking(self):
        inner = MagicMock()
        tts = ModalityTTS(inner)
        tts.set_thread_speaking(False)
        tts.speak("silent")
        inner.speak.assert_not_called()

        def other_thread():
            tts.speak("spoken")  # default for a new thread is speaking enabled
        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
        inner.speak.assert_called_once_with("spoken", wait=False)


if __name__ == "__main__":
    unittest.main()
