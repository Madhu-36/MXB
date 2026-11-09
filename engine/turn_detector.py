"""
Has the user finished speaking? (config "turn_detection")

MXB used to decide by silence alone: 0.5-0.8 s of quiet ended a turn. That answers late after a
complete sentence and cuts people off mid-thought ("open the... uhh... downloads folder").
In natural conversation the gap between one speaker finishing and the next starting averages
about 200 ms.

Smart Turn v3.2 (Pipecat, BSD-2-Clause; Whisper-Tiny encoder + classifier, 8.7 MB int8 ONNX, ~10-65 ms
on a CPU) listens to the last 8 s of the utterance, intonation included, and says whether the turn
is complete. MXB asks it once per pause, ~0.2 s into the silence:
- complete    -> transcribe now (about 0.3-0.6 s sooner than before)
- incomplete  -> keep listening up to turn_detection.hold_seconds (1.5 s) of silence

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


class TurnDetector:
    def __init__(self, config: dict | None = None, session=None):
        cfg = (config or {}).get("turn_detection", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.threshold = float(cfg.get("threshold", 0.5))
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

    def is_complete(self, audio: np.ndarray) -> bool | None:
        """True / False, or None when it can't tell (not loaded, or the model failed)."""
        if not self.ready:
            return None
        try:
            return self.complete_probability(audio) >= self.threshold
        except Exception as e:
            log.warning(f"TurnDetector: {e}; ending this turn on silence.")
            return None
