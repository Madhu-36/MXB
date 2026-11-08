"""v4.3 wiring: router -> executor -> feature, safety scopes, confirmations, speech rate, background services."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from PySide6.QtWidgets import QApplication

from engine.accessibility import AccessibilityMode
from engine.actions_catalog import risk_of, uses_input
from engine.executor import V43_ACTIONS, OSExecutionManager
from engine.focus_coach import ActivityStore, FocusCoach
from engine.router import IntentRouter
from engine.ui_automation import UIElement
from safety.injection import ALWAYS_DENIED, READ_ONLY_OR_PAUSE, scope_for_goal


class SilentTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text, wait=False):
        self.spoken.append(text)

    def speaking_enabled(self):
        return False

    def stop(self):
        pass


class Recorder:
    """Stands in for one v4.3 feature object and records which method was called."""

    def __init__(self, active=False):
        self.calls, self.active, self.enabled = [], active, False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.calls.append((name, args))
            return f"{name}:{args[0] if args else ''}"
        return method


def new_executor(test, config=None):
    """A real executor with the Windows-only input/screen classes replaced (portable)."""
    for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
        p = patch(f"engine.executor.{target}")
        p.start()
        test.addCleanup(p.stop)
    ex = OSExecutionManager(config=config if config is not None else {})
    ex.audit = MagicMock()
    return ex


def make_executor(test):
    ex = new_executor(test)
    ex._meetings, ex._access, ex._coach = Recorder(), Recorder(), Recorder()
    return ex


class TestExecutorDispatch(unittest.TestCase):
    def test_every_v43_action_reaches_its_feature(self):
        ex = make_executor(self)
        expected = {
            "meeting_start": ("_meetings", "start", "Weekly sync"), "meeting_stop": ("_meetings", "stop", None),
            "meeting_status": ("_meetings", "status", "just"), "meeting_list": ("_meetings", "list_meetings", None),
            "meeting_recap": ("_meetings", "recap", "last"),
            "accessibility_mode": ("_access", "enable", None), "describe_screen": ("_access", "describe_screen", None),
            "where_am_i": ("_access", "where_am_i", None), "read_this": ("_access", "read_this", None),
            "navigate_screen": ("_access", "navigate", "next button"), "activate_element": ("_access", "activate", None),
            "speech_rate": ("_access", "set_rate", "faster"), "windows_accessibility": ("_access", "windows_tool", "narrator"),
            "focus_start": ("_coach", "start_session", "25 minutes"), "focus_stop": ("_coach", "stop_session", None),
            "focus_status": ("_coach", "status", None), "screen_time": ("_coach", "report", "today"),
            "screen_time_tracking": ("_coach", "set_tracking", True), "eye_breaks": ("_coach", "set_eye_breaks", "on"),
        }
        self.assertEqual(set(expected) | {"screen_time_forget"}, set(V43_ACTIONS))
        for action, (owner, method, arg) in expected.items():
            target = arg if isinstance(arg, str) else ""
            ex.execute_action(action, target)
            name, args = getattr(ex, owner).calls[-1]
            self.assertEqual(name, method, action)
            if arg is not None:
                self.assertEqual(args[0], arg, action)

    def test_off_switches_and_defaults(self):
        ex = make_executor(self)
        ex.execute_action("accessibility_mode", "off")
        self.assertEqual(ex._access.calls[-1][0], "disable")
        ex.execute_action("screen_time_tracking", "off")
        self.assertEqual(ex._coach.calls[-1], ("set_tracking", (False,)))
        ex.execute_action("windows_accessibility", "")
        self.assertEqual(ex._access.calls[-1], ("windows_tool", ("magnifier",)))
        ex.execute_action("screen_time", "")
        self.assertEqual(ex._coach.calls[-1], ("report", ("today",)))

    def test_summarize_the_meeting_during_a_call_means_so_far(self):
        ex = make_executor(self)
        ex._meetings.active = True
        ex.execute_action("meeting_recap", "")
        self.assertEqual(ex._meetings.calls[-1], ("status", ("so far",)))

    def test_forgetting_screen_time_needs_a_yes(self):
        ex = make_executor(self)
        self.assertEqual(risk_of("screen_time_forget"), "confirm")
        ex.confirm_callback = lambda question: False
        self.assertIn("Cancelled", ex.execute_action("screen_time_forget", ""))
        self.assertEqual(ex._coach.calls, [])
        ex.confirm_callback = lambda question: True
        ex.execute_action("screen_time_forget", "")
        self.assertEqual(ex._coach.calls[-1][0], "forget_data")

    def test_input_actions_hold_the_input_lock(self):
        for action in ("navigate_screen", "activate_element", "read_this", "windows_accessibility"):
            self.assertTrue(uses_input(action), action)
        self.assertFalse(uses_input("describe_screen"))


class TestAgentSafety(unittest.TestCase):
    def test_web_pages_cannot_start_recording_or_tracking(self):
        scope = scope_for_goal("open the hackathon page and read the rules")
        for action in ("meeting_start", "meeting_status", "focus_start", "screen_time", "screen_time_tracking",
                       "accessibility_mode", "speech_rate", "scam_report", "eye_breaks"):
            self.assertIn(action, ALWAYS_DENIED)
            self.assertEqual(scope.check(action, "")[0], "deny", action)

    def test_agent_may_check_a_page_for_scams(self):
        scope = scope_for_goal("open the payment page")
        self.assertEqual(scope.check("scam_check", "")[0], "allow")
        scope.mark_suspicious(["ignore previous instructions"])
        self.assertIn("scam_check", READ_ONLY_OR_PAUSE)
        self.assertEqual(scope.check("scam_check", "")[0], "allow")   # read-only, so still fine on a hostile page


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_voice_command_to_focus_session_and_report(self):
        ex = new_executor(self)
        said = []
        probe_state = {"app": "code.exe", "title": "main.py - Visual Studio Code"}
        clock = SimpleNamespace(t=time.mktime((2026, 11, 9, 9, 0, 0, 0, 0, -1)))
        ex._coach = FocusCoach({"focus": {}}, said.append, store=ActivityStore(Path(self.tmp.name) / "a.db"),
                               probe=lambda: (probe_state["app"], probe_state["title"], 0.0, 1), clock=lambda: clock.t,
                               save_setting=lambda k, v: ex.save_setting("focus", k, v), background=False)
        router = IntentRouter(executor=ex, tts=SilentTTS())
        with patch("utils.paths.save_config"):
            out = router.route("Start a 30 minute focus session for DSA practice")
            self.assertIn("Focus session started: 30 minutes on 'DSA practice'", out)
            ex._coach.tracker.tick()
            for _ in range(4):
                clock.t += 5
                ex._coach.tracker.tick()
            probe_state.update(app="chrome.exe", title="Shorts - YouTube - Google Chrome")
            for _ in range(2):
                clock.t += 5
                ex._coach.tracker.tick()
            self.assertEqual(said, ["You're on YouTube. 30 min left on 'DSA practice'. Back to it?"])
            self.assertIn("focused under a minute", router.route("how much time is left in my focus session"))
            self.assertIn("Stopped 'DSA practice'", router.route("stop the focus session"))
            self.assertIn("app and site names", router.route("track my screen time"))
            self.assertTrue(ex.config["focus"]["track_activity"])

    def test_voice_navigation_reads_without_clicking(self):
        ex = new_executor(self)
        elements = [UIElement("Send", "Button", rect=(300, 500, 380, 524)), UIElement("To", "Edit", rect=(100, 40, 400, 64))]
        ex._uia = SimpleNamespace(available=lambda: True, foreground_title=lambda: "New message - Mail",
                                  collect=lambda: (elements, 0), focused=lambda: elements[1])
        clicks, moves = [], []
        ex.mouse = SimpleNamespace(left_click=lambda x, y: clicks.append((x, y)),
                                   move_to=lambda x, y, smooth=False: moves.append((x, y)))
        router = IntentRouter(executor=ex, tts=SilentTTS())
        self.assertIn("Send, button, 1 of 1.", router.route("next button"))
        self.assertEqual((clicks, moves), ([], [(340, 512)]))
        self.assertIn("Activated Send, button.", router.route("activate"))
        self.assertEqual(clicks, [(340, 512)])
        self.assertIn("You're in New message - Mail.", router.route("what is focused"))

    def test_accessibility_focus_speech_interrupts_first(self):
        ex = new_executor(self)
        events = []
        ex.interrupt_speech = lambda: events.append("interrupt")
        ex.speak = lambda text: events.append(text)
        ex._speak_now("Search, edit box.")
        self.assertEqual(events, ["interrupt", "Search, edit box."])
        self.assertIsInstance(ex.access, AccessibilityMode)


class TestBusWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_bus(self, executor, config=None):
        from engine.command_bus import CommandBus
        router = SimpleNamespace(executor=executor, tts=MagicMock(), route=lambda text, feedback_callback=None: "MXB: ok")
        return CommandBus(config or {"listening": {"mode": "always"}}, router=router)

    def test_speech_rate_and_interrupt_hooks(self):
        ex = new_executor(self)
        bus = self.make_bus(ex)
        inner = SimpleNamespace(rate_percent=5, set_rate=lambda p: max(-50, min(100, int(p))), interrupt=MagicMock(),
                                speak=lambda *a, **k: None)
        bus.tts._inner = inner
        try:
            with patch("utils.paths.save_config") as save:
                self.assertEqual(ex.speech_rate(None), 5)
                self.assertEqual(ex.speech_rate(250), 100)
                self.assertEqual(ex.config["voice"]["rate_percent"], 100)
                self.assertTrue(save.called)
            ex.interrupt_speech()
            self.assertTrue(inner.interrupt.called)
        finally:
            bus.shutdown()

    def test_clipboard_guard_and_opt_in_coach(self):
        ex = new_executor(self)
        bus = self.make_bus(ex, {"listening": {"mode": "always"}, "focus": {}})
        try:
            with patch("engine.scam_shield.ClipboardGuard.start") as start:
                bus.start_services(scheduler=False, remote=False)
                self.assertTrue(start.called)
            self.assertIsNotNone(bus.clipboard_guard)
            self.assertIsNone(ex._coach)                       # not asked for: no tracker, no database
        finally:
            bus.shutdown()
        ex2 = new_executor(self)
        bus2 = self.make_bus(ex2, {"listening": {"mode": "always"}, "focus": {"eye_break_minutes": 20},
                                   "scam_shield": {"watch_clipboard": False}})
        try:
            with patch("engine.focus_coach.FocusCoach.start") as start:
                bus2.start_services(scheduler=False, remote=False)
                self.assertTrue(start.called)
            self.assertIsNone(bus2.clipboard_guard)
        finally:
            bus2.shutdown()

    def test_shutdown_saves_meeting_notes_and_stops_features(self):
        ex = new_executor(self)
        ex._meetings, ex._access, ex._coach = Recorder(active=True), Recorder(), Recorder()
        with patch.object(ex._meetings, "stop", create=True, return_value="saved") as stop:
            ex.shutdown()
        stop.assert_called_once_with(summarize_notes=False, timeout=10)   # never wait minutes for an AI summary on exit
        self.assertEqual(ex._access.calls[0][0], "stop")
        self.assertEqual(ex._coach.calls[0][0], "shutdown")


class TestWindowsCheck(unittest.TestCase):
    def test_checks_report_instead_of_crashing(self):
        import sys as _sys
        from utils import windows_check as wc
        wc.RESULTS.clear()

        @wc.check("passes")
        def ok():
            return "fine"

        @wc.check("breaks")
        def broken():
            raise ValueError("nope")

        @wc.check("windows only", windows_only=True)
        def win():
            return "ran"

        ok(), broken(), win()
        statuses = {name: status for status, name, _ in wc.RESULTS}
        self.assertEqual(statuses["passes"], "PASS")
        self.assertEqual(statuses["breaks"], "FAIL")
        self.assertIn("ValueError: nope", next(d for s, n, d in wc.RESULTS if n == "breaks"))
        self.assertEqual(statuses["windows only"], "PASS" if _sys.platform == "win32" else "SKIP")
        if _sys.platform != "win32":           # on Windows the real check touches devices; CI runs it separately
            wc.RESULTS.clear()
            fails = wc.main()
            self.assertEqual(len(wc.RESULTS), 12)
            self.assertTrue(all(status in ("PASS", "FAIL", "SKIP") for status, _, _ in wc.RESULTS))
            self.assertEqual(fails, sum(1 for status, _, _ in wc.RESULTS if status == "FAIL"))
        wc.RESULTS.clear()


class TestThreadHygiene(unittest.TestCase):
    def test_no_stray_threads_after_a_focus_session(self):
        before = {t.name for t in threading.enumerate()}
        tmp = tempfile.TemporaryDirectory()
        try:
            coach = FocusCoach({"focus": {}}, lambda text: None, store=ActivityStore(Path(tmp.name) / "a.db"),
                               probe=lambda: ("code.exe", "", 0.0, 0), interval=0.01)
            coach.start_session("1 minute")
            time.sleep(0.05)
            coach.shutdown()
        finally:
            tmp.cleanup()
        self.assertNotIn("mxb-focus-tracker", {t.name for t in threading.enumerate()} - before)


if __name__ == "__main__":
    unittest.main()
