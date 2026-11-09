"""
Barge-in: talk over MXB to interrupt it, like a person.

Problem: on laptop speakers the microphone also hears MXB's own voice (echo).
Policy (config voice.barge_in):
- "headset": no echo possible -> interrupt TTS as soon as ~0.3 s of confident speech is heard.
- "speaker": wait for the transcript; drop it if it matches what MXB was just saying
             (echo), otherwise interrupt TTS and treat it as a command.
- "auto"   : "headset" when the input device looks like a headset/earbuds, else "speaker".
- "off"    : ignore the microphone while MXB speaks (v3 behaviour).
"""
import re
from rapidfuzz import fuzz

HEADSET_HINTS = ("headset", "headphone", "earphone", "earbud", "buds", "airpods", "airdopes", "hands-free",
                 "handsfree", "bluetooth", "noise", "neckband", "jabra", "plantronics", "poly ", "hyperx")


def resolve_mode(setting: str, input_device_name: str = "") -> str:
    s = (setting or "auto").lower()
    if s in {"off", "headset", "speaker"}:
        return s
    name = (input_device_name or "").lower()
    return "headset" if any(h in name for h in HEADSET_HINTS) else "speaker"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", (text or "").lower())).strip()


def is_probable_echo(transcript: str, spoken_recently: list[str], threshold: int = 78) -> bool:
    """True if the transcript is (part of) something MXB itself just said."""
    t = _norm(transcript)
    if not t:
        return True
    words = t.split()
    for spoken in spoken_recently:
        s = _norm(spoken)
        if not s:
            continue
        if t in s:
            return True
        if len(words) >= 3 and fuzz.partial_ratio(t, s) >= threshold:
            return True
        if len(words) >= 4:
            overlap = len(set(words) & set(s.split())) / max(1, len(set(words)))
            if overlap >= 0.8:
                return True
    return False


class BargeInDetector:
    """Frame-level detector used while TTS is playing (stricter than normal VAD)."""

    def __init__(self, prob_threshold: float = 0.8, min_frames: int = 10, rms_floor: float = 0.004):
        self.prob_threshold = prob_threshold
        self.min_frames = min_frames      # 10 x 32 ms = 320 ms of confident speech
        self.rms_floor = rms_floor
        self._run = 0

    def reset(self):
        self._run = 0

    def update(self, speech_prob: float, rms: float) -> bool:
        """Feed one 32 ms frame; returns True once sustained user speech is detected."""
        if speech_prob >= self.prob_threshold and rms >= self.rms_floor:
            self._run += 1
        else:
            self._run = 0
        return self._run >= self.min_frames
