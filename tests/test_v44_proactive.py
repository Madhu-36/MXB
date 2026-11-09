"""v4.4 item 5: MXB speaks first — morning briefing, meeting and battery alerts, calendar and email."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from engine import proactive
from engine.proactive import (CalendarSource, MailSource, ProactiveEngine, _local, build_sources, imap_host_for,
                              needs_oauth)

TODAY = datetime(2026, 11, 9, 9, 0)        # a Monday

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//MXB test//EN
BEGIN:VEVENT
UID:standup
DTSTART:20261102T100000
DTEND:20261102T101500
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
SUMMARY:Team standup
LOCATION:Google Meet
END:VEVENT
BEGIN:VEVENT
UID:mock
DTSTART:20261109T153000
DTEND:20261109T163000
SUMMARY:DSA mock interview
END:VEVENT
BEGIN:VEVENT
UID:holiday
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
SUMMARY:Kannada Rajyotsava week
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTART:20261109T120000
DTEND:20261109T130000
STATUS:CANCELLED
SUMMARY:Cancelled lunch
END:VEVENT
BEGIN:VEVENT
UID:tomorrow
DTSTART:20261110T110000
DTEND:20261110T120000
SUMMARY:Project review
END:VEVENT
END:VCALENDAR
"""


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


HAS_ICAL = bool(importlib.util.find_spec("icalendar") and importlib.util.find_spec("recurring_ical_events"))


@unittest.skipUnless(HAS_ICAL, "needs icalendar + recurring-ical-events")
class TestCalendar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ics = Path(self.tmp.name) / "cal.ics"
        self.ics.write_text(ICS, encoding="utf-8")

    def test_today_with_recurrence_all_day_and_cancelled(self):
        cal = CalendarSource(str(self.ics))
        start = datetime(2026, 11, 9)
        events = cal.events(start, start + timedelta(days=1))
        titles = [e.title for e in events]
        self.assertEqual(titles[0], "Kannada Rajyotsava week")          # all-day first
        self.assertIn("Team standup", titles)                           # weekly recurrence
        self.assertIn("DSA mock interview", titles)
        self.assertNotIn("Cancelled lunch", titles)
        self.assertNotIn("Project review", titles)
        standup = next(e for e in events if e.title == "Team standup")
        self.assertEqual((standup.start.date(), standup.location), (start.date(), "Google Meet"))
        self.assertTrue(events[0].all_day)

    def test_times_become_local(self):
        from datetime import date, timezone
        aware = datetime(2026, 11, 9, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(_local(aware), (aware.astimezone().replace(tzinfo=None), False))
        self.assertEqual(_local(date(2026, 11, 9)), (datetime(2026, 11, 9), True))
        self.assertEqual(_local(datetime(2026, 11, 9, 10, 0)), (datetime(2026, 11, 9, 10, 0), False))

    def test_link_is_fetched_once_per_cache_window(self):
        resp = MagicMock(content=ICS.encode())
        get = MagicMock(return_value=resp)
        clock = FakeClock(0.0)
        cal = CalendarSource("webcal://calendar.example/secret.ics", http_get=get, cache_seconds=900, clock=clock)
        day = datetime(2026, 11, 9)
        cal.events(day, day + timedelta(days=1))
        cal.events(day, day + timedelta(days=1))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], "https://calendar.example/secret.ics")
        clock.now = 1000.0
        cal.events(day, day + timedelta(days=1))
        self.assertEqual(get.call_count, 2)


class FakeIMAP:
    def __init__(self, host, port):
        self.selected = None
        self.logged_out = False

    def login(self, user, password):
        assert password == "app-pass"

    def select(self, folder, readonly=False):
        self.selected = (folder, readonly)

    def search(self, charset, criterion):
        return "OK", [b"3 7 9"]

    def fetch(self, msg_id, parts):
        assert "PEEK" in parts                       # never marks mail as read
        headers = {b"9": b"From: Ravi Kumar <ravi@example.com>\r\nSubject: =?utf-8?q?Placement_drive_=E2=80=94_Friday?=\r\n\r\n",
                   b"7": b"From: hr@company.example\r\nSubject: Interview slot\r\n\r\n"}
        return "OK", [(b"header", headers.get(msg_id, b"From: a@b\r\nSubject: old\r\n\r\n"))]

    def logout(self):
        self.logged_out = True


