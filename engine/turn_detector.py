"""
Has the user finished speaking? (config "turn_detection")

MXB used to decide by silence alone: 0.5-0.8 s of quiet ended a turn. That answers late after a
complete sentence and cuts people off mid-thought ("open the... uhh... downloads folder").
In natural conversation the gap between one speaker finishing and the next starting averages
about 200 ms.

Smart Turn v3.2 (Pipecat, BSD-2-Clause; Whisper-Tiny encoder + classifier, 8.7 MB int8 ONNX, ~50 ms
on one CPU core) listens to the last 8 s of the utterance, intonation included, and gives the
probability that the turn is complete. MXB asks it once per pause, 0.2 s into the silence:
- p >= complete_threshold (0.5): sounds finished. Recognition starts right away, in parallel with
  the silence timer, and the command is released when the timer confirms the pause. If the user
  keeps talking first, that early transcript is thrown away and the sentence continues as one.
- p <  unfinished_threshold (0.5): sounds unfinished. Keep listening up to hold_seconds (1.5 s).
- in between (only when the two thresholds differ): the silence timer alone decides.

Why the model never ends a turn by itself (measured in v4.4 through MXB's real mic loop with
synthetic voices, Whisper faked): ending the turn at 0.2 s on "finished" split 15 of 40 complete
commands, mostly right after "MXB," (a name alone sounds finished), which made MXB say "Yes?" over
the rest of the sentence. The old timer split none. Starting recognition early gives the same speed-up
(the 0.3-0.5 s the timer waits overlaps transcription) without ever cutting a sentence.

Features match the reference (transformers WhisperFeatureExtractor, chunk_length=8, normalized
waveform) to within 7e-6, computed with faster-whisper's numpy extractor, so no transformers/torch.
"""
import functools
import threading

import numpy as np

from utils.logger import log

SECONDS = 8
RATE = 16000


@functools.lru_cache(maxsize=1)
def _extractor():
    from faster_whisper.feature_extractor import FeatureExtractor
    return FeatureExtractor(feature_size=80, sampling_rate=RATE, hop_length=160, chunk_length=SECONDS, n_fft=400)


def turn_features(audio: np.ndarray) -> np.ndarray:
    """(1, 80, 800) log-mel features of the last 8 s, exactly as Smart Turn was trained on."""
    n = SECONDS * RATE
    x = np.asarray(audio, dtype=np.float32)
    x = x[-n:] if len(x) > n else np.pad(x, (n - len(x), 0))      # the speech sits at the end
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    return _extractor()(x, padding=0)[np.newaxis].astype(np.float32)


class SpeculativeTurn:
    """An utterance handed to recognition before the silence timer confirmed that the turn is over.
    The microphone loop decides; the recognition thread waits for the decision before acting on it."""

    def __init__(self):
        self._decided = threading.Event()
        self.keep = False

    def confirm(self):
        self.keep = True
        self._decided.set()

    def cancel(self):
        self.keep = False
        self._decided.set()

    def wait(self, timeout: float = 5.0) -> bool:
        """True once confirmed; False if cancelled or undecided after timeout (never act on a guess)."""
        return self._decided.wait(timeout) and self.keep


class TurnDetector:
    def __init__(self, config: dict | None = None, session=None):
        cfg = (config or {}).get("turn_detection", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.complete_threshold = float(cfg.get("complete_threshold", 0.5))
        self.unfinished_threshold = float(cfg.get("unfinished_threshold", 0.5))
        self.last_probability: float | None = None
        self.probe_seconds = float(cfg.get("probe_seconds", 0.2))
        self.hold_seconds = float(cfg.get("hold_seconds", 1.5))
        self._session = session
        self._lock = threading.Lock()
        self.ready = session is not None

    def load(self) -> bool:
        if not self.enabled:
            return False
        if self._session is not None:
            return True
        try:
            import onnxruntime as ort
            from utils.fetch_models import MODELS, fetch
            folder = fetch("turn", progress=lambda m: log.info(f"TurnDetector: {m}"))
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            self._session = ort.InferenceSession(str(folder / MODELS["turn"]["files"][0]), sess_options=opts,
                                                 providers=["CPUExecutionProvider"])
            self.ready = True
            log.info("TurnDetector: Smart Turn v3.2 loaded; turns end on meaning, not only on silence.")
            return True
        except Exception as e:
            log.warning(f"TurnDetector: unavailable ({e}); ending turns on silence alone.")
            self._session, self.ready = None, False
            return False

    def complete_probability(self, audio: np.ndarray) -> float:
        with self._lock:
            out = self._session.run(None, {"input_features": turn_features(audio)})
        return float(np.asarray(out[0]).reshape(-1)[0])

    def verdict(self, audio: np.ndarray) -> str | None:
        """'complete', 'unfinished' or 'unsure'; None when the model isn't loaded or failed."""
        if not self.ready:
            return None
        try:
            p = self.complete_probability(audio)
        except Exception as e:
            log.warning(f"TurnDetector: {e}; ending this turn on silence.")
            return None
        self.last_probability = p
        if p >= self.complete_threshold:
            return "complete"
        if p < self.unfinished_threshold:
            return "unfinished"
        return "unsure"

    def is_complete(self, audio: np.ndarray) -> bool | None:
        """True (finished), False (unfinished), or None (unsure, not loaded, or the model failed)."""
        v = self.verdict(audio)
        return True if v == "complete" else False if v == "unfinished" else None
