"""v4.2 Indian-language voice and text: detection, safety words, translation bridge, bus flow, TTS voices, Sarvam."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from engine import indic
from engine.indic import (
    IndicBridge, SarvamSTT, classify_answer, code_for, is_stop, language_instruction, looks_romanized,
    script_language, set_preferred_language, set_reply_language, voice_for,
)


class FakeLLM:
    """Deterministic 'translator': maps known phrases, counts calls."""

    TABLE = {"ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ": "open notepad", "नोटपैड खोलो": "open notepad",
             "notepad open maadi": "open notepad", "Opened notepad": "ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆಯಲಾಗಿದೆ"}

    def __init__(self):
        self.calls = []

    def chat(self, system, user, max_tokens=None, json_mode=True, image_png=None):
        self.calls.append((system, user))
        return self.TABLE.get(user)


class TestDetectionAndSafetyWords(unittest.TestCase):
    def test_script_detection(self):
        cases = {"ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ": "kn", "नोटपैड खोलो": "hi", "నోట్‌ప్యాడ్ తెరువు": "te", "நோட்பேட் திற": "ta",
                 "നോട്ട്പാഡ് തുറക്കുക": "ml", "নোটপ্যাড খোলো": "bn", "નોટપેડ ખોલો": "gu"}
        for text, code in cases.items():
            with self.subTest(text=text):
                self.assertEqual(script_language(text), code)
        self.assertEqual(script_language("नोटपैड उघडा", devanagari="mr"), "mr")
        self.assertIsNone(script_language("open notepad"))
        self.assertIsNone(script_language("open notepad please ಹ"))       # one stray letter is not Kannada

    def test_stop_words_in_every_language(self):
        for word in ("ನಿಲ್ಲಿಸು", "रुको", "MXB ఆపు", "நிறுத்து", "ruko", "nillisu", "थांबा।"):
            with self.subTest(word=word):
                self.assertTrue(is_stop(word))
        self.assertFalse(is_stop("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ"))
        self.assertFalse(is_stop("open notepad"))

    def test_yes_no(self):
        for text, want in (("ಹೌದು", True), ("ಬೇಡ", False), ("हाँ", True), ("नहीं", False), ("avunu", True),
                           ("vaddu", False), ("ஆம்", True), ("illai", False), ("haan nahi", None), ("open notepad", None)):
            with self.subTest(text=text):
                self.assertIs(classify_answer(text), want)
        from safety.policy import classify_answer as policy_answer
        self.assertIs(policy_answer("हाँ"), True)          # Devanagari vowel signs used to be stripped
        self.assertIs(policy_answer("ಬೇಡ"), False)
        self.assertIs(policy_answer("yes"), True)

    def test_names_voices_and_romanized(self):
        self.assertEqual(code_for("Kannada"), "kn")
        self.assertEqual(code_for("ಕನ್ನಡ"), "kn")
        self.assertEqual(code_for("kn-IN"), "kn")
        self.assertEqual(code_for("auto"), "auto")
        self.assertIsNone(code_for("klingon"))
        self.assertEqual(voice_for("ನಮಸ್ಕಾರ", "en-IN-NeerjaNeural"), "kn-IN-SapnaNeural")
        self.assertEqual(voice_for("ನಮಸ್ಕಾರ", "en-IN-NeerjaNeural", gender="male"), "kn-IN-GaganNeural")
        self.assertEqual(voice_for("hello", "en-IN-NeerjaNeural"), "en-IN-NeerjaNeural")
        self.assertTrue(looks_romanized("notepad open maadi", "kn"))
        self.assertFalse(looks_romanized("notepad open maadi", "hi"))

    def test_wake_word_in_native_script(self):
        from engine.wake_word import WakeWordGate
        gate = WakeWordGate(mode="wake_word", wake_words=["mxb"])
        self.assertEqual(gate.process("ಎಂಎಕ್ಸ್‌ಬಿ ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ"), "ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ")
        gate.disengage()
        self.assertEqual(gate.process("एमएक्सबी, नोटपैड खोलो"), "नोटपैड खोलो")
        gate.disengage()
        self.assertIsNone(gate.process("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ"))


class TestBridge(unittest.TestCase):
    def tearDown(self):
        set_preferred_language(None)
        set_reply_language(None)

    def test_translation_is_cached_and_falls_back(self):
        llm = FakeLLM()
        bridge = IndicBridge({}, llm_getter=lambda: llm)
        self.assertEqual(bridge.to_english("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ", "kn"), "open notepad")
        self.assertEqual(bridge.to_english("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ", "kn"), "open notepad")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("Kannada", llm.calls[0][0])
        self.assertEqual(bridge.from_english("ಈಗಾಗಲೇ ಕನ್ನಡ", "kn"), "ಈಗಾಗಲೇ ಕನ್ನಡ")     # already Kannada: no call
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(bridge.to_english("ಗೊತ್ತಿಲ್ಲದ ವಾಕ್ಯ", "kn"), "ಗೊತ್ತಿಲ್ಲದ ವಾಕ್ಯ")   # LLM had no answer
        self.assertEqual(IndicBridge({}, llm_getter=lambda: None).from_english("Done.", "kn"), "Done.")
        self.assertEqual(bridge.to_english("open notepad", "en"), "open notepad")

    def test_detect(self):
        bridge = IndicBridge({}, llm_getter=lambda: None)
        self.assertEqual(bridge.detect("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ"), "kn")
        self.assertEqual(bridge.detect("open notepad", hint="te"), "te")
        self.assertIsNone(bridge.detect("notepad open maadi"))      # romanized needs the user's language set
        set_preferred_language("kn")
        self.assertEqual(bridge.detect("notepad open maadi"), "kn")
        self.assertIsNone(bridge.detect("open notepad"))

    def test_reply_language_reaches_the_planner_prompt(self):
        from engine.actions_catalog import planner_system_prompt
        self.assertEqual(language_instruction(), "")
        set_reply_language("kn")
        self.assertIn("Kannada (ಕನ್ನಡ script)", planner_system_prompt())
        seen = []
        t = threading.Thread(target=lambda: seen.append(language_instruction()))
        t.start()
        t.join()
        self.assertEqual(seen, [""])                                  # per worker thread
        set_reply_language(None)
        self.assertNotIn("Reply language", planner_system_prompt())


class TestBusFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from engine.command_bus import CommandBus
        self.llm = FakeLLM()
        router = MagicMock()
        router.executor = MagicMock()
        router.executor.llm = self.llm
        router.executor.planner.abort_event = threading.Event()
        self.routed = []
        router.route.side_effect = lambda text, feedback_callback=None: (self.routed.append(text), "Opened notepad")[1]
        router.tts = MagicMock()
        self.bus = CommandBus({"listening": {"mode": "always"}}, router=router)
        self.addCleanup(self.bus.shutdown)
        self.replies = []
        self.bus.reply_ready.connect(lambda text, src: self.replies.append(text))

    def wait(self, cond, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def test_kannada_command_routes_in_english_and_replies_in_kannada(self):
        self.assertEqual(self.bus.submit("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆ", "text"), "action")
        self.assertTrue(self.wait(lambda: self.replies))
        self.assertEqual(self.routed, ["open notepad"])
        self.assertEqual(self.replies[-1], "ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆಯಲಾಗಿದೆ")

    def test_voice_language_hint_and_english_untouched(self):
        self.bus.submit("open notepad", "text")
        self.assertTrue(self.wait(lambda: self.replies))
        self.assertEqual((self.routed[-1], self.replies[-1]), ("open notepad", "Opened notepad"))
        self.assertEqual(self.llm.calls, [])
        self.bus.submit("नोटपैड खोलो", "voice", lang="hi")
        self.assertTrue(self.wait(lambda: len(self.routed) == 2))

    def test_stop_in_kannada_is_instant(self):
        self.assertEqual(self.bus.submit("ನಿಲ್ಲಿಸು", "voice"), "stopped")
        self.assertEqual(self.bus.submit("ruko", "text"), "stopped")


class TestSpeech(unittest.TestCase):
    def test_modality_tts_localizes_english_replies(self):
        from engine.tts import ModalityTTS
        inner = MagicMock()
        tts = ModalityTTS(inner)
        tts.set_thread_language("kn", lambda text, code: {"Opened notepad": "ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆಯಲಾಗಿದೆ"}.get(text, text))
        tts.speak_always("Opened notepad")
        inner.speak.assert_called_with("ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆಯಲಾಗಿದೆ", wait=False)
        tts.speak_always("ಸರಿ")
        inner.speak.assert_called_with("ಸರಿ", wait=False)
        tts.set_thread_language(None)
        tts.speak_always("Opened notepad")
        inner.speak.assert_called_with("Opened notepad", wait=False)

    def test_edge_voice_follows_the_script(self):
        try:
            from engine.tts import EdgeBackend
            backend = EdgeBackend({"edge_voice": "en-IN-NeerjaNeural"})
        except Exception as e:
            self.skipTest(f"edge-tts/miniaudio unavailable: {e}")
        used = []

        class FakeCommunicate:
            def __init__(self, text, voice, rate=None):
                used.append(voice)

            async def stream(self):
                if False:
                    yield {}

        with patch("edge_tts.Communicate", FakeCommunicate):
            for text in ("ನಮಸ್ಕಾರ", "hello"):
                with self.assertRaises(RuntimeError):     # no audio from the fake
                    backend.synth(text)
        self.assertEqual(used, ["kn-IN-SapnaNeural", "en-IN-NeerjaNeural"])

    def test_edge_synth_fallback_when_miniaudio_fails(self):
        try:
            from engine.tts import EdgeBackend
            backend = EdgeBackend({"edge_voice": "en-IN-NeerjaNeural"})
        except Exception as e:
            self.skipTest(f"edge-tts unavailable: {e}")

        class FakeAudioCommunicate:
            def __init__(self, text, voice, rate=None):
                pass
            async def stream(self):
                yield {"type": "audio", "data": b"FAKE_MP3_DATA"}

        with patch("edge_tts.Communicate", FakeAudioCommunicate):
            with patch.dict("sys.modules", {"miniaudio": None}):
                pcm, rate = backend.synth("Hello world")
                self.assertEqual(rate, 24000)
                self.assertGreater(len(pcm), 0)


class TestSarvamAndLanguageSwitch(unittest.TestCase):
    def test_sarvam_request_and_response(self):
        http = MagicMock()
        http.post.return_value = MagicMock(status_code=200, json=lambda: {"transcript": "open notepad", "language_code": "kn-IN"})
        text, lang = SarvamSTT("key-1", http=http).transcribe(b"RIFF....", "auto")
        self.assertEqual((text, lang), ("open notepad", "kn"))
        kwargs = http.post.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"api-subscription-key": "key-1"})
        self.assertEqual(kwargs["data"], {"model": "saaras:v3", "language_code": "unknown", "mode": "translate"})
        SarvamSTT("k", http=http).transcribe(b"x", "te")
        self.assertEqual(http.post.call_args.kwargs["data"]["language_code"], "te-IN")
        http.post.return_value = MagicMock(status_code=200, json=lambda: {"transcript": "hi", "language_code": "en-IN"})
        self.assertEqual(SarvamSTT("k", http=http).transcribe(b"x")[1], None)
        http.post.return_value = MagicMock(status_code=403, text="bad key")
        with self.assertRaisesRegex(RuntimeError, "403"):
            SarvamSTT("k", http=http).transcribe(b"x")

    def test_set_language_command(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(set_preferred_language, None)
        from engine.executor import OSExecutionManager
        from utils.paths import load_config
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MXB_DATA_DIR": tmp}):
            ex = OSExecutionManager(config={})
            ex.audit = MagicMock()
            self.assertIn("Kannada (ಕನ್ನಡ)", ex.execute_action("set_language", "kannada"))
            self.assertEqual(indic.preferred_language(), "kn")
            self.assertEqual(load_config()["voice"]["language"], "kn")
            self.assertIn("don't know the language", ex.execute_action("set_language", "klingon"))
            self.assertIn("English", ex.execute_action("set_language", "english"))


if __name__ == "__main__":
    unittest.main()
