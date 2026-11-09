"""
v4.4 item 4: Smart Turn v3.2 hears whether a sentence is finished. "Finished" starts recognition early
(the reply comes sooner), "unfinished" waits longer (a thinking pause doesn't cut the sentence), and
the silence timer still decides when a turn ends, so a pause after "MXB," never splits a command.
The model downloads on the PC; here scripted sessions stand in, and the microphone loop itself runs
on a real speech clip in a child process (tests/_mic_loop.py).
"""
import importlib.util
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

import tests._stubs  # noqa: F401
from engine.turn_detector import SpeculativeTurn, TurnDetector, turn_features
from utils.fetch_models import MODELS


@unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "features use faster-whisper's extractor")
class TestFeatures(unittest.TestCase):
    def test_shape_and_alignment(self):
        rng = np.random.default_rng(0)
        short = rng.normal(0, 0.05, 16000 * 2).astype(np.float32)
        feats = turn_features(short)
        self.assertEqual(feats.shape, (1, 80, 800))
        self.assertEqual(feats.dtype, np.float32)
        # the speech sits at the end: padding at the front is flat, the tail is not
        self.assertLess(float(feats[0, :, :100].std()), float(feats[0, :, -150:].std()))
        long = rng.normal(0, 0.05, 16000 * 12).astype(np.float32)
        np.testing.assert_allclose(turn_features(long), turn_features(long[-16000 * 8:]), atol=1e-5)

    @unittest.skipUnless(importlib.util.find_spec("transformers"), "reference extractor needs transformers")
    def test_matches_the_reference_extractor(self):
        from transformers import WhisperFeatureExtractor
        x = np.random.default_rng(1).normal(0, 0.1, 16000 * 3).astype(np.float32)
        padded = np.pad(x, (16000 * 5, 0))
        ref = WhisperFeatureExtractor(chunk_length=8)(padded, sampling_rate=16000, return_tensors="np",
                                                      padding="max_length", max_length=128000, truncation=True,
                                                      do_normalize=True).input_features
        np.testing.assert_allclose(turn_features(x), ref, atol=1e-4)


class TestTurnDetector(unittest.TestCase):
    def detector(self, prob, **cfg):
        session = MagicMock()
        session.run.return_value = [np.array([[prob]], dtype=np.float32)]
        return TurnDetector({"turn_detection": cfg}, session=session), session

    def test_decision(self):
        audio = np.zeros(16000, dtype=np.float32)
        det, session = self.detector(0.97)
        self.assertEqual(det.verdict(audio), "complete")
        self.assertTrue(det.is_complete(audio))
        self.assertAlmostEqual(det.last_probability, 0.97, places=5)
        feeds = session.run.call_args.args[1]
        self.assertEqual(feeds["input_features"].shape, (1, 80, 800))
        self.assertEqual(self.detector(0.2)[0].verdict(audio), "unfinished")
        self.assertFalse(self.detector(0.2)[0].is_complete(audio))

    def test_thresholds(self):
        audio = np.zeros(16000, dtype=np.float32)
        self.assertEqual(self.detector(0.5)[0].verdict(audio), "complete")             # one cut-off by default
        self.assertEqual(self.detector(0.49)[0].verdict(audio), "unfinished")
        band = {"complete_threshold": 0.9, "unfinished_threshold": 0.3}                 # optional "unsure" band
        det = self.detector(0.6, **band)[0]
        self.assertEqual(det.verdict(audio), "unsure")
        self.assertIsNone(det.is_complete(audio))
        self.assertEqual(self.detector(0.95, **band)[0].verdict(audio), "complete")
        self.assertEqual(self.detector(0.2, **band)[0].verdict(audio), "unfinished")

    def test_unknown_when_not_loaded_or_failing(self):
        self.assertIsNone(TurnDetector({}).is_complete(np.zeros(16000, dtype=np.float32)))
        self.assertIsNone(TurnDetector({}).verdict(np.zeros(16000, dtype=np.float32)))
        det, session = self.detector(0.97)
        session.run.side_effect = RuntimeError("bad input")
        self.assertIsNone(det.is_complete(np.zeros(16000, dtype=np.float32)))

    def test_can_be_turned_off(self):
        det = TurnDetector({"turn_detection": {"enabled": False}})
        self.assertFalse(det.load())
        self.assertFalse(det.ready)

    def test_settings(self):
        det = TurnDetector({"turn_detection": {"probe_seconds": 0.3, "hold_seconds": 2}})
        self.assertEqual((det.probe_seconds, det.hold_seconds, det.complete_threshold, det.unfinished_threshold),
                         (0.3, 2.0, 0.5, 0.5))

    def test_model_is_pinned(self):
        spec = MODELS["turn"]
        self.assertIn("pipecat-ai/smart-turn-v3", spec["url"])
        self.assertEqual(spec["files"], ["smart-turn-v3.2-cpu.onnx"])
        self.assertEqual(len(spec["sha256"]), 64)

    def test_speculative_turn(self):
        keep = SpeculativeTurn()
        threading.Timer(0.05, keep.confirm).start()
        self.assertTrue(keep.wait(timeout=2))
        drop = SpeculativeTurn()
        drop.cancel()
        self.assertFalse(drop.wait(timeout=2))
        self.assertFalse(SpeculativeTurn().wait(timeout=0.01))      # undecided: never act on a guess

    def test_pipeline_wiring(self):
        source = (Path(__file__).parent.parent / "engine" / "audio.py").read_text(encoding="utf-8")
        for needed in ("self.turn.verdict(np.concatenate(buffer))", "turn_hold_frames", "turn_verdict = None",
                       "self.last_end_of_turn"):
            self.assertIn(needed, source)


@unittest.skipUnless(importlib.util.find_spec("faster_whisper") and importlib.util.find_spec("PySide6"),
                     "the mic loop needs faster-whisper's Silero model and PySide6")
class TestMicLoop(unittest.TestCase):
    """The real microphone loop on a real speech clip ("And so my fellow Americans" / "ask not"),
    Whisper faked, Smart Turn scripted."""

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run([sys.executable, "-m", "tests._mic_loop"], cwd=root, capture_output=True, text=True,
                             timeout=300)
        line = next((ln for ln in out.stdout.splitlines() if ln.startswith("MIC-LOOP-RESULTS ")), None)
        if line is None:
            raise AssertionError(f"mic loop run failed:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
        cls.r = json.loads(line.split(" ", 1)[1])

    def test_finished_sentence_is_transcribed_once_while_the_timer_runs(self):
        r = self.r["finished"]
        self.assertEqual(len(r["submitted"]), 1)
        self.assertEqual(len(r["transcribed_seconds"]), 1)          # the early transcript was the one used
        self.assertIn("transcribing since", r["end_of_turn"][1])

    def test_short_pause_that_sounds_finished_does_not_split_the_command(self):
        # The regression this design prevents: ending the turn on "finished" split commands after "MXB,".
        r = self.r["short_pause_sounds_finished"]
        self.assertEqual(len(r["submitted"]), 1)
        self.assertEqual(len(r["transcribed_seconds"]), 2)          # early transcript dropped, whole one kept
        self.assertGreater(r["transcribed_seconds"][1], r["transcribed_seconds"][0])

    def test_unfinished_sentence_survives_a_long_pause(self):
        self.assertEqual(len(self.r["long_pause_unfinished"]["submitted"]), 1)
        self.assertEqual(len(self.r["long_pause_no_model"]["submitted"]), 2)   # the silence timer alone splits it


if __name__ == "__main__":
    unittest.main()
