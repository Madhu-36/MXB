"""
v4.4 item 7: Kannada / Hindi / Telugu by voice without a restart, and auto-detection limited to the
languages the user actually speaks (Whisper on short commands mixes up Kannada/Tamil, Hindi/Urdu).
"""
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tests._stubs  # noqa: F401
from engine.indic import allowed_languages, parse_language_list, pick_language
from engine.listening import BackgroundModel


class TestLanguageChoice(unittest.TestCase):
    def test_parse_lists(self):
        self.assertEqual(parse_language_list("kannada, hindi and telugu"), ["kn", "hi", "te"])
        self.assertEqual(parse_language_list("Hindi & English"), ["hi", "en"])
        self.assertEqual(parse_language_list("kannada and klingon"), ["kn"])
        self.assertEqual(parse_language_list(""), [])

    def test_allowed_and_pick(self):
        cfg = {"voice": {"languages": ["en", "kn", "HI", "xx"]}}
        self.assertEqual(allowed_languages(cfg), ["en", "kn", "hi"])
        self.assertEqual(allowed_languages({}), [])
        probs = [("ta", 0.41), ("kn", 0.33), ("ml", 0.12), ("en", 0.05)]
        self.assertEqual(pick_language(probs, ["en", "kn", "hi"]), "kn")         # Tamil isn't spoken here
        self.assertEqual(pick_language([("ur", 0.6), ("hi", 0.3)], ["en", "hi"]), "hi")
        self.assertIsNone(pick_language(probs, []))


class TestBackgroundModel(unittest.TestCase):
    def test_loads_once_and_hands_over(self):
        gate = threading.Event()
        loads = []

        def loader(name):
            loads.append(name)
            gate.wait(2)
            return f"model:{name}"
        bm = BackgroundModel(loader)
        self.assertTrue(bm.request("small"))
        self.assertFalse(bm.request("small"))            # already loading
        self.assertIsNone(bm.take())                     # not ready yet
        gate.set()
        for _ in range(100):
            ready = bm.take()
            if ready:
                break
            time.sleep(0.01)
        self.assertEqual(ready, ("small", "model:small"))
        self.assertIsNone(bm.take())                     # handed over once
        self.assertEqual(loads, ["small"])

    def test_failed_load_keeps_the_current_model(self):
        bm = BackgroundModel(lambda name: (_ for _ in ()).throw(OSError("no internet")))
        bm.request("small")
        bm._thread.join(2)
        self.assertIsNone(bm.take())
        self.assertIsInstance(bm.error, OSError)


class TestCommands(unittest.TestCase):
    def route(self, text):
        from bench.routing import RecordingExecutor, SilentTTS
        from engine.router import IntentRouter
        ex = RecordingExecutor()
        router = IntentRouter(executor=ex, tts=SilentTTS())
        with patch.object(router, "_route_to_llm", return_value="__LLM__"):
            router.route(text)
        return ex.calls

    def test_phrases(self):
        self.assertEqual(self.route("I speak kannada, hindi and telugu"), [("set_language", "kannada, hindi and telugu")])
        self.assertEqual(self.route("listen for kannada and english"), [("set_language", "kannada and english")])
        self.assertEqual(self.route("speak in kannada"), [("set_language", "kannada")])

    def test_executor_saves_several_languages(self):
        from engine.executor import OSExecutionManager
        ex = OSExecutionManager.__new__(OSExecutionManager)
        ex.config = {}
        saved = {}
        ex.save_setting = lambda section, key, value: saved.__setitem__((section, key), value)
        with patch("engine.indic.set_preferred_language") as pref:
            reply = ex.set_language("kannada, hindi and telugu")
        self.assertEqual(saved[("voice", "languages")], ["en", "kn", "hi", "te"])
        self.assertEqual(saved[("voice", "language")], "auto")
        pref.assert_called_with("auto")
        self.assertIn("English, Kannada, Hindi, Telugu", reply)

    def test_pipeline_wiring(self):
        source = (Path(__file__).parent.parent / "engine" / "audio.py").read_text(encoding="utf-8")
        for needed in ("pick_language(getattr(info, \"all_language_probs\", None), allowed)", "BackgroundModel(",
                       "swap.take()", "allowed_languages(self.config)"):
            self.assertIn(needed, source)


if __name__ == "__main__":
    unittest.main()
