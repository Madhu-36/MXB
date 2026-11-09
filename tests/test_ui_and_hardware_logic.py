"""Pure logic of UI Automation scoring, hardware parsing and the agent loop."""
import threading
import unittest
from unittest.mock import MagicMock

import tests._stubs  # noqa: F401
from engine.ui_automation import UIAutomation, UIElement, pick_search_box, pick_element, summarize_elements, fallback_search_shortcut
from engine.hardware import (parse_on_off, parse_level, volume_key_presses, parse_netsh_interfaces,
                             parse_netsh_networks, summarize_pnp_devices, match_device_name,
                             BLUETOOTH_DEVICE_INFO, BLUETOOTH_DEVICE_SEARCH_PARAMS, _GUID)
from engine.agent_loop import AgentLoop, rescale_step
from engine.llm_client import parse_json_reply
import ctypes
import sys


def el(name, ctype="Edit", rect=(100, 80, 600, 110), **kw):
    return UIElement(name=name, control_type=ctype, rect=rect, **kw)


class TestSearchBoxScoring(unittest.TestCase):
    def test_prefers_named_search_box(self):
        elements = [el("Username"), el("Search YouTube"), el("Password"), el("Search", "Button")]
        self.assertEqual(pick_search_box(elements).name, "Search YouTube")

    def test_hint_beats_browser_address_bar(self):
        elements = [el("Address and search bar", rect=(0, 40, 1200, 70)), el("Search Amazon.in", rect=(200, 120, 900, 150))]
        self.assertEqual(pick_search_box(elements, "amazon").name, "Search Amazon.in")

    def test_placeholder_in_help_text(self):
        elements = [el("", help_text="Type to search"), el("Comment")]
        self.assertEqual(pick_search_box(elements).help_text, "Type to search")

    def test_never_picks_password(self):
        self.assertIsNone(pick_search_box([el("Enter password")]))
        self.assertEqual(pick_search_box([el("Password"), el("Search")]).name, "Search")

    def test_single_plain_input_accepted(self):
        self.assertEqual(pick_search_box([el("Message")]).name, "Message")

    def test_ambiguous_plain_inputs_rejected(self):
        self.assertIsNone(pick_search_box([el("First name"), el("Last name")]))

    def test_pick_element_fuzzy(self):
        elements = [el("Sign in", "Button"), el("Create account", "Hyperlink"), el("Settings", "MenuItem")]
        self.assertEqual(pick_element(elements, "sign in").name, "Sign in")
        self.assertEqual(pick_element(elements, "create an account").name, "Create account")
        self.assertIsNone(pick_element(elements, "delete everything"))

    def test_summary_has_coordinates(self):
        out = summarize_elements([el("OK", "Button", rect=(10, 10, 50, 30))])
        self.assertEqual(out[0], {"type": "Button", "name": "OK", "x": 30, "y": 20})

    def test_fallback_shortcuts(self):
        self.assertEqual(fallback_search_shortcut("Inbox - Google Chrome")[1], ["ctrl", "l"])
        self.assertEqual(fallback_search_shortcut("")[1], ["win", "s"])
        self.assertEqual(fallback_search_shortcut("Untitled - Notepad")[1], ["ctrl", "f"])


class TestHardwareParsing(unittest.TestCase):
    def test_on_off(self):
        self.assertEqual(parse_on_off("ON"), "on")
        self.assertEqual(parse_on_off("disable"), "off")
        self.assertEqual(parse_on_off(""), "status")

    def test_levels(self):
        self.assertEqual(parse_level("45%"), 45)
        self.assertEqual(parse_level("150"), 100)
        self.assertEqual(parse_level("up", 95), 100)
        self.assertEqual(parse_level("down", 30), 20)
        self.assertIsNone(parse_level("status"))
        self.assertEqual(volume_key_presses(40), (50, 20))

    def test_netsh(self):
        iface = "    State                  : connected\n    SSID                   : Home_5G\n    Signal                 : 88%\n"
        self.assertEqual(parse_netsh_interfaces(iface), {"state": "connected", "ssid": "Home_5G", "signal": "88%"})
        nets = parse_netsh_networks("SSID 1 : Home_5G\n    Authentication          : WPA2-Personal\n"
                                    "    BSSID 1                 : aa:bb\n         Signal             : 91%\n"
                                    "SSID 2 : \n         Signal             : 20%\n")
        self.assertEqual(nets[0], {"ssid": "Home_5G", "signal": "91%", "auth": "WPA2-Personal"})
        self.assertEqual(nets[1]["ssid"], "(hidden network)")

    def test_pnp_summary_filters_generic_and_category(self):
        recs = [{"Class": "Keyboard", "FriendlyName": "Logitech K380", "Status": "OK"},
                {"Class": "USB", "FriendlyName": "USB Root Hub (USB 3.0)", "Status": "OK"},
                {"Class": "Camera", "FriendlyName": "HP Wide Vision HD Camera", "Status": "OK"}]
        all_summary = summarize_pnp_devices(recs)
        self.assertIn("Logitech K380", all_summary)
        self.assertNotIn("Root Hub", all_summary)
        self.assertNotIn("Logitech", summarize_pnp_devices(recs, "camera"))

    def test_device_name_matching(self):
        names = ["boAt Airdopes 141", "OnePlus Buds Z2", "JBL Flip 5"]
        self.assertEqual(match_device_name("my airdopes", names), "boAt Airdopes 141")
        self.assertEqual(match_device_name("oneplus buds", names), "OnePlus Buds Z2")
        self.assertIsNone(match_device_name("sony tv", names))

    def test_win32_struct_sizes_match_sdk(self):
        # wintypes only has Windows sizes (DWORD/BOOL = 4 bytes, WCHAR = 2) on Windows itself.
        if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(BLUETOOTH_DEVICE_INFO), 560)
            self.assertEqual(ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS), 40)
        g = _GUID.from_string("0000110B-0000-1000-8000-00805F9B34FB")
        self.assertEqual((g.Data1, g.Data2, g.Data3, g.Data4[0], g.Data4[7]), (0x110B, 0, 0x1000, 0x80, 0xFB))


