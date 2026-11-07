"""
Transcript-level wake word gate.

mode "wake_word" (default): voice commands must start with the wake word
("MXB, open chrome" / "hey MXB what's the time"). After a wake word or a reply,
MXB stays engaged for follow_up_seconds so a conversation doesn't need the
wake word every sentence.
mode "always": every recognized utterance is treated as a command (old behaviour —
risky with a TV or other people talking in the room).

Typed chat messages never need the wake word; "stop" never needs it either
(both are handled before this gate by the CommandBus).
"""
import re
import time

DEFAULT_WAKE_WORDS = ["mxb", "m x b", "mx b", "m xb", "emexbee", "max b"]
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "yo", "hai"}


def _norm_token(tok: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tok.lower())


class WakeWordGate:
    def __init__(self, mode: str = "wake_word", wake_words: list[str] | None = None,
                 follow_up_seconds: float = 15.0, clock=time.monotonic):
        self.mode = (mode or "wake_word").lower()
        words = wake_words or DEFAULT_WAKE_WORDS
        # Compare without spaces so "MXB", "M X B", "M.X.B." and "mx-b" all match "mxb".
        self.wake_keys = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in words if w.strip()}
        self.max_tokens = max((len(w.split()) for w in words), default=1) + 2
        self.follow_up_seconds = float(follow_up_seconds)
        self._clock = clock
        self._engaged_until = 0.0

    def engage(self, seconds: float | None = None):
        self._engaged_until = self._clock() + (self.follow_up_seconds if seconds is None else seconds)

    def disengage(self):
        self._engaged_until = 0.0

    @property
    def engaged(self) -> bool:
        return self._clock() < self._engaged_until

    def strip_wake_word(self, text: str) -> tuple[bool, str]:
        """Returns (found, remainder_with_original_case)."""
        tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", text or "")]
        if not tokens:
            return False, ""
        start = 0
        if _norm_token(tokens[0][0]) in GREETINGS:
            start = 1
        for span in range(1, min(self.max_tokens, len(tokens) - start) + 1):
            joined = "".join(_norm_token(t[0]) for t in tokens[start:start + span])
            if joined in self.wake_keys:
                end = tokens[start + span - 1][2]
                rest = (text[end:]).lstrip(" ,.:;!-")
                return True, rest.strip()
        return False, text

    def process(self, text: str) -> str | None:
        """
        Returns the command to run, "" if only the wake word was heard
        (caller should answer "Yes?"), or None if the utterance should be ignored.
        """
        text = (text or "").strip()
        if not text:
            return None
        if self.mode == "always":
            return text
        found, rest = self.strip_wake_word(text)
        if found:
            self.engage()
            return rest
        if self.engaged:
            self.engage()
            return text
        return None
