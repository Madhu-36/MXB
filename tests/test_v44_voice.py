"""
v4.4 item 3: voice ID (only the owner's voice commands MXB) and "MXB" spotted in the audio.
Fakes stand in for the models here; the real TitaNet / zipformer models were checked separately
(owner 0.85-0.93, other voices <= 0.33; "MXB" woke on three voices, look-alikes didn't).
"""
import bz2
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

import tests._stubs  # noqa: F401
from engine.kws_engine import DEFAULT_KEYWORDS, SherpaKWSEngine, encode_phrases, keyword_lines
from engine.voice_id import VoiceID, is_stop_phrase
from utils import fetch_models


def voice(speaker: int, seconds: float = 2.0) -> np.ndarray:
    """Fake audio: the first sample carries the speaker id the fake extractor reads."""
    a = np.full(int(16000 * seconds), 0.01, dtype=np.float32)
    a[0] = speaker
    return a


class FakeExtractor:
    """Speaker n -> a fixed direction; speaker 9 is 'noisy' (half-way between 1 and 2)."""

    def __call__(self, audio):
        n = int(round(float(audio[0])))
        e = np.zeros(8, dtype=np.float32)
        if n == 9:
            e[1] = e[2] = 1.0
        else:
            e[n % 8] = 1.0
        return e / np.linalg.norm(e)


class TestStopPhrases(unittest.TestCase):
    def test_anyone_may_stop_mxb(self):
        for text in ("Stop!", "stop stop", "MXB stop", "please cancel that", "never mind"):
            self.assertTrue(is_stop_phrase(text), text)
        for text in ("open notepad", "stop the music and open chrome right now please", "", "bus stop near me tomorrow"):
            self.assertFalse(is_stop_phrase(text), text)


class TestVoiceID(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "voice_id.npz"

    def enrolled(self, **cfg):
        vid = VoiceID({"voice_id": cfg}, extractor=FakeExtractor(), store=self.store)
        vid.start_enrollment()
        for _ in range(4):
            reply = vid.add_sample(voice(1, 3.0))
        self.assertIn("only take commands from your voice", reply)
        return vid

    def test_off_until_enrolled(self):
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())
        self.assertEqual(vid.check(voice(2), "delete my files"), (True, "voice ID off"))
        self.assertIn("isn't set up", vid.status())

    def test_owner_allowed_others_ignored(self):
        vid = self.enrolled()
        self.assertTrue(vid.check(voice(1), "open notepad")[0])
        allowed, why = vid.check(voice(2), "okay nice")
        self.assertFalse(allowed)
        self.assertIn("not your voice", why)
        self.assertTrue(vid.check(voice(2, 0.6), "stop")[0])                 # anyone may stop MXB

    def test_short_utterances_get_the_benefit_of_the_doubt_only_when_close(self):
        vid = self.enrolled()
        self.assertTrue(vid.check(voice(9, 0.8), "yes")[0])                 # 0.71: allowed anyway
        vid.threshold = 0.9
        self.assertTrue(vid.check(voice(9, 0.8), "yes")[0])                 # too short to judge, >= floor
        self.assertFalse(vid.check(voice(9, 2.0), "delete everything")[0])  # long enough to judge
        self.assertFalse(vid.check(voice(3, 0.8), "yes")[0])                # clearly someone else

    def test_enrolment_rejects_short_and_mixed_samples(self):
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        vid.start_enrollment()
        self.assertIn("short", vid.add_sample(voice(1, 0.5)))
        self.assertEqual(vid.enrolling, 4)
        for speaker in (1, 2, 1, 2):
            reply = vid.add_sample(voice(speaker, 3.0))
        self.assertIn("didn't sound like the same voice", reply)
        self.assertFalse(vid.ready())

    def test_voiceprint_survives_a_restart_and_can_be_forgotten(self):
        self.enrolled()
        again = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertTrue(again.ready())
        self.assertIn("saved on", again.status())
        self.assertIn("forgotten", again.forget())
        self.assertFalse(self.store.exists())
        self.assertFalse(VoiceID({}, extractor=FakeExtractor(), store=self.store).ready())

    def test_can_be_switched_off(self):
        vid = self.enrolled()
        vid.set_enabled(False)
        self.assertTrue(vid.check(voice(2), "anything")[0])
        self.assertFalse(VoiceID({"voice_id": {"enabled": False}}, extractor=FakeExtractor(), store=self.store).ready())

    def test_corrupted_profiles_and_file_locking(self):
        # 1. Zero bytes
        self.store.write_bytes(b"")
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())
        self.assertIsNone(vid.owner)

        # 2. Random bytes
        self.store.write_bytes(b"invalid npz archive contents")
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())

        # 3. Valid npz but missing owner key
        np.savez(self.store, wrong_key=np.array([1, 2, 3]))
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())

        # 4. Owner array containing NaNs
        np.savez(self.store, owner=np.array([np.nan] * 8, dtype=np.float32))
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())

        # 5. Owner array all zeros (norm < 1e-4)
        np.savez(self.store, owner=np.zeros(8, dtype=np.float32))
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertFalse(vid.ready())

        # 6. Windows file lock test: ensure file handle is closed so replacing/saving succeeds
        np.savez(self.store, owner=np.ones(8, dtype=np.float32), enrolled_at=np.array("2026-11-10"))
        vid = VoiceID({}, extractor=FakeExtractor(), store=self.store)
        self.assertTrue(vid.ready())
        # Overwrite file while vid is loaded — on Windows this would fail if file wasn't closed
        vid._save()
        self.assertTrue(self.store.exists())

    def test_thread_safety_concurrent_access(self):
        vid = self.enrolled()
        import threading
        errors = []

        def worker():
            for _ in range(50):
                try:
                    vid.check(voice(1), "open notepad")
                    vid.status()
                    vid.ready()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        # Concurrently toggle and forget/enroll
        for _ in range(10):
            vid.set_enabled(False)
            vid.set_enabled(True)
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestKeywordSpotting(unittest.TestCase):
    def test_default_phrases_need_no_sentencepiece(self):
        phrases = encode_phrases(["mxb", "hey mxb"], bpe_model="missing.model")
        self.assertEqual(set(phrases), set(DEFAULT_KEYWORDS))
        self.assertEqual(phrases["M X B"], ["▁", "M", "▁", "X", "▁B"])
        line = keyword_lines({"M X B": phrases["M X B"]}, boost=1.5, threshold=0.2)
        self.assertEqual(line, "▁ M ▁ X ▁B :1.5 #0.2 @M_X_B\n")

    def test_fires_once_per_detection_with_cooldown(self):
        eng = SherpaKWSEngine(cooldown=60)
        spotter = MagicMock()
        ready = iter([True, False, True, False])
        spotter.is_ready.side_effect = lambda s: next(ready, False)
        spotter.get_result.side_effect = ["M_X_B", "M_X_B"]
        eng.spotter, eng.stream = spotter, MagicMock()
        self.assertTrue(eng.process(np.zeros(512, dtype=np.float32)))
        self.assertFalse(eng.process(np.zeros(512, dtype=np.float32)))     # within the cooldown
        self.assertEqual(spotter.reset_stream.call_count, 2)

    def test_unavailable_engine_never_fires(self):
        self.assertFalse(SherpaKWSEngine().process(np.zeros(512, dtype=np.float32)))


