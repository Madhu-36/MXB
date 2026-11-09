"""
v4.4 items 1-2: a benchmark for the brain, and a brain that passes it.
- bench/brain.py scores whole plans (order, nothing destructive added); it found four fast-path bugs
- planner stops before typing into the wrong window and waits for launched apps
- local models: output constrained to the plan schema, no hybrid "thinking", a one-click upgrade
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from bench.brain import run_brain, score_plan, step_matches
from bench.brain_cases import BRAIN_CASES, DESTRUCTIVE
from bench.routing import RecordingExecutor, SilentTTS
from engine.actions_catalog import action_names
from engine.llm_client import LLMClient
from engine.planner import ActionPlanner, step_failed
from engine.router import is_compound, names_an_app
from utils import model_setup


class TestPlanScoring(unittest.TestCase):
    def test_steps_must_appear_in_order(self):
        steps = [[("open_app", ["notepad"])], [("type_text", ["buy milk"])]]
        self.assertEqual(score_plan([("open_app", "Notepad"), ("wait", "1"), ("type_text", "Buy milk")], steps),
                         (True, "ok"))
        ok, reason = score_plan([("type_text", "buy milk"), ("open_app", "notepad")], steps)
        self.assertFalse(ok)
        self.assertIn("missing step 2", reason)

    def test_alternatives_and_keyword_choices(self):
        alts = [("set_brightness", ["up|100|9"])]
        self.assertTrue(step_matches(("set_brightness", "90"), alts))
        self.assertTrue(step_matches(("set_brightness", "up"), alts))
        self.assertFalse(step_matches(("set_brightness", "40"), alts))
        self.assertFalse(step_matches(("set_volume", "up"), alts))

    def test_unrequested_destructive_action_fails(self):
        ok, reason = score_plan([("close_app", "internet connection")], [[("wifi_power", ["off"])]])
        self.assertFalse(ok)
        self.assertIn("destructive", reason)
        self.assertTrue(score_plan([("close_app", "chrome")], [[("close_app", ["chrome"])]])[0])

    def test_talk_cases_must_not_act(self):
        self.assertTrue(score_plan([("conversation", "none")], [])[0])
        self.assertFalse(score_plan([("open_app", "jokes")], [])[0])

    def test_case_file_is_valid(self):
        names = set(action_names())
        self.assertGreaterEqual(len(BRAIN_CASES), 40)
        for phrase, steps, category in BRAIN_CASES:
            for alternatives in steps:
                for action, keywords in alternatives:
                    self.assertIn(action, names, phrase)
                    self.assertIsInstance(keywords, list)
        self.assertTrue(DESTRUCTIVE <= names)


class TestFastPathFixes(unittest.TestCase):
    """Bugs the brain benchmark found in the instant (no-LLM) path."""

    def route(self, text):
        from engine.router import IntentRouter
        executor = RecordingExecutor()
        router = IntentRouter(executor=executor, tts=SilentTTS())
        with patch.object(router, "_route_to_llm", return_value="__LLM__") as llm:
            router.route(text)
        return executor.calls, llm.called

    def test_second_command_is_not_swallowed_as_an_app_name(self):
        calls, used_llm = self.route("fire up spotify and then minimize it")
        self.assertTrue(used_llm)
        self.assertNotIn(("open_app", "spotify and then minimize it"), calls)
        calls, used_llm = self.route("open youtube and play arijit singh songs")
        self.assertTrue(used_llm)

    def test_kill_the_internet_does_not_close_an_app(self):
        calls, _ = self.route("kill the internet connection")
        self.assertFalse(any(a == "close_app" for a, _ in calls))
        self.assertEqual(self.route("close chrome")[0], [("close_app", "chrome")])

    def test_volume_number_wins(self):
        self.assertEqual(self.route("it's too loud, bring the volume down to 30")[0], [("set_volume", "30")])
        self.assertEqual(self.route("set the volume to 45 percent")[0], [("set_volume", "45")])
        self.assertEqual(self.route("make the volume 150 percent")[0], [("set_volume", "100")])
        self.assertEqual(self.route("volume down")[0], [("media_control", "volume_down")])

    def test_simple_commands_still_instant(self):
        self.assertEqual(self.route("open notepad")[0], [("open_app", "notepad")])

    def test_helpers(self):
        self.assertTrue(is_compound("open notepad and type hello"))
        self.assertTrue(is_compound("launch chrome then search for cats"))
        self.assertFalse(is_compound("open notepad"))
        self.assertFalse(is_compound("open the salt and pepper app"))
        self.assertFalse(names_an_app("the internet connection"))
        self.assertTrue(names_an_app("visual studio code"))


class TestBrainHarness(unittest.TestCase):
    def test_scores_model_plans_without_executing(self):
        from engine.router import IntentRouter
        router = IntentRouter(executor=RecordingExecutor(), tts=SilentTTS())
        router.llm = MagicMock()
        router.llm.cloud_available.return_value = False
        router.llm.local_model = "fake:4b"
        plans = {
            "write a quick note in notepad saying buy milk": [{"action": "open_app", "target": "notepad"},
                                                              {"action": "type_text", "target": "buy milk"}],
            "tell me a joke": [],
        }

        def plan_with_tools(system, prompt, tool):
            text = prompt.split("User Command: '")[-1].split("'")[0] if "User Command: '" in prompt else prompt
            for phrase, plan in plans.items():
                if phrase in text.lower():
                    return {"reply": "Sure.", "plan": plan}
            return {"reply": "Hmm.", "plan": [{"action": "open_app", "target": "wrong"}]}
        router.llm.plan_with_tools.side_effect = plan_with_tools
        cases = [c for c in BRAIN_CASES if c[0] in plans] + [c for c in BRAIN_CASES if c[0] == "lock my computer"]
        res = run_brain(cases=cases, router=router)
        by = {r["phrase"]: r for r in res["rows"]}
        self.assertTrue(by["write a quick note in notepad saying buy milk"]["passed"])
        self.assertTrue(by["tell me a joke"]["passed"])
        self.assertEqual(res["summary"]["model"], "fake:4b")
        self.assertEqual(res["summary"]["cases"], len(cases))


class FakeExecutor:
    def __init__(self, results):
        self.results = dict(results)
        self.calls = []
        self.input_lock = threading.Lock()

    def execute_action(self, action, target=""):
        self.calls.append((action, target))
        return self.results.get(action, f"Done: {action}")


class TestPlanSafety(unittest.TestCase):
    def test_failure_words(self):
        for text in ("Could not find an app matching 'zzz'", "Failed step 2 (open_app): boom",
                     "I don't have access to C:\\Windows", "No app called that is installed"):
            self.assertTrue(step_failed(text), text)
        for text in ("Launched notepad", "Typed 12 characters", "Done: no errors", ""):
            self.assertFalse(step_failed(text), text)

    def test_stops_before_typing_after_a_failed_launch(self):
        ex = FakeExecutor({"open_app": "Could not find an app matching 'notpad'"})
        planner = ActionPlanner(ex)
        out = planner.execute_plan([{"action": "open_app", "target": "notpad"},
                                    {"action": "type_text", "target": "secret notes"}])
        self.assertEqual([a for a, _ in ex.calls], ["open_app"])
        self.assertIn("didn't type", out[-1])

    def test_failure_without_later_input_keeps_going(self):
        ex = FakeExecutor({"open_app": "Could not find an app matching 'x'"})
        planner = ActionPlanner(ex)
        planner.execute_plan([{"action": "open_app", "target": "x"}, {"action": "set_volume", "target": "30"}])
        self.assertEqual([a for a, _ in ex.calls], ["open_app", "set_volume"])

    def test_waits_for_the_launched_window_before_typing(self):
        ex = FakeExecutor({"open_app": "Launched notepad"})
        planner = ActionPlanner(ex, launch_wait_s=2)
        seq = iter([100, 100, 100, 200])                  # notepad comes to the front on the 3rd poll
        planner.foreground = lambda: next(seq, 200)
        planner.execute_plan([{"action": "open_app", "target": "notepad"}, {"action": "type_text", "target": "hi"}])
        self.assertEqual([a for a, _ in ex.calls], ["open_app", "type_text"])

    def test_gives_up_if_the_window_never_appears(self):
        ex = FakeExecutor({"open_app": "Launched notepad"})
        planner = ActionPlanner(ex, launch_wait_s=0.3)
        planner.foreground = lambda: 100
        out = planner.execute_plan([{"action": "open_app", "target": "notepad"}, {"action": "type_text", "target": "hi"}])
        self.assertEqual([a for a, _ in ex.calls], ["open_app"])
        self.assertIn("didn't come to the front", out[-1])

    def test_no_wait_without_later_input(self):
        ex = FakeExecutor({"open_app": "Launched spotify"})
        planner = ActionPlanner(ex, launch_wait_s=5)
        planner.foreground = MagicMock(return_value=100)
        planner.execute_plan([{"action": "open_app", "target": "spotify"}])
        planner.foreground.assert_not_called()


class TestStructuredOutput(unittest.TestCase):
    def setUp(self):
        p = patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def _post(self, client, call):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"message": {"content": '{"reply": "ok", "plan": []}'}}
        ok.iter_lines.return_value = ['{"message": {"content": "{}"}, "done": true}']
        ok.__enter__ = lambda s: s
        ok.__exit__ = lambda s, *a: False
        with patch("engine.llm_client.requests.post", return_value=ok) as post:
            call(client)
        return post.call_args.kwargs["json"]

    def test_schema_constrains_ollama_output(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
        client = LLMClient({"llm": {"local_model": "llama3.2:3b"}})
        self.assertEqual(self._post(client, lambda c: c.chat_json("s", "u", schema=schema))["format"], schema)
        self.assertEqual(self._post(client, lambda c: c.stream_chat("s", "u", schema=schema))["format"], schema)
        self.assertEqual(self._post(client, lambda c: c.chat_json("s", "u"))["format"], "json")
        off = LLMClient({"llm": {"structured_output": False}})
        self.assertEqual(self._post(off, lambda c: c.chat_json("s", "u", schema=schema))["format"], "json")

    def test_no_thinking_for_hybrid_models_only(self):
        self.assertIs(self._post(LLMClient({"llm": {"local_model": "qwen3:4b"}}),
                                 lambda c: c.chat_json("s", "u"))["think"], False)
        for model in ("qwen3:4b-instruct-2507-q4_K_M", "llama3.2:1b", "phi4-mini"):
            self.assertNotIn("think", self._post(LLMClient({"llm": {"local_model": model}}),
                                                 lambda c: c.chat_json("s", "u")), model)

    def test_router_passes_the_plan_schema(self):
        from engine.router import IntentRouter
        router = IntentRouter.__new__(IntentRouter)
        router.config = {"llm": {}}
        router.llm = MagicMock()
        router.llm.cloud_available.return_value = False
        router.llm.plan_with_tools.return_value = None
        router.llm.chat_json.return_value = {"reply": "ok", "plan": []}
        router.tts = MagicMock()
        router.tts.speaking_enabled.return_value = False
        router._plan("User Command: 'mute my mic'", query="mute my mic")
        schema = router.llm.chat_json.call_args.kwargs["schema"]
        self.assertIn("mic_mute", schema["properties"]["plan"]["items"]["properties"]["action"]["enum"])
        self.assertEqual(schema["required"], ["reply", "plan"])


class TestModelSetup(unittest.TestCase):
    def test_size_and_recommendation(self):
        self.assertTrue(model_setup.is_too_small("llama3.2:1b"))
        self.assertTrue(model_setup.is_too_small("qwen2.5:0.5b"))
        self.assertFalse(model_setup.is_too_small("qwen3:4b-instruct-2507-q4_K_M"))
        self.assertEqual(model_setup.recommend(16)[0], "qwen3:4b-instruct-2507-q4_K_M")
        self.assertEqual(model_setup.recommend(4)[0], "qwen3:1.7b")

    def test_pull_falls_back_to_the_next_candidate(self):
        ollama = model_setup.Ollama()
        tags = MagicMock(status_code=200)
        tags.json.return_value = {"models": [{"name": "llama3.2:1b"}]}
        missing = MagicMock(status_code=200)
        missing.iter_lines.return_value = ['{"status": "pulling manifest"}', '{"error": "file does not exist"}']
        good = MagicMock(status_code=200)
        good.iter_lines.return_value = ['{"status": "pulling abc", "total": 100, "completed": 50}',
                                        '{"status": "success"}']
        for r in (missing, good):
            r.__enter__ = lambda s: s
            r.__exit__ = lambda s, *a: False
        lines = []
        with patch("utils.model_setup.requests.get", return_value=tags), \
                patch("utils.model_setup.requests.post", side_effect=[missing, good]):
            got = ollama.pull_first(["qwen3:4b-instruct-2507-q4_K_M", "hf.co/x/y:Q4"], progress=lines.append)
        self.assertEqual(got, "hf.co/x/y:Q4")
        self.assertTrue(any("file does not exist" in line for line in lines))

    def test_already_downloaded_is_not_pulled_again(self):
        tags = MagicMock(status_code=200)
        tags.json.return_value = {"models": [{"name": "qwen3:4b"}]}
        with patch("utils.model_setup.requests.get", return_value=tags), \
                patch("utils.model_setup.requests.post") as post:
            self.assertEqual(model_setup.Ollama().pull_first(["qwen3:4b"], progress=lambda m: None), "qwen3:4b")
        post.assert_not_called()

    def test_switch_writes_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"llm": {"local_model": "llama3.2:1b", "num_ctx": 4096}, "x": 1}))
            with patch("utils.paths.config_path", return_value=cfg):
                model_setup.set_local_model("qwen3:4b")
            saved = json.loads(cfg.read_text())
        self.assertEqual(saved["llm"], {"local_model": "qwen3:4b", "num_ctx": 4096})
        self.assertEqual(saved["x"], 1)


if __name__ == "__main__":
    unittest.main()
