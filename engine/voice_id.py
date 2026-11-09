"""
Voice ID: once you teach MXB your voice, it only takes commands from you.

Why: the listening bench on the user's PC heard background talk ("Bye!", "Okay, nice.") right after
"MXB, open Notepad" and would have run it as a follow-up command; a TV saying "MXB" could command it.

How: NVIDIA TitaNet-small speaker embeddings (192 numbers per utterance, ~40 ms on a laptop CPU,
via sherpa-onnx). Enrolment averages 4 utterances of your voice into one "voiceprint". Every later
utterance is compared with it (cosine similarity).

Measured on real recordings of 5 different speakers (sherpa-onnx speaker-recognition test set, a
public-domain speech, a read-speech sample): other people never scored above 0.36; the owner scored
>= 0.4 in 94% of 1.5 s commands and 100% of 2.5 s ones. Hence the rules:
- similarity >= threshold (0.38)           -> you
- under 1 s and similarity >= 0.2          -> too short to judge, allowed
- "stop" / "cancel" from anyone            -> always allowed (anyone in the room may stop MXB)
- anything else                            -> ignored, and logged
Nothing leaves the PC: the voiceprint is 192 numbers in voice_id.npz in MXB's data folder.
"""
import re
import threading
import time
from pathlib import Path

import numpy as np

from utils.logger import log

STOP_WORDS = {"stop", "cancel", "wait", "quiet", "shut up", "pause", "abort", "enough", "never mind", "nevermind"}