class TestModelDownloads(unittest.TestCase):
    def fake_session(self, payload: bytes):
        resp = MagicMock()
        resp.iter_content.return_value = [payload]
        resp.raise_for_status.return_value = None
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        return MagicMock(get=MagicMock(return_value=resp))

    def test_checksum_and_archive_extraction(self):
        files = {"a.onnx": b"A" * 10, "tokens.txt": b"x 1\n", "junk.txt": b"ignored"}
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(f"model-dir/{name}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        payload = bz2.compress(raw.getvalue())
        spec = {"url": "https://example.invalid/m.tar.bz2", "sha256": hashlib.sha256(payload).hexdigest(),
                "files": ["a.onnx", "tokens.txt"], "mb": 1}
        with tempfile.TemporaryDirectory() as d, patch.dict(fetch_models.MODELS, {"t": spec}), \
                patch("utils.fetch_models.models_dir", return_value=Path(d)):
            folder = fetch_models.fetch("t", progress=lambda m: None, session=self.fake_session(payload))
            self.assertEqual((folder / "a.onnx").read_bytes(), files["a.onnx"])
            self.assertFalse((folder / "junk.txt").exists())
            self.assertTrue(fetch_models.is_ready("t"))
            bad = dict(spec, sha256="0" * 64)
            with patch.dict(fetch_models.MODELS, {"u": bad}):
                with self.assertRaises(RuntimeError):
                    fetch_models.fetch("u", progress=lambda m: None, session=self.fake_session(payload))
                self.assertFalse(fetch_models.is_ready("u"))

    def test_pinned_models(self):
        for name, spec in fetch_models.MODELS.items():
            self.assertTrue(spec["url"].startswith(("https://github.com/k2-fsa/sherpa-onnx/releases/",
                                                     "https://huggingface.co/pipecat-ai/")), name)
            self.assertEqual(len(spec["sha256"]), 64)
            int(spec["sha256"], 16)


class TestVoiceCommands(unittest.TestCase):
    def route(self, text):
        from bench.routing import RecordingExecutor, SilentTTS
        from engine.router import IntentRouter
        ex = RecordingExecutor()
        router = IntentRouter(executor=ex, tts=SilentTTS())
        with patch.object(router, "_route_to_llm", return_value="__LLM__"):
            router.route(text)
        return ex.calls

    def test_phrases(self):
        self.assertEqual(self.route("learn my voice"), [("voice_id", "enroll")])
        self.assertEqual(self.route("only listen to me"), [("voice_id", "enroll")])
        self.assertEqual(self.route("forget my voice"), [("voice_id", "forget")])
        self.assertEqual(self.route("turn off voice id"), [("voice_id", "off")])
        self.assertEqual(self.route("voice id on"), [("voice_id", "on")])
        self.assertEqual(self.route("do you know my voice"), [("voice_id", "status")])

    def test_executor_action(self):
        from engine.executor import OSExecutionManager
        ex = OSExecutionManager.__new__(OSExecutionManager)
        ex.config = {}
        ex._voice_id = MagicMock()
        ex._voice_id.start_enrollment.return_value = "Okay. Say 4 sentences."
        ex.save_setting = MagicMock()
        self.assertEqual(ex.v44_action("voice_id", "enroll"), "Okay. Say 4 sentences.")
        ex.v44_action("voice_id", "off")
        ex.save_setting.assert_called_with("voice_id", "enabled", False)
        ex._voice_id.set_enabled.assert_called_with(False)

    def test_pipeline_wiring(self):
        source = (Path(__file__).parent.parent / "engine" / "audio.py").read_text(encoding="utf-8")
        for needed in ("vid.add_sample(audio_data)", "vid.check(audio_data, text)", "SherpaKWSEngine(",
                       'engine_name == "kws"'):
            self.assertIn(needed, source)


if __name__ == "__main__":
    unittest.main()
