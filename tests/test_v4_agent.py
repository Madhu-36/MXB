"""v4 smarter agent: tool calling, plan validation, set-of-marks, verification, stuck detection, undo."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from PIL import Image
from engine.actions_catalog import validate_plan, plan_tool_schema, action_names
from engine.agent_loop import AgentLoop, expectation_met, is_failure
from engine.llm_client import LLMClient, parse_tool_arguments, parse_json_reply
from engine.streaming import ReplyStreamer
from engine.ui_automation import UIElement, build_marks, annotate_marks, marks_prompt_lines, screen_signature
from engine.undo import UndoJournal
from engine.file_ops import FileOperationsManager


def el(name, ctype="Button", rect=(0, 0, 50, 20)):
    return UIElement(name=name, control_type=ctype, rect=rect)


class TestPlanValidation(unittest.TestCase):
    def test_aliases_unknown_and_cap(self):
        steps, dropped = validate_plan([{"action": "Click", "target": "1,2"}, {"action": "teleport", "target": "x"},
                                        {"action": "conversation"}, {"action": "type", "target": 5, "expect": "Saved"}])
        self.assertEqual(steps, [{"action": "left_click", "target": "1,2"},
                                 {"action": "type_text", "target": "5", "expect": "Saved"}])
        self.assertEqual(dropped, ["teleport"])
        many, _ = validate_plan([{"action": "wait", "target": "1"}] * 30, max_steps=5)
        self.assertEqual(len(many), 5)

    def test_tool_schema_enumerates_actions(self):
        schema = plan_tool_schema(agent=True)
        enum = schema["function"]["parameters"]["properties"]["plan"]["items"]["properties"]["action"]["enum"]
        self.assertIn("click_mark", enum)
        self.assertEqual(set(enum), set(action_names()))
        self.assertIn("done", schema["function"]["parameters"]["required"])


class TestLLMClientParsing(unittest.TestCase):
    def test_tool_arguments(self):
        self.assertEqual(parse_tool_arguments('{"reply": "ok", "plan": []}'), {"reply": "ok", "plan": []})
        self.assertEqual(parse_tool_arguments({"reply": "x"}), {"reply": "x"})

    def test_sse_and_ndjson(self):
        got = []
        sse = ['data: {"choices":[{"delta":{"content":"Hel"}}]}', "", 'data: {"choices":[{"delta":{"content":"lo"}}]}', "data: [DONE]"]
        self.assertEqual(LLMClient._consume_sse(sse, got.append), "Hello")
        self.assertEqual(got, ["Hel", "lo"])
        nd = [json.dumps({"message": {"content": "A"}}), json.dumps({"message": {"content": "B"}, "done": True})]
        self.assertEqual(LLMClient._consume_ndjson(nd, None), "AB")

    def test_tool_call_request_and_fallback_flag(self):
        client = LLMClient({})
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"choices": [{"message": {"tool_calls": [{"function": {
            "name": "execute_plan", "arguments": '{"reply": "Opening", "plan": [{"action": "open_app", "target": "chrome"}]}'}}]}}]}
        with patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value="k"), \
                patch("engine.llm_client.requests.post", return_value=ok) as post:
            out = client.plan_with_tools("sys", "open chrome", plan_tool_schema())
        self.assertEqual(out["plan"][0]["action"], "open_app")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["tool_choice"]["function"]["name"], "execute_plan")

        bad = MagicMock(status_code=400, text="tools not supported")
        with patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value="k"), \
                patch("engine.llm_client.requests.post", return_value=bad):
            self.assertIsNone(client.plan_with_tools("sys", "x", plan_tool_schema()))
        self.assertTrue(client._tools_unsupported["nvidia"])

    def test_truncated_reply_with_escapes(self):
        self.assertEqual(parse_json_reply('{"reply": "He said \\"hi\\" then'), {"reply": 'He said "hi" then', "plan": []})


class TestReplyStreamer(unittest.TestCase):
    def test_speaks_sentences_before_plan_finishes(self):
        spoken = []
        s = ReplyStreamer(spoken.append)
        raw = '{"reply": "Sure! Opening Chrome and searching for lofi music now. Give me a second.", "plan": [{"action": "open_app"'
        for i in range(0, len(raw), 4):
            s.feed(raw[i:i + 4])
            if "plan" in s.raw[-10:]:
                break
        self.assertEqual(spoken[0], "Sure! Opening Chrome and searching for lofi music now.")
        s.finish()
        self.assertEqual(spoken[-1], "Give me a second.")

    def test_plain_text_and_unicode(self):
        spoken = []
        s = ReplyStreamer(spoken.append)
        s.feed("Paris is the capital of France. ")
        s.feed("It is lovely.")
        s.finish()
        self.assertEqual(spoken, ["Paris is the capital of France.", "It is lovely."])
        spoken.clear()
        s = ReplyStreamer(spoken.append)
        s.feed('{"reply": "Caf\\u00e9 opened.", "plan": []}')
        s.finish()
        self.assertEqual(spoken, ["Café opened."])


class TestMarks(unittest.TestCase):
    def test_build_marks_orders_and_dedupes(self):
        elements = [el("Sign in", rect=(500, 10, 560, 30)), el("Search", "Edit", rect=(100, 10, 400, 30)),
                    el("Sign in", rect=(501, 11, 561, 31)), el("Footer", rect=(0, 900, 50, 920)),
                    el("decor", "Pane", rect=(0, 0, 10, 10))]
        marks = build_marks(elements)
        self.assertEqual([m.name for m in marks.values()], ["Search", "Sign in", "Footer"])
        self.assertEqual(marks_prompt_lines(marks)[0], '[1] Edit "Search" @ 250,20')

    def test_annotate_and_signature(self):
        marks = build_marks([el("OK", rect=(20, 30, 80, 60))])
        img = annotate_marks(Image.new("RGB", (200, 100), "white"), marks)
        self.assertEqual(img.size, (200, 100))
        self.assertNotEqual(img.getpixel((20, 45)), (255, 255, 255))  # box drawn
        self.assertEqual(screen_signature("A", marks), screen_signature("A", marks))
        self.assertNotEqual(screen_signature("A", marks), screen_signature("B", marks))


class FakePlanner:
    def __init__(self, results=None):
        self.abort_event = threading.Event()
        self.executed = []
        self.results = results

    @property
    def is_aborted(self):
        return self.abort_event.is_set()

    def reset(self):
        self.abort_event.clear()

    def execute_plan(self, steps, feedback_callback=None, reset=True):
        self.executed.extend(steps)
        if self.results:
            return [self.results.pop(0) for _ in steps]
        return [f"did {s['action']}" for s in steps]


class TestAgentV2(unittest.TestCase):
    def make(self, tool_responses, results=None, titles=None):
        ex = MagicMock()
        ex.planner = FakePlanner(results)
        ex.uia.available.return_value = True
        ex.uia.foreground_title.side_effect = titles or (lambda: "Login - App")
        ex.uia.collect.return_value = ([UIElement("Username", "Edit", rect=(10, 10, 210, 30)),
                                        UIElement("Sign in", "Button", rect=(10, 50, 90, 70))], 0)
        ex.screen.read_active_window_text.return_value = "Welcome back Srinivas"
        llm = MagicMock()
        llm.plan_with_tools.side_effect = tool_responses
        return AgentLoop(ex, llm, {"agent": {"max_steps": 5, "max_stuck_turns": 2}}), ex, llm

    def test_uses_tool_calling_and_marks(self):
        loop, ex, llm = self.make([{"plan": [{"action": "type_mark", "target": "1 :: srinivas"},
                                             {"action": "click_mark", "target": "2", "expect": "Welcome"}], "done": False},
                                   {"done": True, "reply": "Logged in."}], titles=["Login", "Home"])
        self.assertEqual(loop.run("log in"), "Logged in.")
        llm.chat_json.assert_not_called()
        ex.set_marks.assert_called()
        second_prompt = llm.plan_with_tools.call_args_list[1].args[1]
        self.assertIn("[verified]", second_prompt)

    def test_failed_expectation_reported(self):
        loop, ex, llm = self.make([{"plan": [{"action": "click_mark", "target": "2", "expect": "Dashboard"}]},
                                   {"done": True, "reply": "x"}], titles=["Login", "Login 2"])
        loop.run("go")
        self.assertIn("EXPECTED 'Dashboard' NOT FOUND", llm.plan_with_tools.call_args_list[1].args[1])

    def test_stuck_detection(self):
        loop, ex, _ = self.make([{"plan": [{"action": "click_mark", "target": "2"}]}] * 5)
        self.assertIn("stuck", loop.run("go"))

    def test_repeated_failure_gets_banned(self):
        loop, ex, llm = self.make([{"plan": [{"action": "click_element", "target": "Nope"}]}] * 4 + [{"done": True, "reply": "gave up"}],
                                  results=["Could not find 'Nope'"] * 4, titles=["A", "B", "C", "D", "E", "F"])
        loop.max_stuck_turns = 99
        loop.run("go")
        prompts = [c.args[1] for c in llm.plan_with_tools.call_args_list]
        self.assertTrue(any("BANNED" in p and "click_element Nope" in p for p in prompts))
        self.assertLessEqual(sum(1 for s in ex.planner.executed if s["target"] == "Nope"), 2)

    def test_falls_back_to_json_mode(self):
        loop, ex, llm = self.make([None])
        llm.chat_json.return_value = {"done": True, "reply": "done via json"}
        self.assertEqual(loop.run("go"), "done via json")

    def test_helpers(self):
        self.assertTrue(is_failure("Could not find 'x' on screen"))
        self.assertFalse(is_failure("Clicked 2: button 'Sign in'"))
        self.assertTrue(expectation_met("welcome", "Home — Welcome back"))
        self.assertFalse(expectation_met("invoice", "Home — Welcome back"))


class TestUndo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.journal = UndoJournal(self.base / "j.json", backup_dir=self.base / "backups")
        self.ops = FileOperationsManager(journal=self.journal)

    def tearDown(self):
        self.tmp.cleanup()

    def test_move_rename_undo(self):
        a = self.base / "report.txt"
        a.write_text("x")
        (self.base / "archive").mkdir()
        self.ops.move_path(str(a), str(self.base / "archive"))
        self.assertFalse(a.exists())
        self.assertIn("back", self.journal.undo_last())
        self.assertTrue(a.exists())
        self.ops.rename_path(str(a), "final")
        self.assertTrue((self.base / "final.txt").exists())
        self.journal.undo_last()
        self.assertTrue(a.exists())

    def test_overwrite_restores_previous_version(self):
        f = self.base / "notes.txt"
        f.write_text("original")
        self.ops.create_file(str(f), "replaced")
        self.assertEqual(f.read_text(), "replaced")
        self.journal.undo_last()
        self.assertEqual(f.read_text(), "original")

    def test_copy_and_create_undo_use_recycle(self):
        src = self.base / "a.txt"
        src.write_text("x")
        self.ops.copy_path(str(src), str(self.base / "b.txt"))
        recycled = []
        self.journal.undo_last(recycle_fn=lambda p: (recycled.append(p), p.unlink())[0] or True)
        self.assertEqual([p.name for p in recycled], ["b.txt"])

    def test_permanent_delete_not_undoable_and_persistence(self):
        f = self.base / "gone.txt"
        f.write_text("x")
        self.ops.delete_file(str(f), permanent=True)
        reloaded = UndoJournal(self.base / "j.json", backup_dir=self.base / "backups")
        self.assertIn("can't be undone", reloaded.undo_last())
        self.assertIn("nothing", reloaded.undo_last())

    def test_recycle_restore_hook(self):
        self.journal.record("recycle", path=str(self.base / "x.txt"))
        restored = []
        msg = self.journal.undo_last(restore_fn=lambda p: restored.append(p) or True)
        self.assertIn("restored", msg)
        self.assertEqual(len(restored), 1)


class TestExecutorV4(unittest.TestCase):
    def setUp(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        from engine.executor import OSExecutionManager
        self.ex = OSExecutionManager(config={})
        self.ex._uia = MagicMock()
        self.ex._uia.available.return_value = True
        self.ex._uia.collect.return_value = ([UIElement("Search", "Edit", rect=(100, 10, 300, 30)),
                                              UIElement("Go", "Button", rect=(310, 10, 350, 30))], 0)
        self.shown = []
        self.ex.ui_hooks["show_marks"] = self.shown.append
        self.ex.ui_hooks["hide_marks"] = lambda: self.shown.append("hidden")

    def test_show_and_click_marks(self):
        self.assertIn("Numbered 2", self.ex.execute_action("show_marks"))
        self.assertEqual([n for n, _r, _l in self.shown[0]], [1, 2])
        self.assertIn("Clicked 2", self.ex.execute_action("click_mark", "2"))
        self.ex.mouse.left_click.assert_called_with(330, 20)
        self.assertEqual(self.shown[-1], "hidden")
        self.assertIn("no item number 9", self.ex.execute_action("click_mark", "9"))

    def test_type_mark(self):
        self.ex.execute_action("show_marks")
        res = self.ex.execute_action("type_mark", "1 :: hello")
        self.ex.keyboard.type_text.assert_called_with("hello")
        self.assertIn("Typed 'hello'", res)

    def test_recorded_click_falls_back_to_coordinates(self):
        self.ex._uia.find_clickable.return_value = None
        self.ex.screen.find_text_coordinates.return_value = None
        res = self.ex.execute_action("click_element", "Submit || 640,480")
        self.ex.mouse.left_click.assert_called_with(640, 480)
        self.assertIn("recorded spot", res)


if __name__ == "__main__":
    unittest.main()