def is_stop_phrase(text: str) -> bool:
    """Short utterances like "stop", "MXB stop", "please cancel that"."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words or len(words) > 4:
        return False
    joined = " ".join(words)
    return any(re.search(rf"\b{re.escape(w)}\b", joined) for w in STOP_WORDS)


class SherpaExtractor:
    """TitaNet-small through sherpa-onnx; returns a unit-length embedding."""

    def __init__(self, model_file: Path):
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model_file), num_threads=1)
        self._ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        self._lock = threading.Lock()

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        with self._lock:
            stream = self._ext.create_stream()
            stream.accept_waveform(16000, np.asarray(audio, dtype=np.float32))
            stream.input_finished()
            emb = np.asarray(self._ext.compute(stream), dtype=np.float32)
        return emb / (np.linalg.norm(emb) or 1.0)


class VoiceID:
    SAMPLES = 4

    def __init__(self, config: dict | None = None, extractor=None, store: Path | None = None, speak=None):
        cfg = (config or {}).get("voice_id", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.threshold = float(cfg.get("threshold", 0.38))
        self.floor = float(cfg.get("short_floor", 0.2))
        self.short_s = float(cfg.get("short_seconds", 1.0))
        self._extractor = extractor
        self._store = store
        self.speak = speak or (lambda text: None)
        self.owner: np.ndarray | None = None
        self.enrolled_at = ""
        self._samples: list[np.ndarray] = []
        self.enrolling = 0                      # utterances still wanted for enrolment
        self.last_score: float | None = None
        self._load()

    # ------------------------------------------------------------------ storage
    @property
    def store(self) -> Path:
        if self._store is None:
            from utils.paths import data_dir
            self._store = data_dir() / "voice_id.npz"
        return self._store

    def _load(self):
        try:
            if self.store.exists():
                data = np.load(self.store)
                self.owner = data["owner"].astype(np.float32)
                self.enrolled_at = str(data["enrolled_at"]) if "enrolled_at" in data else ""
        except Exception as e:
            log.warning(f"VoiceID: couldn't read the voiceprint ({e}); voice ID is off until you enrol again.")
            self.owner = None

    def _save(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_name(self.store.stem + ".tmp.npz")
        np.savez(tmp, owner=self.owner, enrolled_at=np.array(self.enrolled_at))
        tmp.replace(self.store)

    # ------------------------------------------------------------------ model
    def extractor(self):
        if self._extractor is None:
            from utils.fetch_models import fetch, model_path, MODELS
            fetch("voice_id", progress=lambda m: log.info(f"VoiceID: {m}"))
            self._extractor = SherpaExtractor(model_path("voice_id") / MODELS["voice_id"]["files"][0])
        return self._extractor

    def ready(self) -> bool:
        return self.enabled and self.owner is not None

    def score(self, audio: np.ndarray) -> float:
        emb = self.extractor()(audio)
        return float(np.dot(emb, self.owner))

    # ------------------------------------------------------------------ the gate
    def check(self, audio: np.ndarray, text: str) -> tuple[bool, str]:
        """(allowed, why). Only consulted once someone has enrolled."""
        if not self.ready():
            return True, "voice ID off"
        if is_stop_phrase(text):
            return True, "stop words are allowed from anyone"
        seconds = len(audio) / 16000
        try:
            s = self.score(audio)
        except Exception as e:
            log.warning(f"VoiceID: couldn't check this voice ({e}); letting it through.")
            return True, "check failed"
        self.last_score = s
        if s >= self.threshold:
            return True, f"your voice ({s:.2f})"
        if seconds < self.short_s and s >= self.floor:
            return True, f"too short to judge ({s:.2f}, {seconds:.1f} s)"
        return False, f"not your voice ({s:.2f})"

    # ------------------------------------------------------------------ enrolment
    def start_enrollment(self, samples: int = SAMPLES) -> str:
        try:
            self.extractor()                     # downloads the model now, not halfway through
        except Exception as e:
            return f"I can't learn voices on this PC yet: {e}. Install sherpa-onnx (pip install sherpa-onnx)."
        self._samples = []
        self.enrolling = samples
        return (f"Okay. Say {samples} sentences, any you like, each about three seconds long, with a short pause "
                "between them. For example: what's the weather today.")

    def add_sample(self, audio: np.ndarray) -> str | None:
        """Feeds one enrolment utterance; returns a message to speak, or None to stay quiet."""
        if not self.enrolling:
            return None
        if len(audio) < 16000 * 1.2:
            return "That was a bit short. Say a full sentence."
        self._samples.append(self.extractor()(audio))
        self.enrolling -= 1
        if self.enrolling:
            return None if self.enrolling > 1 else "One more."
        embs = np.stack(self._samples)
        centroid = embs.mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1.0
        pairs = embs @ embs.T
        agreement = float(pairs[~np.eye(len(embs), dtype=bool)].min())   # the least alike pair of samples
        if agreement < 0.45:
            self._samples, self.enrolling = [], 0
            return ("Those didn't sound like the same voice, maybe someone else spoke or it was noisy. "
                    "Say 'learn my voice' to try again.")
        self.owner = centroid.astype(np.float32)
        self.enrolled_at = time.strftime("%Y-%m-%d %H:%M")
        self._save()
        self._samples = []
        return "Got it. From now on I'll only take commands from your voice. Anyone can still say stop."

    def forget(self) -> str:
        self.owner, self.enrolled_at, self.enrolling = None, "", 0
        try:
            self.store.unlink(missing_ok=True)
        except Exception:
            pass
        return "I've forgotten your voice. I'll take commands from anyone again."

    def set_enabled(self, on: bool) -> str:
        self.enabled = on
        if on and self.owner is None:
            return "Voice ID is on, but I don't know your voice yet. Say 'learn my voice'."
        return "Voice ID is on: I only take commands from you." if on else "Voice ID is off: I take commands from anyone."

    def status(self) -> str:
        if self.enrolling:
            return f"I'm learning your voice: {self.enrolling} more sentence(s)."
        if self.owner is None:
            return "Voice ID isn't set up. Say 'learn my voice' and I'll only take commands from you."
        state = "on" if self.enabled else "off"
        last = f" Last voice I heard scored {self.last_score:.2f}." if self.last_score is not None else ""
        return f"Voice ID is {state}; your voice was saved on {self.enrolled_at}.{last}"
