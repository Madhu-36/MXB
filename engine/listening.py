"""
Listening helpers for quiet microphones and noisy rooms. Pure numpy and regex, no audio devices,
so everything here is unit-tested.

Measured on a real laptop (Realtek mic through the Windows Sound Mapper): speech reached MXB at a
median RMS of 0.004 (about -48 dBFS), where normal speech is 0.03-0.1, and the Silero VAD scored it at
a median of 0.09, so 58 of 60 detections came from the fixed energy threshold instead (RMS > 0.0025),
which also fires on room noise; Whisper then filled the noise with hallucinations. So:

- StreamingVAD: the main bug. faster-whisper >= 1.1 resets the VAD's memory on every call and MXB
  called it once per 32 ms frame. Replaying real speech at that mic level: 9% of speech frames
  detected with the old calls, 98% with the memory kept (faster-whisper 1.2.1, Silero v6).
- InputAGC: automatic gain BEFORE voice detection. It tracks the room's noise floor and the recent
  speech level, raises quiet speech toward the target, never amplifies the noise floor above a
  ceiling, moves smoothly (fast down, slow up) and soft-limits so loud speech can't clip.
- is_speech: speech vs silence relative to the room's own noise floor, not a fixed number.
- clean_transcript: "open notepad, open notepad" becomes one command instead of being thrown away,
  and chanted single words ("go go go go") that Whisper invents from noise are dropped.
- The old Whisper prompt ("Desktop commands: open app, close window...") is gone: on noise Whisper
  repeated it back ("open app, open app, open app"). whisper_options adds optional hint words.
"""
import inspect
import math
import re
from collections import deque

import numpy as np


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20.0))


def gain_to_db(gain: float) -> float:
    return 20.0 * math.log10(max(gain, 1e-9))


class InputAGC:
    """Automatic gain for one mono stream of short frames (MXB uses 512 samples = 32 ms at 16 kHz)."""

    def __init__(self, mode="auto", target_rms: float = 0.1, max_gain_db: float = 30.0, noise_ceiling: float = 0.015,
                 window_s: float = 6.0, frame_s: float = 0.032, limit_rms: float = 0.35):
        mode = "off" if mode in (False, None) else mode
        self.fixed = None
        if isinstance(mode, (int, float)) and not isinstance(mode, bool):
            self.fixed = db_to_gain(float(mode))
            mode = "fixed"
        self.mode = str(mode).lower()
        self.target = float(target_rms)
        self.max_gain = db_to_gain(float(max_gain_db))
        self.noise_ceiling = float(noise_ceiling)
        self.limit = float(limit_rms)     # a frame louder than this after gain cuts the gain at once
        self.history: deque = deque(maxlen=max(10, int(window_s / frame_s)))
        self.noise = 0.0              # raw-input noise floor (RMS)
        self.speech = 0.0             # raw-input recent speech level (RMS of loud frames)
        self.gain = self.fixed or 1.0

    @classmethod
    def from_config(cls, config: dict | None) -> "InputAGC":
        eng = (config or {}).get("engine", {}) or {}
        setting = eng.get("input_gain", "auto")
        if isinstance(setting, str) and setting.strip().lower() not in ("auto", "off", "none", "false"):
            try:
                setting = float(setting.strip().lower().replace("db", ""))
            except ValueError:
                setting = "auto"
        return cls(mode=setting, target_rms=float(eng.get("input_target_rms", 0.1)),
                   max_gain_db=float(eng.get("max_input_gain_db", 30.0)))

    @property
    def gain_db(self) -> float:
        return gain_to_db(self.gain)

    @property
    def noise_after_gain(self) -> float:
        return self.noise * self.gain

    def _desired(self) -> float:
        if self.noise <= 0:
            return self.gain
        if self.speech > self.noise * 3:
            desired = self.target / self.speech
        else:                                      # no speech heard yet: lift the floor to half the ceiling
            desired = (self.noise_ceiling * 0.5) / self.noise
        desired = min(desired, self.noise_ceiling / self.noise, self.max_gain)
        return max(1.0, desired)

    def _observe(self, x: np.ndarray):
        """Updates the noise floor and speech level (raw input) from one frame."""
        self.history.append(float(np.sqrt(np.mean(x * x))))
        hist = np.fromiter(self.history, dtype=np.float32)
        self.noise = max(float(np.percentile(hist, 10)), 1e-5)
        loud = float(np.percentile(hist, 95))
        if loud > self.noise * 3:
            self.speech = loud
        elif self.speech:
            self.speech = max(self.speech * 0.999, self.noise * 3)   # forget slowly in long silences

    def process(self, chunk, adapt: bool = True) -> np.ndarray:
        """
        Returns the frame with gain applied. adapt=False (while MXB itself is talking) applies the
        current gain without learning from the frame, so MXB's own voice can't turn the gain down.
        The noise floor is tracked in every mode, because is_speech() needs it even with gain off.
        """
        x = np.asarray(chunk, dtype=np.float32)
        if not len(x):
            return x
        if adapt:
            self._observe(x)
            if self.mode == "auto":
                desired = self._desired()
                rate = 0.5 if desired < self.gain else 0.05          # fast attack, slow release
                self.gain += rate * (desired - self.gain)
                level = self.history[-1]
                if level * self.gain > self.limit:                    # sudden shout or a door slam
                    self.gain = max(1.0, self.limit / level)
        if self.mode == "off":
            return x
        return np.tanh(x * self.gain).astype(np.float32)             # soft limit: loud speech can't clip