class FakePlanner:
    def __init__(self):
        self.abort_event = threading.Event()
        self.executed = []

    @property
    def is_aborted(self):
        return self.abort_event.is_set()

    def reset(self):
        self.abort_event.clear()

    def execute_plan(self, steps, feedback_callback=None, reset=True):
        self.executed.extend(steps)
        return [f"did {s['action']}" for s in steps]


class TestAgentLoop(unittest.TestCase):
    def make(self, responses, elements=None):
        executor = MagicMock()
        executor.planner = FakePlanner()
        executor.uia.available.return_value = True
        executor.uia.foreground_title.return_value = "Inbox - Gmail"
        executor.uia.collect.return_value = (elements if elements is not None else
                                             [UIElement("Ravi", "Hyperlink", rect=(250, 190, 350, 210))], 0)
        executor.screen.read_active_window_text.return_value = "Inbox Ravi Project update"
        llm = MagicMock()
        llm.plan_with_tools.return_value = None      # force the JSON-mode fallback path
        llm.chat_json.side_effect = responses
        return AgentLoop(executor, llm, {"agent": {"max_steps": 3}}), executor, llm

    def test_runs_until_done(self):
        loop, ex, llm = self.make([
            {"thought": "open mail", "done": False, "plan": [{"action": "click_mark", "target": "1"}]},
            {"done": True, "reply": "Opened Ravi's email."},
        ])
        self.assertEqual(loop.run("open Ravi's email"), "Opened Ravi's email.")
        self.assertEqual(ex.planner.executed, [{"action": "click_mark", "target": "1"}])
        prompt = llm.chat_json.call_args_list[0].args[1]
        self.assertIn('[1] Hyperlink "Ravi" @ 300,200', prompt)

    def test_no_recursion_and_step_cap(self):
        loop, ex, _ = self.make([{"plan": [{"action": "agent_task", "target": "x"}, {"action": "wait", "target": "1"}]}] * 3)
        loop.max_stuck_turns = 99
        loop.run("loop forever")
        self.assertTrue(all(s["action"] != "agent_task" for s in ex.planner.executed))
        self.assertEqual(len(ex.planner.executed), 3)

    def test_abort(self):
        loop, ex, _ = self.make([{"plan": [{"action": "wait", "target": "1"}]}] * 3)
        ex.planner.execute_plan = lambda *a, **k: (ex.planner.abort_event.set(), ["stopped"])[1]
        self.assertEqual(loop.run("anything"), "Agent task stopped.")

    def test_rescale(self):
        self.assertEqual(rescale_step({"action": "left_click", "target": "100,50"}, 2.0)["target"], "200,100")
        self.assertEqual(rescale_step({"action": "type_text", "target": "100,50"}, 2.0)["target"], "100,50")


class TestJsonRepair(unittest.TestCase):
    def test_done_flag_from_truncated(self):
        res = parse_json_reply('{"thought": "ok", "done": true, "reply": "All set')
        self.assertTrue(res["done"])
        self.assertEqual(res["reply"], "All set")


if __name__ == "__main__":
    unittest.main()


class TestUIAutomationCaching(unittest.TestCase):
    def test_cache_hits_and_invalidation(self):
        import time
        client = UIAutomation(cache_ttl=1.0)
        client._available = True
        sample_elements = [el("Search YouTube", rect=(10, 10, 200, 40))]

        with unittest.mock.patch.object(client, "foreground_hwnd", return_value=12345):
            # Seed the cache
            client._cache = (12345, time.time(), sample_elements, 10)

            # Consecutive queries hit cache
            elems, top = client.collect()
            self.assertEqual(elems, sample_elements)
            self.assertEqual(client.cache_hits, 1)

            elems2, top2 = client.collect()
            self.assertEqual(client.cache_hits, 2)

            # Invalidation resets cache
            client.invalidate_cache()
            self.assertIsNone(client._cache)