class TestMail(unittest.TestCase):
    def test_unread_is_read_only_and_decoded(self):
        made = []

        def factory(host, port):
            made.append(FakeIMAP(host, port))
            return made[-1]
        mail = MailSource("imap.gmail.com", "me@gmail.com", lambda: "app-pass", imap_factory=factory)
        count, latest = mail.unread(limit=2)
        self.assertEqual(count, 3)
        self.assertEqual(latest, [("Ravi Kumar", "Placement drive — Friday"), ("hr@company.example", "Interview slot")])
        self.assertEqual(made[0].selected, ("INBOX", True))
        self.assertTrue(made[0].logged_out)


class FakeVault:
    def __init__(self):
        self.secrets = {}

    def set_secret(self, key, value):
        self.secrets[key] = value


class TestSetup(unittest.TestCase):
    """`scripts\\setup_proactive.bat`: nothing is saved until the account actually works."""

    def test_providers(self):
        self.assertEqual(imap_host_for("S10@Gmail.com"), "imap.gmail.com")
        self.assertEqual(imap_host_for("me@yahoo.co.in"), "imap.mail.yahoo.com")
        self.assertEqual(imap_host_for("me@college.edu.in"), "")
        self.assertTrue(needs_oauth("me@outlook.com"))
        self.assertTrue(needs_oauth("me@hotmail.com"))
        self.assertFalse(needs_oauth("me@gmail.com"))

    def _email(self, answers, password, unread):
        vault, config, saved = FakeVault(), {}, []
        with patch("builtins.input", side_effect=answers), patch("getpass.getpass", return_value=password), \
                patch.object(proactive.MailSource, "unread", unread), patch("builtins.print"):
            proactive._setup_email(vault, config, saved.append)
        return vault, config, saved

    def test_working_gmail_is_saved_with_the_password_in_the_vault(self):
        vault, config, saved = self._email(["me@gmail.com", ""], "abcd efgh ijkl mnop", lambda self, limit=3: (2, []))
        self.assertEqual(config["proactive"], {"imap_host": "imap.gmail.com", "imap_user": "me@gmail.com"})
        self.assertEqual(vault.secrets[proactive.IMAP_PASSWORD_KEY], "abcd efgh ijkl mnop")
        self.assertNotIn("abcd", str(config))
        self.assertEqual(len(saved), 1)

    def test_failed_sign_in_saves_nothing(self):
        def refuse(self, limit=3):
            raise proactive.imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        vault, config, saved = self._email(["me@gmail.com", ""], "wrong", refuse)
        self.assertEqual((vault.secrets, config, saved), ({}, {}, []))

    def test_outlook_is_refused_before_asking_for_a_password(self):
        asked = MagicMock()
        with patch("builtins.input", side_effect=["me@outlook.com"]), patch("getpass.getpass", asked), \
                patch("builtins.print"):
            proactive._setup_email(FakeVault(), {}, lambda c: None)
        asked.assert_not_called()

    def test_mail_server_has_a_timeout(self):
        with patch.object(proactive.imaplib, "IMAP4_SSL") as ssl:
            ssl.return_value = FakeIMAP("imap.gmail.com", 993)
            MailSource("imap.gmail.com", "me@gmail.com", lambda: "app-pass").unread()
        self.assertEqual(ssl.call_args.kwargs.get("timeout"), 15)

    @unittest.skipUnless(HAS_ICAL, "needs icalendar + recurring-ical-events")
    def test_calendar_link_is_checked_before_saving(self):
        vault = FakeVault()
        with patch("getpass.getpass", return_value="https://calendar.example/private-x/basic.ics"), \
                patch.object(proactive.CalendarSource, "_ics", side_effect=OSError("404")), patch("builtins.print"):
            proactive._setup_calendar(vault)
        self.assertEqual(vault.secrets, {})
        with tempfile.TemporaryDirectory() as tmp:
            ics = Path(tmp) / "cal.ics"
            ics.write_text(ICS, encoding="utf-8")
            with patch("getpass.getpass", return_value=str(ics)), patch("builtins.print"):
                proactive._setup_calendar(vault)
        self.assertEqual(vault.secrets[proactive.CALENDAR_KEY], str(ics))


