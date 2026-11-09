"""v4 automation: scheduler, routines, record-replay, plugins, phone remote server, v4 router phrases."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from engine.scheduler import Scheduler, parse_when, split_leading_time, split_trailing_time
from engine.routines import RoutineStore, events_to_plan
from engine.skills import SkillRegistry
from engine.remote_server import RemoteServer, is_private_address, EventLog
from engine.router import IntentRouter

NOW = datetime(2026, 11, 7, 21, 15)  # a Saturday evening


class TestTimeParsing(unittest.TestCase):
    def check(self, text, expected, recurring=False):
        r = parse_when(text, NOW)
        self.assertIsNotNone(r, text)
        self.assertEqual(r["next"], expected, text)
        self.assertEqual(r["rule"] is not None, recurring, text)

    def test_relative(self):
        self.check("in 20 minutes", NOW + timedelta(minutes=20))
        self.check("in an hour", NOW + timedelta(hours=1))
        self.check("in half an hour", NOW + timedelta(minutes=30))

    def test_absolute(self):
        self.check("at 5 pm", datetime(2026, 11, 8, 17, 0))          # already past today -> tomorrow
        self.check("at 22:30", datetime(2026, 11, 7, 22, 30))
        self.check("at 9", datetime(2026, 11, 8, 9, 0))               # 9 pm passed, so 9 am tomorrow
        self.check("at 10", datetime(2026, 11, 7, 22, 0))             # bare hour -> the next 10 o'clock (10 pm)
        self.check("tomorrow at 9 am", datetime(2026, 11, 8, 9, 0))
        self.check("on friday at 10 am", datetime(2026, 11, 13, 10, 0))
        self.check("at noon", datetime(2026, 11, 8, 12, 0))

    def test_recurring(self):
        self.check("every day at 9 am", datetime(2026, 11, 8, 9, 0), recurring=True)
        self.check("every weekday at 8:30 am", datetime(2026, 11, 9, 8, 30), recurring=True)
        self.check("every monday and wednesday at 7 pm", datetime(2026, 11, 9, 19, 0), recurring=True)
        self.check("every 2 hours", NOW + timedelta(hours=2), recurring=True)

    def test_not_a_time(self):
        for t in ("open chrome", "at", "every", "tomorrow is a holiday"):
            self.assertIsNone(parse_when(t, NOW), t)

    def test_splitting(self):
        self.assertEqual(split_leading_time("every weekday at 9 am open outlook", NOW), ("every weekday at 9 am", "open outlook"))
        self.assertEqual(split_trailing_time("call mom at 5 pm", NOW), ("call mom", "at 5 pm"))


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(NOW)
        self.fired = []
        self.s = Scheduler(Path(self.tmp.name) / "s.json", fire=self.fired.append, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_shot_reminder_fires_once(self):
        self.assertIn("remind you at 9:35 PM today to stretch", self.s.add("reminder", "in 20 minutes", "stretch"))
        self.assertEqual(self.s.tick(), [])
        self.clock.now += timedelta(minutes=21)
        self.assertEqual([j["text"] for j in self.s.tick()], ["stretch"])
        self.assertEqual(self.s.tick(), [])
        self.assertIn("no reminders", self.s.list_text())

    def test_recurring_reschedules_and_persists(self):
        self.s.add("command", "every day at 10 pm", "lock the pc")
        self.clock.now = datetime(2026, 11, 7, 22, 0, 30)
        self.assertEqual(len(self.s.tick()), 1)
        reloaded = Scheduler(self.s.store_path, clock=self.clock)
        self.assertEqual(datetime.fromisoformat(reloaded.jobs[0]["next"]), datetime(2026, 11, 8, 22, 0))

    def test_list_and_cancel(self):
        self.s.add("reminder", "in 1 hour", "check the oven")
        self.s.add("reminder", "tomorrow at 9 am", "submit the SIH form")
        self.assertIn("1. Reminder: check the oven", self.s.list_text())
        self.assertIn("Cancelled: submit the SIH form", self.s.cancel("sih form"))
        self.assertIn("Cancelled: check the oven", self.s.cancel("1"))
        self.s.add("reminder", "in 5 minutes", "a")
        self.assertIn("all 1", self.s.cancel("all"))

    def test_bad_time(self):
        self.assertIn("couldn't understand", self.s.add("reminder", "sometime soon", "x"))


class TestRoutinesAndRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RoutineStore(Path(self.tmp.name) / "r.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_routine_store(self):
        self.assertIn("3 steps", self.store.create("Work Mode", ["open vs code", "open chrome", "set volume to 30"]))
        self.assertEqual(self.store.find("work mode")[1]["commands"][0], "open vs code")
        self.assertIsNotNone(self.store.find("the work mode"))
        self.assertIsNone(self.store.find("gaming"))
        self.assertIn("Deleted", self.store.delete("work mode"))

    def test_events_to_plan(self):
        ev = [{"t": 0.0, "type": "click", "x": 100, "y": 200, "button": "left", "label": "Search"}]
        ev += [{"t": 0.5 + i * 0.1, "type": "key", "key": c, "mods": []} for i, c in enumerate("hellp")]
        ev += [{"t": 1.0, "type": "key", "key": "backspace", "mods": []},
               {"t": 1.05, "type": "key", "key": "o", "mods": []},
               {"t": 1.2, "type": "key", "key": "enter", "mods": []},
               {"t": 4.0, "type": "click", "x": 300, "y": 400, "button": "left", "label": "Password", "password": True}]
        ev += [{"t": 4.2 + i * 0.1, "type": "key", "key": c, "mods": []} for i, c in enumerate("secret")]
        ev += [{"t": 5.0, "type": "click", "x": 500, "y": 500, "button": "left", "label": ""},
               {"t": 5.2, "type": "click", "x": 501, "y": 501, "button": "left", "label": ""},
               {"t": 5.5, "type": "key", "key": "s", "mods": ["ctrl_l"]}]
        steps, skipped = events_to_plan(ev)
        self.assertEqual(skipped, 6)
        self.assertEqual(steps[0], {"action": "click_element", "target": "Search || 100,200"})
        self.assertEqual(steps[1], {"action": "type_text", "target": "hello"})
        self.assertEqual(steps[2], {"action": "press_key", "target": "enter"})
        self.assertEqual(steps[3]["action"], "wait")
        self.assertIn({"action": "double_click", "target": "501,501"}, steps)
        self.assertEqual(steps[-1], {"action": "shortcut", "target": "ctrl+s"})
        self.assertFalse(any("secret" in s["target"] for s in steps))


class TestExecutorRoutines(unittest.TestCase):
    def setUp(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from engine.executor import OSExecutionManager
        self.ex = OSExecutionManager(config={})
        self.ex._routines = RoutineStore(Path(self.tmp.name) / "r.json")
        self.ran = []
        self.ex.command_runner = self.ran.append

    def test_create_and_run_spoken_routine(self):
        self.ex.execute_action("create_routine", "focus :: open vs code; mute audio then set volume to 20")
        res = self.ex.execute_action("run_routine", "focus")
        self.assertEqual(self.ran, ["open vs code", "mute audio", "set volume to 20"])
        self.assertIn("3 steps", res)

    def test_run_recording_through_planner(self):
        self.ex._routines.save_recording("login", [{"action": "type_text", "target": "hi"}, {"action": "press_key", "target": "enter"}])
        self.ex.execute_action("run_routine", "login")
        self.ex.keyboard.type_text.assert_called_with("hi")
        self.ex.keyboard.tap_key.assert_called_with("enter")

    def test_reminder_without_scheduler(self):
        self.assertIn("isn't running", self.ex.execute_action("set_reminder", "in 5 minutes :: stretch"))


class TestSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "greet.py").write_text(
            "from engine.skills import skill\n"
            "@skill(name='greet_person', patterns=[r'^say hello to (?P<target>.+)$'], description='Greets someone')\n"
            "def greet(target, ctx):\n    return f'Hello {target}!'\n"
            "@skill(name='crashy', patterns=[r'^crash now$'])\n"
            "def crashy(target, ctx):\n    raise ValueError('boom')\n")
        (self.dir / "broken.py").write_text("this is not python")
        (self.dir / "clash.py").write_text(
            "from engine.skills import skill\n@skill(name='open_app')\ndef f(t, c):\n    return 'hijacked'\n")
        (self.dir / "off.py").write_text(
            "from engine.skills import skill\n@skill(name='disabled_one', patterns=[r'^nope$'])\ndef f(t, c):\n    return 'x'\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_match_run_and_isolation(self):
        reg = SkillRegistry(self.dir, disabled=["off"])
        reg.load_all()
        self.assertEqual(set(reg.skills), {"greet_person", "crashy"})
        self.assertIn("broken.py", reg.errors)
        sk, target = reg.match("Say hello to Ravi")
        self.assertEqual((sk.name, target), ("greet_person", "Ravi"))
        self.assertEqual(reg.run("greet_person", "Ravi"), "Hello Ravi!")
        self.assertIn("failed: boom", reg.run("crashy", ""))
        self.assertIsNone(reg.match("nope"))

    def test_shipped_example_plugins_load(self):
        reg = SkillRegistry(Path(__file__).parent.parent / "plugins")
        reg.load_all()
        self.assertTrue({"quick_note", "read_notes", "play_youtube"} <= set(reg.skills))
        self.assertEqual(reg.match("play lofi hip hop on youtube")[1], "lofi hip hop")


class FakeBus(QObject):
    user_message = Signal(str, str)
    reply_ready = Signal(str, str)
    feedback = Signal(str)
    status_changed = Signal(str)
    confirmation_requested = Signal(str)
    confirmation_resolved = Signal(bool)

    def __init__(self):
        super().__init__()
        self.submitted, self.resolved, self.busy = [], [], False
        self.confirm = MagicMock()
        self.confirm.has_pending.return_value = False

    def submit(self, text, source="text"):
        self.submitted.append((text, source))
        self.reply_ready.emit(f"done {text}", source)
        return "action"

    def resolve_confirmation(self, approved):
        self.resolved.append(approved)

    def describe_status(self):
        return "I'm free."


class TestRemoteServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bus = FakeBus()
        self.server = RemoteServer(self.bus, {"remote": {"host": "127.0.0.1", "port": 0}},
                                   store_path=Path(self.tmp.name) / "remote.json",
                                   screen_grabber=lambda: Image.new("RGB", (1600, 900), "navy"))
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def req(self, path, method="GET", body=None, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {self.server.token if token is True else token}"
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        r = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), ""

    def test_page_is_public_but_api_needs_token(self):
        code, body, ctype = self.req("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"MXB Remote", body)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertEqual(self.req("/api/status", token=False)[0], 401)
        self.assertEqual(self.req("/api/status", token="wrong-token-value-xyz")[0], 401)
        self.assertEqual(json.loads(self.req("/api/status")[1])["status"], "I'm free.")

    def test_command_events_confirm_stop(self):
        code, body, _ = self.req("/api/command", "POST", {"text": "open notepad"})
        self.assertEqual((code, json.loads(body)["result"]), (200, "action"))
        self.assertEqual(self.bus.submitted[-1], ("open notepad", "phone"))
        events = json.loads(self.req("/api/events?after=0&wait=1")[1])["events"]
        self.assertIn(("reply", "done open notepad"), [(e["type"], e["text"]) for e in events])
        self.req("/api/confirm", "POST", {"approved": True})
        self.assertEqual(self.bus.resolved, [True])
        self.req("/api/stop", "POST", {})
        self.assertEqual(self.bus.submitted[-1], ("stop", "phone"))

    def test_long_poll_wakes_on_new_event(self):
        threading.Timer(0.3, lambda: self.server.events.push("reply", "late")).start()
        start = time.time()
        events = json.loads(self.req("/api/events?after=0&wait=5")[1])["events"]
        self.assertLess(time.time() - start, 3)
        self.assertEqual(events[-1]["text"], "late")

    def test_screen_peek_is_downscaled_jpeg(self):
        code, body, ctype = self.req("/api/screen")
        self.assertEqual((code, ctype), (200, "image/jpeg"))
        import io
        self.assertEqual(Image.open(io.BytesIO(body)).width, 1280)

    def test_lockout_after_ten_bad_tokens(self):
        for _ in range(10):
            self.req("/api/status", token="bad-token-1234567890")
        self.assertEqual(self.req("/api/status")[0], 429)  # even the right token is refused for a while

    def test_token_persists_and_rotates(self):
        again = RemoteServer(None, {}, store_path=Path(self.tmp.name) / "remote.json")
        self.assertEqual(again.token, self.server.token)
        old = again.token
        self.assertNotEqual(again.rotate_token(), old)

    def test_private_address_check(self):
        for ok in ("127.0.0.1", "192.168.1.20", "10.0.0.5", "172.20.1.1", "::1", "fe80::1"):
            self.assertTrue(is_private_address(ok), ok)
        for bad in ("8.8.8.8", "142.250.1.1", "not-an-ip"):
            self.assertFalse(is_private_address(bad), bad)

    def test_eventlog_since(self):
        log = EventLog()
        log.push("a", "1")
        log.push("b", "2")
        self.assertEqual([e["text"] for e in log.since(1)], ["2"])


class TestV4Router(unittest.TestCase):
    CASES = [
        ("show numbers", ("show_marks", "")),
        ("click 12", ("click_mark", "12")),
        ("type Hello World in 3", ("type_mark", "3 :: Hello World")),
        ("undo the move", ("undo_last", "")),
        ("what do you remember about me", ("recall_memories", "")),
        ("forget my old address", ("forget_memory", "my old address")),
        ("I use VS Code for everything", ("remember_preference", "I use VS Code for everything")),
        ("ask my documents when is the SIH deadline", ("ask_documents", "when is the SIH deadline")),
        ("index my Documents folder", ("index_folder", "Documents")),
        ("remind me in 20 minutes to stretch", ("set_reminder", "in 20 minutes :: stretch")),
        ("remind me to call Mom at 5 pm", ("set_reminder", "at 5 pm :: call Mom")),
        ("every monday at 9 am remind me to send the report", ("set_reminder", "every monday at 9 am :: send the report")),
        ("schedule open Outlook every weekday at 9 am", ("schedule_command", "every weekday at 9 am :: open Outlook")),
        ("every day at 10 pm lock the pc", ("schedule_command", "every day at 10 pm :: lock the pc")),
        ("list my reminders", ("list_schedules", "")),
        ("cancel all reminders", ("cancel_schedule", "all")),
        ("create a routine called work mode: open vs code; open chrome", ("create_routine", "work mode :: open vs code; open chrome")),
        ("run the work mode routine", ("run_routine", "work mode")),
        ("start recording expense report", ("start_recording", "expense report")),
        ("stop recording", ("stop_recording", "")),
        ("turn on phone remote", ("phone_remote", "on")),
        ("turn off the phone remote", ("phone_remote", "off")),
    ]

    def setUp(self):
        self.ex = MagicMock()
        self.ex.execute_action.return_value = "ok"
        self.ex.skills.match.return_value = None
        self.ex.journal.seconds_since_last.return_value = None
        self.router = IntentRouter(executor=self.ex, tts=MagicMock())

    def test_phrases(self):
        for phrase, expected in self.CASES:
            with self.subTest(phrase=phrase):
                self.ex.execute_action.reset_mock()
                self.router.route(phrase)
                self.assertEqual(self.ex.execute_action.call_args.args, expected)

    def test_plugin_skill_routed_first(self):
        sk = MagicMock()
        sk.name = "quick_note"
        self.ex.skills.match.return_value = (sk, "the demo is Friday")
        self.router.route("note that the demo is Friday")
        self.ex.execute_action.assert_called_with("quick_note", "the demo is Friday")

    def test_undo_that_uses_journal_only_when_recent(self):
        self.ex.journal.seconds_since_last.return_value = 30
        self.router.route("undo that")
        self.ex.execute_action.assert_called_with("undo_last", "")
        self.ex.execute_action.reset_mock()
        self.ex.journal.seconds_since_last.return_value = 900
        self.router.route("undo that")
        self.ex.execute_action.assert_called_with("undo")  # old behaviour: Ctrl+Z

    def test_run_routine_only_when_it_exists(self):
        self.ex.routines.find.return_value = ("work mode", {"type": "commands"})
        self.router.route("run work mode")
        self.ex.execute_action.assert_called_with("run_routine", "work mode")


if __name__ == "__main__":
    unittest.main()
