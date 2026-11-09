"""v4.3 focus & study coach: classification, sessions and nudges, screen-time reports, eye breaks."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import tests._stubs  # noqa: F401
from engine.focus_coach import (
    calculate_productivity_metrics,
    DISTRACTION, FOCUS, IDLE, MEETING, NEUTRAL, ActivityStore, ActivityTracker, FocusCoach, Sample, classify,
    label_mentioned, minutes_text, parse_session_request,
)


class Clock:
    def __init__(self, t=None):
        self.t = t if t is not None else time.mktime((2026, 11, 9, 10, 0, 0, 0, 0, -1))   # 10:00 local

    def __call__(self):
        return self.t


class Probe:
    """The foreground window the fake user is looking at."""

    def __init__(self):
        self.app, self.title, self.idle, self.hwnd = "code.exe", "main.py - mxb - Visual Studio Code", 0.0, 42

    def __call__(self):
        return self.app, self.title, self.idle, self.hwnd

    def show(self, app, title="", idle=0.0, hwnd=42):
        self.app, self.title, self.idle, self.hwnd = app, title, idle, hwnd


class TestClassify(unittest.TestCase):
    def test_apps(self):
        self.assertEqual(classify("Code.exe", "x - Visual Studio Code"), ("VS Code", FOCUS, False))
        self.assertEqual(classify("WINWORD.EXE", "Report.docx - Word")[1], FOCUS)
        self.assertEqual(classify("Discord.exe", "#general")[1], DISTRACTION)
        self.assertEqual(classify("valorant.exe", "VALORANT"), ("Valorant", NEUTRAL, False))
        self.assertEqual(classify("Zoom.exe", "Zoom Meeting")[1], MEETING)
        self.assertEqual(classify("Zoom.exe", "Zoom Workplace")[1], "communication")
        self.assertEqual(classify("ms-teams.exe", "Call with Ravi | Microsoft Teams")[1], MEETING)

    def test_browser_sites_from_titles(self):
        self.assertEqual(classify("chrome.exe", "Lofi beats to study to - YouTube - Google Chrome"),
                         ("YouTube", DISTRACTION, True))
        self.assertEqual(classify("msedge.exe", "Two Sum - LeetCode - Personal - Microsoft​ Edge")[0], "LeetCode")
        self.assertEqual(classify("firefox.exe", "(3) Instagram — Mozilla Firefox")[0], "Instagram")
        self.assertEqual(classify("chrome.exe", "Home / X - Google Chrome")[0], "X (Twitter)")
        self.assertEqual(classify("chrome.exe", "Meet - abc-defg-hij - Google Chrome")[1], MEETING)
        self.assertEqual(classify("chrome.exe", "Bank statement - Google Chrome"), ("Web browsing", NEUTRAL, False))
        # the site name at the end wins over words in the page title
        self.assertEqual(classify("chrome.exe", "LeetCode 75 explained - YouTube - Google Chrome")[0], "YouTube")

    def test_user_overrides(self):
        self.assertEqual(classify("chrome.exe", "NPTEL week 4 - YouTube - Google Chrome", productive=["YouTube"])[1], FOCUS)
        self.assertEqual(classify("valorant.exe", "", distracting=["valorant"])[1], DISTRACTION)


class TestParsing(unittest.TestCase):
    def test_session_requests(self):
        self.assertEqual(parse_session_request("50 minutes for DSA practice"), (50, "DSA practice", False, set()))
        self.assertEqual(parse_session_request("strict 1 hour on ML notes, allow YouTube and LeetCode"),
                         (60, "ML notes", True, {"youtube", "leetcode"}))
        self.assertEqual(parse_session_request("a focus session for 1.5 hours"), (90, "", False, set()))
        self.assertEqual(parse_session_request("half an hour to revise OS"), (30, "revise OS", False, set()))
        self.assertEqual(parse_session_request(""), (25, "", False, set()))
        self.assertEqual(parse_session_request("pomodoro", 30)[0], 25)
        self.assertEqual(parse_session_request("DSA practice for 30 minutes"), (30, "DSA practice", False, set()))
        self.assertEqual(parse_session_request("900 minutes")[0], 240)

    def test_text_helpers(self):
        self.assertEqual(minutes_text(30), "under a minute")
        self.assertEqual(minutes_text(25 * 60), "25 min")
        self.assertEqual(minutes_text(3900), "1 h 5 min")
        self.assertEqual(minutes_text(7200), "2 h")
        self.assertTrue(label_mentioned("YouTube", "how long on youtube this week"))
        self.assertTrue(label_mentioned("X (Twitter)", "time on twitter"))
        self.assertFalse(label_mentioned("Web browsing", "screen time today"))


class TestStoreAndTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ActivityStore(Path(self.tmp.name) / "activity.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_adds_up_per_day_and_never_has_titles(self):
        self.store.add_usage("2026-11-09", "YouTube", DISTRACTION, 30)
        self.store.add_usage("2026-11-09", "YouTube", DISTRACTION, 45)
        self.store.add_usage("2026-11-08", "VS Code", FOCUS, 600)
        self.assertEqual(self.store.usage("2026-11-09", "2026-11-09"), [("YouTube", DISTRACTION, 75.0)])
        self.assertEqual(len(self.store.usage("2026-11-01", "2026-11-09")), 2)
        conn = sqlite3.connect(self.store.path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage)")]
        conn.close()
        self.assertEqual(cols, ["day", "label", "category", "seconds"])
        self.store.forget()
        self.assertEqual(self.store.usage("2026-01-01", "2026-12-31"), [])

    def test_tracker_counts_time_skips_idle_and_sleep_gaps(self):
        clock, probe = Clock(), Probe()
        tracker = ActivityTracker(probe=probe, store=self.store, interval=5, clock=clock)
        tracker.store_usage = True
        seen = []
        tracker.listeners.append(seen.append)
        tracker.tick()                                       # first sample: nothing to count yet
        for _ in range(6):
            clock.t += 5
            tracker.tick()                                   # 30 s of VS Code
        probe.show("chrome.exe", "Some page - Google Chrome", idle=300)
        clock.t += 5
        tracker.tick()                                       # away from the keyboard: idle, not counted
        probe.show("chrome.exe", "Lecture - YouTube - Google Chrome", idle=300)
        clock.t += 5
        tracker.tick()                                       # but watching a video without touching anything counts
        clock.t += 3600                                      # laptop slept for an hour
        tracker.tick()
        tracker.flush()
        usage = dict((label, sec) for label, _, sec in self.store.usage("2000-01-01", "2100-01-01"))
        self.assertEqual(usage, {"VS Code": 30.0, "YouTube": 20.0})   # 5 s + the sleep gap capped at 15 s
        self.assertEqual(seen[7].category, IDLE)

    def test_nothing_is_stored_unless_tracking_is_on(self):
        clock, probe = Clock(), Probe()
        tracker = ActivityTracker(probe=probe, store=self.store, interval=5, clock=clock)
        for _ in range(3):
            tracker.tick()
            clock.t += 5
        tracker.flush()
        self.assertEqual(self.store.usage("2000-01-01", "2100-01-01"), [])

    def test_background_thread_runs_and_stops_cleanly(self):
        probe = Probe()
        tracker = ActivityTracker(probe=probe, store=self.store, interval=0.01)
        tracker.store_usage = True
        tracker.start()
        deadline = time.time() + 3
        while time.time() < deadline:
            tracker.flush()
            if self.store.usage("2000-01-01", "2100-01-01"):
                break
            time.sleep(0.02)
        tracker.stop()
        self.assertFalse(tracker.running)
        self.assertEqual(self.store.usage("2000-01-01", "2100-01-01")[0][0], "VS Code")


class TestCoach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ActivityStore(Path(self.tmp.name) / "activity.db")
        self.clock, self.probe = Clock(), Probe()
        self.said, self.minimized, self.saved = [], [], {}
        self.meeting = False
        self.coach = FocusCoach({"focus": {}}, self.said.append, store=self.store, probe=self.probe, clock=self.clock,
                                minimize=self.minimized.append, save_setting=self.saved.__setitem__,
                                meeting_active=lambda: self.meeting, background=False)
        self.coach.tracker.tick()

    def tearDown(self):
        self.coach.shutdown()
        self.tmp.cleanup()

    def run_for(self, seconds, step=5):
        for _ in range(int(seconds / step)):
            self.clock.t += step
            self.coach.tracker.tick()

    def test_session_nudges_after_ten_seconds_on_a_distraction(self):
        self.assertEqual(self.coach.start_session("25 minutes for DSA practice"),
                         "Focus session started: 25 minutes on 'DSA practice'. I'll nudge you if you drift to a distraction.")
        self.run_for(60)
        self.probe.show("chrome.exe", "Cricket highlights - YouTube - Google Chrome")
        self.run_for(5)
        self.assertEqual(self.said, [])                      # 5 s: no nag for a quick look
        self.run_for(5)
        self.assertEqual(self.said, ["You're on YouTube. 24 min left on 'DSA practice'. Back to it?"])
        self.run_for(60)
        self.assertEqual(len(self.said), 1)                  # no repeat for 2 minutes
        self.run_for(60)
        self.assertEqual(len(self.said), 2)
        self.assertEqual(self.minimized, [])                 # gentle mode never touches windows
        self.probe.show("code.exe")
        self.run_for(30)
        self.assertEqual(self.coach.status(), "21 min left on 'DSA practice'. So far: focused 2 min, distracted 2 min.")

    def test_session_completes_with_a_summary_and_is_saved(self):
        self.coach.start_session("30 minutes on ML notes")
        self.run_for(20 * 60)
        self.probe.show("chrome.exe", "Reels - Instagram - Google Chrome")
        self.run_for(5 * 60)
        self.probe.show("explorer.exe", "Downloads")
        self.run_for(5 * 60 + 5)
        summary = self.said[-1]
        self.assertTrue(summary.startswith("Focus session done: 30 min on 'ML notes'. Focused 20 min, distracted 5 min "
                                           "(Instagram 5 min), other apps 5 min."), summary)
        self.assertIn("Take a 5-minute break", summary)
        self.assertIsNone(self.coach.session)
        rows = self.store.sessions_since(0)
        self.assertEqual((rows[0]["goal"], rows[0]["completed"], rows[0]["nudges"]), ("ML notes", 1, 3))

    def test_strict_mode_minimizes_and_allowed_sites_pass(self):
        self.coach.start_session("strict 50 minutes for lectures, allow YouTube")
        self.probe.show("chrome.exe", "NPTEL lecture 7 - YouTube - Google Chrome", hwnd=7)
        self.run_for(60)
        self.assertEqual((self.said, self.minimized), ([], []))
        self.probe.show("chrome.exe", "Home / X - Google Chrome", hwnd=9)
        self.run_for(10)
        self.assertEqual(self.minimized, [9])
        self.assertIn("X (Twitter) is off limits until 'lectures' ends. I minimized it.", self.said[-1])
        self.run_for(15)
        self.assertEqual(self.minimized, [9, 9])             # strict re-checks every 15 s

    def test_stop_early_and_one_session_at_a_time(self):
        self.coach.start_session("")
        self.assertIn("already in a focus session", self.coach.start_session("10 minutes"))
        self.run_for(10 * 60)
        self.assertEqual(self.coach.stop_session(), "Stopped your focus session after 10 min. Focused 10 min.")
        self.assertEqual(self.coach.stop_session(), "There's no focus session running.")
        self.assertIn("No focus session is running", self.coach.status())

    def test_reports_need_opt_in_and_hold_only_names(self):
        self.assertIn("not tracking screen time yet", self.coach.report("today"))
        self.assertIn("app and site names", self.coach.set_tracking(True))
        self.assertEqual(self.saved["track_activity"], True)
        self.run_for(40 * 60)                                # VS Code
        self.probe.show("chrome.exe", "Shorts - YouTube - Google Chrome")
        self.run_for(15 * 60)
        self.probe.show("whatsapp.exe", "WhatsApp")
        self.run_for(5 * 60)
        report = self.coach.report("today")
        self.assertEqual(report, "Today: 1 h on screen. Focused 40 min (VS Code 40 min). Distracted 15 min "
                                 "(YouTube 15 min). Messages and email 5 min (WhatsApp 5 min).")
        self.assertEqual(self.coach.report("how long on youtube today"), "Today: 15 min on YouTube.")
        self.assertIn("Today", self.coach.report("this week").replace("This week", "Today"))
        self.assertEqual(self.coach.report("yesterday"), "Yesterday: nothing recorded yet.")
        self.assertIn("Stopped tracking", self.coach.set_tracking(False))
        self.assertEqual(self.coach.forget_data(), "Deleted all saved screen-time and focus-session data.")
        self.assertIn("not tracking", self.coach.report("today"))

    def test_eye_breaks_every_twenty_minutes_of_screen_time(self):
        self.assertIn("every 20 minutes", self.coach.set_eye_breaks("on"))
        self.run_for(19 * 60)
        self.assertEqual(self.said, [])
        self.run_for(60)
        self.assertEqual(self.said, ["Eye break: look at something about 20 feet (6 metres) away for 20 seconds."])
        self.probe.show("code.exe", idle=200)                # away from the screen: the streak resets
        self.run_for(10)
        self.probe.show("code.exe", idle=0)
        self.run_for(19 * 60)
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.coach.set_eye_breaks("off"), "Eye-break reminders are off.")
        self.assertEqual(self.saved["eye_break_minutes"], 0)

    def test_offers_meeting_notes_once_per_call(self):
        self.probe.show("Zoom.exe", "Zoom Meeting")
        self.run_for(25)
        self.assertEqual(self.said, [])
        self.run_for(10)
        self.assertEqual(len(self.said), 1)
        self.assertIn("take meeting notes", self.said[0])
        self.run_for(600)
        self.assertEqual(len(self.said), 1)

    def test_no_meeting_offer_while_notes_are_running(self):
        self.meeting = True
        self.probe.show("Zoom.exe", "Zoom Meeting")
        self.run_for(120)
        self.assertEqual(self.said, [])

    def test_productivity_score_calculation(self):
        # Empty rows
        self.assertEqual(calculate_productivity_metrics([])["score"], 100)

        # 40m focus, 10m distraction -> 40 / 50 = 80%
        rows = [("VS Code", FOCUS, 2400.0), ("YouTube", DISTRACTION, 600.0)]
        metrics = calculate_productivity_metrics(rows)
        self.assertEqual(metrics["score"], 80)
        self.assertEqual(metrics["ratio"], 0.8)
        self.assertEqual(metrics["total_seconds"], 3000.0)

        # 100% distraction
        d_metrics = calculate_productivity_metrics([("YouTube", DISTRACTION, 1000.0)])
        self.assertEqual(d_metrics["score"], 0)

        # Via coach
        self.coach.set_tracking(True)
        self.run_for(30 * 60)
        res = self.coach.productivity_score("today")
        self.assertGreaterEqual(res["score"], 90)

    def test_sample_dataclass(self):
        s = Sample(at=1.0, label="VS Code", category=FOCUS, seconds=5.0)
        self.assertEqual(s.hwnd, 0)


class TestCoachBackground(unittest.TestCase):
    def test_tracker_only_runs_while_needed(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            coach = FocusCoach({"focus": {}}, lambda text: None, store=ActivityStore(Path(tmp.name) / "a.db"),
                               probe=Probe(), interval=0.01)
            coach.start()
            self.assertFalse(coach.tracker.running)          # nothing asked for: nothing runs
            coach.start_session("1 minute")
            self.assertTrue(coach.tracker.running)
            coach.stop_session()
            self.assertFalse(coach.tracker.running)
            coach.shutdown()
        finally:
            tmp.cleanup()





if __name__ == "__main__":
    unittest.main()
