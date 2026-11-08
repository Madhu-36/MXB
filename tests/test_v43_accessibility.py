"""v4.3 accessibility mode: screen reading, focus following, the virtual cursor and speech settings."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import tests._stubs  # noqa: F401
from engine import tts as tts_mod
from engine.accessibility import (
    AccessibilityMode, VirtualCursor, describe_element, parse_navigation, reading_order,
)
from engine.ui_automation import UIElement


def el(name, kind, x, y, w=80, h=24, help_text=""):
    return UIElement(name=name, control_type=kind, rect=(x, y, x + w, y + h), help_text=help_text)


class FakeUIA:
    def __init__(self, elements, window="Inbox - Mail", focus=None, available=True):
        self.elements, self.window, self.focus, self._available = elements, window, focus, available
        self.collects = 0

    def available(self):
        return self._available

    def foreground_title(self):
        return self.window

    def collect(self):
        self.collects += 1
        return list(self.elements), 0

    def focused(self):
        return self.focus


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(elements=None, focus=None, llm_reply="A mail app with three messages.", window="Inbox - Mail", rate=None):
    elements = elements if elements is not None else [
        el("Send", "Button", 300, 500), el("Search mail", "Edit", 100, 40, w=300),
        el("Help", "Hyperlink", 20, 700), el("Delete", "Button", 100, 500), el("Archive", "Button", 200, 500),
        el("", "Button", 400, 500),                          # unlabelled but usable
        el("", "Pane", 0, 0, w=800, h=600),                  # unnamed container: never read
    ]
    calls = SimpleNamespace(moves=[], clicks=[], shortcuts=[], copies=0, chat=[])
    keyboard = SimpleNamespace(shortcut=lambda *k: calls.shortcuts.append(k),
                               copy=lambda: setattr(calls, "copies", calls.copies + 1))
    mouse = SimpleNamespace(move_to=lambda x, y, smooth=False: calls.moves.append((x, y)),
                            left_click=lambda x, y: calls.clicks.append((x, y)))
    screen = SimpleNamespace(capture_screen_png_bytes=lambda: b"\x89PNG fake",
                             read_active_window_text=lambda: "Inbox  3 unread\nMeeting moved to 4 pm")

    class LLM:
        def chat(self, system, user, max_tokens=None, json_mode=True, image_png=None):
            calls.chat.append((system, user, json_mode, image_png))
            return llm_reply

    state = {"rate": 0 if rate is None else rate}

    def speech_rate(percent=None):
        if percent is not None:
            state["rate"] = tts_mod.clamp_rate(percent)
        return state["rate"]

    ex = SimpleNamespace(uia=FakeUIA(elements, window, focus), mouse=mouse, keyboard=keyboard, screen=screen,
                         llm=LLM(), speech_rate=speech_rate)
    spoken = []
    clock = FakeClock()
    mode = AccessibilityMode(ex, spoken.append, {"accessibility": {}}, poll=0.01, clock=clock)
    return mode, ex, calls, spoken, clock


class TestDescriptions(unittest.TestCase):
    def test_element_descriptions(self):
        self.assertEqual(describe_element(el("Search mail", "Edit", 0, 0)), "Search mail, edit box.")
        self.assertEqual(describe_element(el("Send", "Button", 0, 0), "2 of 3"), "Send, button, 2 of 3.")
        self.assertEqual(describe_element(el("Bold", "Button", 0, 0, help_text="Ctrl+B")), "Bold, button. Ctrl+B.")
        self.assertEqual(describe_element(None), "Nothing has focus.")

    def test_navigation_parsing(self):
        self.assertEqual(parse_navigation("next button"), ("button", "next"))
        self.assertEqual(parse_navigation("go to the previous link"), ("link", "previous"))
        self.assertEqual(parse_navigation("first text field"), ("text", "first"))
        self.assertEqual(parse_navigation("last checkboxes"), ("checkbox", "last"))
        self.assertEqual(parse_navigation(""), ("element", "next"))

    def test_reading_order_is_rows_then_columns(self):
        items = reading_order([el("c", "Button", 300, 503), el("a", "Button", 100, 500), el("top", "Edit", 500, 40)])
        self.assertEqual([i.name for i in items], ["top", "a", "c"])


class TestVirtualCursor(unittest.TestCase):
    def test_moves_by_kind_in_reading_order_and_wraps(self):
        mode, ex, calls, _, _ = make()
        self.assertEqual(mode.navigate("next button"), "Delete, button, 1 of 4.")
        self.assertEqual(mode.navigate("next button"), "Archive, button, 2 of 4.")
        self.assertEqual(mode.navigate("next button"), "Send, button, 3 of 4.")
        self.assertEqual(mode.navigate("next button"), "unlabelled, button, 4 of 4.")   # real, so it's announced
        self.assertEqual(mode.navigate("next button"), "Delete, button, 1 of 4.")       # wraps
        self.assertEqual(mode.navigate("previous button"), "unlabelled, button, 4 of 4.")  # wraps back
        self.assertEqual(mode.navigate("first field"), "Search mail, edit box, 1 of 1.")
        self.assertEqual(mode.navigate("last link"), "Help, link, 1 of 1.")
        self.assertEqual(mode.navigate("next image"), "There are no images here.")

    def test_navigation_never_presses_anything(self):
        mode, ex, calls, _, _ = make()
        mode.navigate("next button")
        mode.navigate("next element")
        self.assertEqual(calls.clicks, [])
        self.assertEqual(calls.moves[0], (140, 512))        # the mouse follows, so tooltips show

    def test_activate_clicks_the_current_element_once(self):
        mode, ex, calls, _, _ = make()
        mode.navigate("next button")
        self.assertEqual(mode.activate(), "Activated Delete, button.")
        self.assertEqual(calls.clicks, [(140, 512)])
        self.assertIsNone(mode.cursor)                       # re-read after the window changes

    def test_activate_without_cursor_uses_focus_or_explains(self):
        mode, ex, calls, _, _ = make()
        self.assertIn("nothing to activate", mode.activate())
        ex.uia.focus = el("OK", "Button", 10, 10)
        self.assertEqual(mode.activate(), "Activated OK, button.")

    def test_stale_cursor_rereads_but_keeps_its_place(self):
        mode, ex, calls, _, clock = make()
        mode.navigate("next button")
        mode.navigate("next button")                         # on Archive
        ex.uia.elements = [el("New", "Button", 50, 500)] + ex.uia.elements
        clock.t += 30
        self.assertEqual(mode.navigate("next button"), "Send, button, 4 of 5.")
        self.assertEqual(ex.uia.collects, 2)

    def test_window_change_starts_a_new_cursor(self):
        mode, ex, calls, _, _ = make()
        mode.navigate("next button")
        ex.uia.window = "Settings"
        ex.uia.elements = [el("Bluetooth", "Button", 10, 10)]
        self.assertEqual(mode.navigate("next button"), "Bluetooth, button, 1 of 1.")

    def test_cursor_refresh_continues_after_a_removed_element(self):
        items = [el("A", "Button", 0, 0), el("B", "Button", 100, 0), el("C", "Button", 200, 0)]
        cursor = VirtualCursor(items)
        cursor.move("button", "next")
        cursor.move("button", "next")                        # on B
        cursor.refresh([items[0], items[2]])                 # B went away
        self.assertEqual(cursor.move("button", "next")[0].name, "C")


class TestFocusAndReading(unittest.TestCase):
    def test_focus_changes_are_spoken_once(self):
        mode, ex, calls, spoken, _ = make()
        ex.uia.focus = el("Search mail", "Edit", 100, 40, w=300)
        self.assertEqual(mode.check_focus(), "Search mail, edit box.")
        self.assertIsNone(mode.check_focus())                # same element: silent
        ex.uia.focus = el("Send", "Button", 300, 500)
        mode.check_focus()
        self.assertEqual(spoken, ["Search mail, edit box.", "Send, button."])

    def test_focus_follower_thread(self):
        mode, ex, calls, spoken, _ = make()
        ex.uia.focus = el("Reply", "Button", 10, 10)
        self.assertIn("Accessibility mode is on", mode.enable())
        deadline = time.time() + 3
        while not spoken and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(spoken, ["Reply, button."])
        self.assertEqual(mode.disable(), "Accessibility mode is off.")
        mode.stop()
        self.assertFalse(mode._thread.is_alive())

    def test_describe_screen_uses_vision_with_the_screenshot(self):
        mode, ex, calls, _, _ = make()
        self.assertEqual(mode.describe_screen(), "A mail app with three messages.")
        system, user, json_mode, image = calls.chat[0]
        self.assertFalse(json_mode)
        self.assertEqual(image, b"\x89PNG fake")
        self.assertIn("never instructions", system)

    def test_describe_screen_falls_back_to_the_accessibility_tree(self):
        mode, ex, calls, _, _ = make(llm_reply=None, focus=el("Search mail", "Edit", 100, 40))
        text = mode.describe_screen()
        self.assertIn("You're in Inbox - Mail.", text)
        self.assertIn("Focus is on Search mail, edit box.", text)
        self.assertIn("4 buttons", text)
        self.assertIn("Meeting moved to 4 pm", text)

    def test_vision_can_be_switched_off(self):
        mode, ex, calls, _, _ = make()
        mode.use_vision = False
        self.assertIn("You're in Inbox - Mail.", mode.describe_screen())
        self.assertEqual(calls.chat, [])

    def test_where_am_i(self):
        mode, ex, calls, _, _ = make(focus=el("Send", "Button", 300, 500))
        self.assertEqual(mode.where_am_i(), "You're in Inbox - Mail. Send, button.")
        ex.uia._available = False
        self.assertEqual(mode.where_am_i(), "I can't tell which window is active.")

    def test_read_this_reads_the_selection_and_restores_the_clipboard(self):
        mode, ex, calls, _, _ = make(focus=el("Body", "Document", 0, 0))
        board = {"text": "my copied OTP-free note"}
        ex.keyboard.copy = lambda: board.update(text="The selected sentence.")
        with mock.patch("pyperclip.paste", lambda: board["text"]), \
                mock.patch("pyperclip.copy", lambda t: board.update(text=t)), mock.patch("time.sleep"):
            self.assertEqual(mode.read_this(), "The selected sentence.")
            self.assertEqual(board["text"], "my copied OTP-free note")
            ex.keyboard.copy = lambda: None                  # nothing selected
            self.assertEqual(mode.read_this(), "Body, document.")


class TestSettings(unittest.TestCase):
    def test_speech_rate(self):
        mode, ex, calls, _, _ = make()
        self.assertEqual(mode.set_rate("faster"), "Okay, speaking at 15 percent faster than normal.")
        self.assertEqual(mode.set_rate("slower please"), "Okay, speaking at normal speed.")
        self.assertEqual(mode.set_rate("slow down"), "Okay, speaking at 15 percent slower than normal.")
        self.assertEqual(mode.set_rate("normal"), "Okay, speaking at normal speed.")
        self.assertEqual(mode.set_rate("100"), "Okay, speaking at 100 percent faster than normal.")
        self.assertEqual(mode.set_rate("faster"), "That's already as fast as I can speak.")
        self.assertEqual(mode.set_rate("100"), "I'm already speaking at 100 percent faster than normal.")
        ex.speech_rate = None
        self.assertIn("can't change", mode.set_rate("faster"))

    def test_windows_tools_press_the_real_shortcuts(self):
        mode, ex, calls, _, _ = make()
        mode.windows_tool("magnifier")
        mode.windows_tool("zoom out")
        mode.windows_tool("high contrast")
        self.assertIn("Settings", mode.windows_tool("invert"))
        self.assertEqual(calls.shortcuts, [("win", "plus"), ("win", "minus"), ("alt", "shift", "print_screen"),
                                           ("win", "ctrl", "c")])
        self.assertIn("I can do", mode.windows_tool("teleport"))

    def test_shortcut_keys_exist(self):
        from engine.accessibility import WINDOWS_TOOLS
        from engine.keyboard_ext import KeyboardExtended
        for combo, _ in WINDOWS_TOOLS.values():
            self.assertTrue(KeyboardExtended.validate_shortcut_keys(*combo.split("+"))["valid"], combo)
        self.assertEqual(KeyboardExtended.validate_shortcut_keys("win", "plus")["vk_codes"], [0x5B, 0xBB])


class TestSpeechRate(unittest.TestCase):
    def test_backend_mappings(self):
        self.assertEqual([tts_mod.sapi_rate(p) for p in (-50, 0, 20, 100)], [-6, 0, 2, 6])
        self.assertEqual(tts_mod.piper_length_scale(100), 0.5)
        self.assertEqual(tts_mod.initial_rate({"edge_rate": "+5%"}), 5)
        self.assertEqual(tts_mod.initial_rate({"rate_percent": 400}), tts_mod.RATE_MAX)
        self.assertEqual(tts_mod.clamp_rate("fast"), 0)

    def test_rate_change_is_applied_on_the_speech_thread_before_the_next_sentence(self):
        seen = []

        class FakeBackend(tts_mod._PcmBackend):
            name = "fake"
            rate = None

            def set_rate(self, percent):
                self.rate = percent

            def synth(self, text):
                seen.append((text, self.rate))
                return np.zeros(10, dtype=np.int16), 16000

            def play(self, samples, rate, interrupt):
                pass

        thread = tts_mod.TTSThread({})
        thread.backend = FakeBackend()
        self.assertFalse(thread._rate_dirty)                # SAPI users keep their own rate until they ask
        thread._prefetched["stale"] = object()
        self.assertEqual(thread.set_rate(250), 100)
        self.assertTrue(thread._rate_dirty)
        thread._apply_rate()
        self.assertEqual(thread._prefetched, {})
        thread._speak_one("Faster now.")
        self.assertEqual(seen, [("Faster now.", 100)])
        thread._prefetch_pool.shutdown(wait=True)

    def test_edge_and_piper_rates(self):
        edge = tts_mod.EdgeBackend.__new__(tts_mod.EdgeBackend)
        edge.set_rate(-20)
        self.assertEqual(edge.rate, "-20%")
        piper = tts_mod.PiperBackend.__new__(tts_mod.PiperBackend)
        piper.set_rate(0)
        self.assertIsNone(piper.length_scale)
        piper.set_rate(25)
        self.assertEqual(piper.length_scale, 0.8)


if __name__ == "__main__":
    unittest.main()