@unittest.skipUnless(HAS_ICAL, "needs icalendar + recurring-ical-events")
class TestProactiveEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ics = Path(self.tmp.name) / "cal.ics"
        ics.write_text(ICS, encoding="utf-8")
        self.clock = FakeClock(TODAY)
        self.said = []
        self.battery = (80, True)
        self.saved = {}
        self.engine = ProactiveEngine(
            {"proactive": {"briefing_time": "08:30", "quiet_hours": "22:30-07:30"}},
            announce=lambda text, speak=True: self.said.append((text, speak)),
            calendar=CalendarSource(str(ics)), battery=lambda: self.battery, user_name="S10",
            reminders=lambda: [(TODAY.replace(hour=18), "call mom")], weather=lambda: "Bengaluru 24°C, cloudy",
            save_setting=lambda k, v: self.saved.__setitem__(k, v), clock=self.clock, idle_seconds=lambda: 5)

    def test_quiet_hours_wrap_midnight(self):
        e = self.engine
        self.assertTrue(e.quiet(datetime(2026, 11, 9, 23, 0)))
        self.assertTrue(e.quiet(datetime(2026, 11, 9, 6, 59)))
        self.assertFalse(e.quiet(datetime(2026, 11, 9, 7, 30)))
        self.assertFalse(e.quiet(datetime(2026, 11, 9, 22, 29)))

    def test_morning_briefing_once_a_day(self):
        said = self.engine.tick()
        kinds = [k for k, _ in said]
        self.assertIn("briefing", kinds)
        text = dict(said)["briefing"]
        for piece in ("Good morning, S10", "Bengaluru 24°C", "Team standup", "DSA mock interview",
                      "Kannada Rajyotsava week", "call mom"):
            self.assertIn(piece, text)
        self.assertNotIn("Cancelled", text)
        self.assertNotIn("briefing", [k for k, _ in self.engine.tick()])   # not twice
        self.clock.now = TODAY + timedelta(days=1)
        self.assertIn("briefing", [k for k, _ in self.engine.tick()])

    def test_no_unasked_briefing_without_a_calendar_or_email(self):
        self.engine.calendar = None
        self.assertNotIn("briefing", [k for k, _ in self.engine.tick()])
        asked = self.engine.briefing(TODAY)                       # "brief me" still works, with the hint
        self.assertIn("Bengaluru 24°C", asked)
        self.assertIn("connect my calendar", asked)

    def test_no_briefing_while_away_or_before_time(self):
        self.engine.idle_seconds = lambda: 3600
        self.assertNotIn("briefing", [k for k, _ in self.engine.tick()])
        self.engine.idle_seconds = lambda: 1
        self.clock.now = TODAY.replace(hour=8, minute=0)
        self.assertNotIn("briefing", [k for k, _ in self.engine.tick()])

    def test_meeting_alert_once(self):
        self.engine.muted.add("briefing")
        self.clock.now = TODAY.replace(hour=9, minute=52)
        said = self.engine.tick()
        self.assertEqual(said, [("meetings", "Team standup starts in 8 minutes, Google Meet.")])
        self.assertEqual(self.said[-1][1], True)
        self.assertEqual(self.engine.tick(), [])
        self.clock.now = TODAY.replace(hour=10, minute=30)
        self.assertEqual(self.engine.tick(), [])

    def test_quiet_hours_show_meetings_without_speaking_and_hold_the_rest(self):
        self.engine.quiet_from, self.engine.quiet_to = (9, 0), (11, 0)
        self.clock.now = TODAY.replace(hour=9, minute=55)
        self.battery = (5, False)
        said = self.engine.tick()
        self.assertEqual([k for k, _ in said], ["meetings"])
        self.assertFalse(self.said[-1][1])

    def test_battery_warns_once_until_charged(self):
        self.engine.muted.add("briefing")
        self.battery = (12, False)
        self.assertEqual(self.engine.tick(), [("battery", "Battery is at 12%. Plug in soon.")])
        self.assertEqual(self.engine.tick(), [])
        self.battery = (12, True)
        self.engine.tick()
        self.battery = (11, False)
        self.assertEqual([k for k, _ in self.engine.tick()], ["battery"])

    def test_busy_means_quiet(self):
        self.engine.busy = lambda: True
        self.battery = (5, False)
        self.assertEqual(self.engine.tick(), [])

    def test_mute_and_unmute(self):
        self.assertIn("no more battery", self.engine.mute("battery"))
        self.assertEqual(self.saved["muted"], ["battery"])
        self.battery = (5, False)
        self.assertNotIn("battery", [k for k, _ in self.engine.tick()])
        self.assertIn("won't speak first", self.engine.mute("all"))
        self.assertEqual(self.engine.tick(), [])
        self.assertIn("on", self.engine.unmute("all"))
        self.assertEqual(self.saved["muted"], [])
        self.assertIn("I can mute", self.engine.mute("weather"))

    def test_agenda_and_email_text(self):
        self.clock.now = TODAY.replace(hour=12)
        self.assertIn("Tomorrow: 1 event: 11:00 AM Project review.", self.engine.agenda(day_offset=1))
        today = self.engine.agenda()
        self.assertNotIn("Team standup", today)                      # already over
        self.assertIn("DSA mock interview", today)
        self.assertEqual(self.engine.email_summary(), "Email isn't connected.")
        mail = MagicMock()
        mail.unread.return_value = (2, [("Ravi", "Placement drive")])
        self.engine.mail = mail
        self.assertEqual(self.engine.email_summary(), "2 unread emails. Latest: Ravi: Placement drive.")
        self.assertIn("isn't connected", ProactiveEngine({}).agenda())


