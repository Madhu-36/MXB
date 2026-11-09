"""v4 real-time voice: barge-in, echo filtering, TTS backend selection, offline wake word."""
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import tests._stubs  # noqa: F401
from engine.barge_in import BargeInDetector, is_probable_echo, resolve_mode
from engine.wake_engine import OpenWakeWordEngine, wake_phrase_words, FRAME
from engine.wake_word import WakeWordGate
from engine import tts as tts_mod


class TestBargeIn(unittest.TestCase):
    def test_mode_resolution(self):
        self.assertEqual(resolve_mode("auto", "Headset Microphone (boAt Airdopes 141)"), "headset")
        self.assertEqual(resolve_mode("auto", "Microphone Array (Realtek(R) Audio)"), "speaker")
        self.assertEqual(resolve_mode("off", "Headset"), "off")
        self.assertEqual(resolve_mode("speaker", "Headset"), "speaker")

    def test_echo_filter(self):
        spoken = ["Opening Chrome and searching for lofi music now.", "Give me a second."]
        self.assertTrue(is_probable_echo("searching for lofi music", spoken))
        self.assertTrue(is_probable_echo("give me a second", spoken))
        self.assertTrue(is_probable_echo("", spoken))
        self.assertFalse(is_probable_echo("stop", spoken))
        self.assertFalse(is_probable_echo("no open youtube instead", spoken))

    def test_detector_needs_sustained_confident_speech(self):
        d = BargeInDetector(prob_threshold=0.8, min_frames=3, rms_floor=0.004)
        self.assertFalse(d.update(0.9, 0.01))
        self.assertFalse(d.update(0.9, 0.01))
        self.assertTrue(d.update(0.95, 0.02))
        d.reset()
        self.assertFalse(d.update(0.9, 0.001))   # too quiet: likely far-field echo
        self.assertFalse(d.update(0.5, 0.05))    # not confident


class TestBackendSelection(unittest.TestCase):
    def test_auto_falls_back_to_sapi(self):
        with patch.object(tts_mod.EdgeBackend, "__init__", side_effect=ImportError("no edge")), \
                patch.object(tts_mod.PiperBackend, "__init__", side_effect=RuntimeError("no piper")):
            backend = tts_mod.choose_backend({"tts_engine": "auto"})
        self.assertEqual(backend.name, "sapi")

    def test_edge_selected_when_available(self):
        backend = tts_mod.choose_backend({"tts_engine": "edge", "edge_voice": "en-IN-PrabhatNeural"})
        self.assertEqual(backend.name, "edge")
        self.assertEqual(backend.voice, "en-IN-PrabhatNeural")

    def test_piper_requires_model(self):
        with self.assertRaises(RuntimeError):
            tts_mod.PiperBackend({"piper_model": "missing.onnx"})

    def test_pcm_playback_is_interruptible(self):
        written = []

        class FakeStream:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def write(self, data):
                written.append(len(data))
                if len(written) == 3:
                    interrupt.set()

        interrupt = threading.Event()
        fake_sd = type("SD", (), {"OutputStream": FakeStream})
        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            tts_mod._PcmBackend.play(np.zeros(24000 * 2, dtype=np.int16), 24000, interrupt)
        self.assertEqual(len(written), 3)  # stopped after the interrupt, not all 50 blocks


class FakeOWW:
    def __init__(self, scores):
        self.scores = list(scores)
        self.calls = 0

    def predict(self, frame):
        assert len(frame) == FRAME and frame.dtype == np.int16
        self.calls += 1
        return {"hey_jarvis": self.scores.pop(0) if self.scores else 0.0}


class TestWakeEngine(unittest.TestCase):
    def test_phrase_words(self):
        self.assertEqual(wake_phrase_words("hey_jarvis"), ["jarvis"])
        self.assertEqual(wake_phrase_words("C:/models/hey_mxb_v0.1.onnx"), ["mxb"])
        self.assertEqual(wake_phrase_words("alexa"), ["alexa"])

    def test_frames_threshold_and_cooldown(self):
        eng = OpenWakeWordEngine(threshold=0.5, cooldown=10)
        eng.model = FakeOWW([0.1, 0.9, 0.95])
        self.assertFalse(eng.process(np.zeros(1000, dtype=np.float32)))      # not a full frame yet
        self.assertFalse(eng.process(np.zeros(500, dtype=np.float32)))       # 1 frame, score 0.1
        self.assertTrue(eng.process(np.zeros(FRAME, dtype=np.float32)))      # score 0.9 -> fires
        self.assertFalse(eng.process(np.zeros(FRAME, dtype=np.float32)))     # cooldown suppresses repeat
        self.assertEqual(eng.model.calls, 3)

    def test_unloaded_engine_never_fires(self):
        self.assertFalse(OpenWakeWordEngine().process(np.ones(FRAME * 3, dtype=np.float32)))

    def test_gate_accepts_model_phrase(self):
        gate = WakeWordGate(mode="wake_word")
        gate.add_wake_word("jarvis")
        self.assertEqual(gate.process("Hey Jarvis, open Chrome"), "open Chrome")


class TestTTSThreadPrefetch(unittest.TestCase):
    def test_prefetch_synthesizes_next_sentence_while_playing(self):
        order = []

        class FakeBackend(tts_mod._PcmBackend):
            name = "fake"

            def synth(self, text):
                order.append(("synth", text))
                return np.zeros(10, dtype=np.int16), 16000

            def play(self, samples, rate, interrupt):
                order.append(("play", None))
                time.sleep(0.05)

        thread = tts_mod.TTSThread({})
        thread.backend = FakeBackend()
        thread.text_queue.put("Second sentence.")
        thread._speak_one("First sentence.")
        self.assertEqual(order[0], ("synth", "First sentence."))
        self.assertIn(("synth", "Second sentence."), order[:3])   # prefetched before/while playing the first
        thread._prefetch_pool.shutdown(wait=True)




def _audio_importable() -> bool:
    try:
        import engine.audio  # noqa: F401  (needs PortAudio, which Linux CI runners don't have)
        return True
    except Exception:
        return False


@unittest.skipUnless(_audio_importable(), "engine.audio needs PortAudio (sounddevice)")
class TestAudioBufferOverflow(unittest.TestCase):
    def test_audio_callback_overflow_guard(self):
        from unittest.mock import MagicMock
        from engine.audio import VoicePipeline
        pipeline = VoicePipeline.__new__(VoicePipeline)
        import queue
        pipeline.raw_audio_queue = queue.Queue(maxsize=2)
        pipeline._dropped_audio_frames = 0
        pipeline.is_listening = True
        pipeline.barge_in_mode = "off"
        pipeline.is_tts_speaking = False
        pipeline.tts_finish_time = 0.0

        # Fill queue to capacity
        frame = np.zeros(512, dtype=np.float32)
        pipeline.audio_callback(frame, 512, None, None)
        pipeline.audio_callback(frame, 512, None, None)
        self.assertEqual(pipeline.dropped_audio_frames, 0)

        # Third frame exceeds capacity and triggers overflow guard
        pipeline.audio_callback(frame, 512, None, None)
        self.assertEqual(pipeline.dropped_audio_frames, 1)
        self.assertEqual(pipeline.raw_audio_queue.qsize(), 2)

if __name__ == "__main__":
    unittest.main()
