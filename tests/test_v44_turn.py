"""
v4.4 item 4: turns end on meaning (Smart Turn v3.2), not only on 0.5-0.8 s of silence.
The model itself runs on the PC (it downloads from Hugging Face); here a fake session stands in,
and the features are checked against the reference extractor when transformers is installed.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

import tests._stubs  # noqa: F401
from engine.turn_detector import TurnDetector, turn_features
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
        det, session = self.detector(0.9)
        self.assertTrue(det.is_complete(np.zeros(16000, dtype=np.float32)))
        feeds = session.run.call_args.args[1]
        self.assertEqual(feeds["input_features"].shape, (1, 80, 800))
        self.assertFalse(self.detector(0.2)[0].is_complete(np.zeros(16000, dtype=np.float32)))
        self.assertFalse(self.detector(0.6, threshold=0.7)[0].is_complete(np.zeros(16000, dtype=np.float32)))

    def test_unknown_when_not_loaded_or_failing(self):
        self.assertIsNone(TurnDetector({}).is_complete(np.zeros(16000, dtype=np.float32)))
        det, session = self.detector(0.9)
        session.run.side_effect = RuntimeError("bad input")
        self.assertIsNone(det.is_complete(np.zeros(16000, dtype=np.float32)))

    def test_can_be_turned_off(self):
        det = TurnDetector({"turn_detection": {"enabled": False}})
        self.assertFalse(det.load())
        self.assertFalse(det.ready)

    def test_settings(self):
        det = TurnDetector({"turn_detection": {"probe_seconds": 0.3, "hold_seconds": 2}})
        self.assertEqual((det.probe_seconds, det.hold_seconds, det.threshold), (0.3, 2.0, 0.5))

    def test_model_is_pinned(self):
        spec = MODELS["turn"]
        self.assertIn("pipecat-ai/smart-turn-v3", spec["url"])
        self.assertEqual(spec["files"], ["smart-turn-v3.2-cpu.onnx"])
        self.assertEqual(len(spec["sha256"]), 64)

    def test_pipeline_wiring(self):
        source = (Path(__file__).parent.parent / "engine" / "audio.py").read_text(encoding="utf-8")
        for needed in ("self.turn.is_complete(np.concatenate(buffer))", "turn_hold_frames", "turn_decision = None",
                       "self.last_end_of_turn"):
            self.assertIn(needed, source)


if __name__ == "__main__":
    unittest.main()