class StreamingVAD:
    """
    Silero VAD that keeps its recurrent state and 64-sample audio context between frames, like
    Silero's own streaming wrapper. Supports faster-whisper >= 1.1 (model.session with h/c inputs)
    and 0.10-1.0 (model(x, state, sr)); anything else is called per frame as before.
    """
    CONTEXT = 64

    def __init__(self, model, sample_rate: int = 16000):
        self.model = model
        self.sample_rate = sample_rate
        self.kind = "stateless"
        session = getattr(model, "session", None)
        try:
            names = {i.name for i in session.get_inputs()} if session is not None else set()
        except Exception:
            names = set()
        if {"input", "h", "c"} <= names:
            self.kind = "session"
        elif callable(getattr(model, "get_initial_state", None)):
            self.kind = "state"
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, self.CONTEXT), dtype=np.float32)
        self.state = self.model.get_initial_state(batch_size=1) if self.kind == "state" else None

    def __call__(self, chunk) -> float:
        x = np.asarray(chunk, dtype=np.float32).reshape(1, -1)
        if self.kind == "session":
            try:
                out, self.h, self.c = self.model.session.run(
                    None, {"input": np.concatenate([self.context, x], axis=1), "h": self.h, "c": self.c})
                self.context = x[:, -self.CONTEXT:]
            except Exception:
                self.kind = "stateless"            # unknown model layout: fall back for good
                out = self.model(x.reshape(-1))
        elif self.kind == "state":
            out, self.state = self.model(x, self.state, self.sample_rate)
        else:
            out = self.model(x.reshape(-1))
        out = np.asarray(out, dtype=np.float32).reshape(-1)
        return float(out[-1]) if out.size else 0.0


def energy_speech_prob(rms: float, noise: float) -> float:
    """Stand-in for the neural VAD when it can't load: 1.0 for frames well above the room's noise floor."""
    return 1.0 if rms >= max(noise * 4.0, 0.002) else 0.0


def is_speech(prob: float, rms: float, noise: float, prob_threshold: float = 0.35) -> bool:
    """
    Voice activity from the VAD probability and the frame's level relative to the noise floor
    (both measured AFTER the gain). A clearly loud frame counts even if the VAD is unsure.
    """
    ratio = rms / max(noise, 1e-6)
    return prob >= prob_threshold or (prob >= 0.15 and ratio >= 3.0) or ratio >= 6.0


_WORD = re.compile(r"[\w']+")
# Said over and over on purpose ("stop, stop, stop!", "no no no"): collapsed, never dropped.
CONTROL_WORDS = {"stop", "no", "yes", "cancel", "wait", "pause", "quit", "exit", "halt", "abort", "enough", "nope",
                 "yeah", "yep", "ok", "okay", "mxb", "help", "undo", "back"}


def clean_transcript(text: str | None) -> str | None:
    """
    Collapses a phrase said twice ("open notepad, open notepad") into one command. Drops Whisper's
    noise loops: one word three or more times ("go, go, go") or any phrase four or more times, except
    control words, which people do repeat ("stop, stop, stop!" still stops MXB).
    """
    if not text:
        return None
    text = text.strip()
    words = _WORD.findall(text.lower())
    if len(text) < 2 or not words:
        return None
    for skip in range(0, min(2, len(words) - 2) + 1):          # "MXB, open notepad, open notepad" too
        rest = words[skip:]
        for n in range(1, min(4, len(rest) // 2) + 1):
            unit = rest[:n]
            reps = len(rest) // n
            if reps >= 2 and rest[:reps * n] == unit * reps and rest[reps * n:] == unit[:len(rest) - reps * n]:
                if (reps >= 4 or (n == 1 and reps >= 3)) and not CONTROL_WORDS & set(unit):
                    return None                     # a loop Whisper invented from noise, not a command
                return " ".join(words[:skip] + unit)
    return text


def max_tokens_for(seconds: float) -> int:
    """Enough tokens for fast speech of this length (~4 words/s), so noise can't run on for 448."""
    return int(min(224, 24 + 8 * max(0.0, seconds)))


def whisper_options(model, hotwords: str = "", max_new_tokens: int | None = None) -> dict:
    """
    Extra transcribe() arguments the installed faster-whisper supports:
    - max_new_tokens / without_timestamps: on a real laptop one 10 s stretch of background talk took
      77 s to decode, because Whisper ran on to its 448-token limit. Commands are short.
    - hotwords: off by default. Hint words work like a prompt, and Whisper repeats prompts back on noise
      (the old "open app, close window..." prompt did exactly that), so a hint of "MXB" could fire the
      wake word on its own. Opt in with engine.whisper_hotwords (faster-whisper >= 1.0).
    """
    try:
        params = inspect.signature(getattr(model, "transcribe")).parameters
    except (AttributeError, TypeError, ValueError):
        return {}
    out = {}
    if hotwords and "hotwords" in params:
        out["hotwords"] = hotwords
    if max_new_tokens and "max_new_tokens" in params:
        out["max_new_tokens"] = int(max_new_tokens)
    if "without_timestamps" in params:
        out["without_timestamps"] = True
    return out