class TestWiring(unittest.TestCase):
    def test_sources_come_from_the_vault(self):
        vault = MagicMock()
        vault.get_secret.side_effect = {"proactive_calendar_ics": "https://cal.example/x.ics",
                                        "proactive_imap_password": "pw"}.get
        vault.has_secret.return_value = True
        cal, mail = build_sources({"proactive": {"imap_host": "imap.gmail.com", "imap_user": "me@gmail.com"}}, vault)
        self.assertEqual(cal.where, "https://cal.example/x.ics")
        self.assertEqual((mail.host, mail.user, mail.password_getter()), ("imap.gmail.com", "me@gmail.com", "pw"))
        empty = MagicMock(get_secret=MagicMock(return_value=None), has_secret=MagicMock(return_value=False))
        self.assertEqual(build_sources({}, empty), (None, None))

    def route(self, text):
        from bench.routing import RecordingExecutor, SilentTTS
        from engine.router import IntentRouter
        ex = RecordingExecutor()
        router = IntentRouter(executor=ex, tts=SilentTTS())
        with patch.object(router, "_route_to_llm", return_value="__LLM__"):
            router.route(text)
        return ex.calls

    def test_commands(self):
        self.assertEqual(self.route("brief me"), [("briefing", "")])
        self.assertEqual(self.route("what does my day look like"), [("briefing", "")])
        self.assertEqual(self.route("what's on my calendar tomorrow"), [("calendar", "tomorrow")])
        self.assertEqual(self.route("do i have any meetings today"), [("calendar", "today")])
        self.assertEqual(self.route("check my email"), [("email_check", "")])
        self.assertEqual(self.route("any new emails"), [("email_check", "")])
        self.assertEqual(self.route("stop the battery alerts"), [("proactive", "mute battery")])
        self.assertEqual(self.route("no more meeting reminders"), [("proactive", "mute meetings")])
        self.assertEqual(self.route("turn off proactive alerts"), [("proactive", "mute all")])
        self.assertEqual(self.route("turn on proactive alerts"), [("proactive", "unmute all")])
        self.assertEqual(self.route("connect my calendar"), [("proactive", "connect")])

    def test_executor_actions(self):
        from engine.executor import OSExecutionManager
        ex = OSExecutionManager.__new__(OSExecutionManager)
        ex._proactive = MagicMock()
        ex._proactive.briefing.return_value = "Good morning."
        ex._proactive.agenda.return_value = "Tomorrow: clear."
        self.assertEqual(ex.v44_action("briefing", ""), "Good morning.")
        self.assertEqual(ex.v44_action("calendar", "tomorrow"), "Tomorrow: clear.")
        ex._proactive.agenda.assert_called_with(day_offset=1)
        ex.v44_action("proactive", "mute battery")
        ex._proactive.mute.assert_called_with("battery")
        ex.v44_action("proactive", "unmute all")
        ex._proactive.unmute.assert_called_with("all")
        self.assertIn("setup_proactive.bat", ex.v44_action("proactive", "connect"))


if __name__ == "__main__":
    unittest.main()
