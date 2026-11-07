"""
Speak-while-thinking: extracts the "reply" field from a JSON plan WHILE it streams
and hands complete sentences to TTS immediately.

The planner prompt puts "reply" first, so with streaming MXB starts talking after
the first sentence (~0.5-1 s) instead of after the whole plan is generated.
If the model answers in plain text instead of JSON, the whole stream is the reply.
"""
import re

_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
_KEY = re.compile(r'"reply"\s*:\s*"$')
_ESCAPES = {"n": " ", "t": " ", "r": "", '"': '"', "\\": "\\", "/": "/", "b": "", "f": ""}


class ReplyStreamer:
    def __init__(self, on_sentence, min_chars: int = 18):
        self.on_sentence = on_sentence
        self.min_chars = min_chars
        self.raw = ""
        self.mode = None            # "json" | "text"
        self.in_reply = False
        self.reply_done = False
        self._escape = False
        self._unicode = None        # pending \\uXXXX digits
        self.reply = ""
        self._emitted = 0
        self.sentences: list[str] = []

    @property
    def spoke(self) -> bool:
        return bool(self.sentences)

    def feed(self, delta: str):
        for ch in delta or "":
            self.raw += ch
            if self.mode is None:
                if ch.isspace():
                    continue
                self.mode = "json" if ch in "{[`" else "text"
                if self.mode == "text":
                    self.in_reply = True
            if self.mode == "text":
                self._add(ch)
                continue
            if self.reply_done:
                continue
            if not self.in_reply:
                if ch == '"' and _KEY.search(self.raw[-48:]):
                    self.in_reply = True
                continue
            self._consume_reply_char(ch)

    def _consume_reply_char(self, ch: str):
        if self._unicode is not None:
            self._unicode += ch
            if len(self._unicode) == 4:
                try:
                    self._add(chr(int(self._unicode, 16)))
                except ValueError:
                    pass
                self._unicode = None
            return
        if self._escape:
            self._escape = False
            if ch == "u":
                self._unicode = ""
            else:
                self._add(_ESCAPES.get(ch, ch))
            return
        if ch == "\\":
            self._escape = True
        elif ch == '"':
            self.in_reply = False
            self.reply_done = True
            self.flush()
        else:
            self._add(ch)

    def _add(self, ch: str):
        self.reply += ch
        if ch in ".!?…\n" or ch.isspace():
            self._emit_complete()

    def _emit_complete(self):
        pending = self.reply[self._emitted:]
        last_end = None
        for m in _SENTENCE_END.finditer(pending):
            if m.end() >= self.min_chars or last_end is not None:
                last_end = m.end()
        # Only emit when the boundary is followed by whitespace (sentence really ended).
        if last_end is not None and last_end < len(pending) and pending[last_end].isspace():
            chunk = pending[:last_end].strip()
            if len(chunk) >= self.min_chars or self.sentences:
                self._speak(chunk)
                self._emitted += last_end

    def flush(self):
        rest = self.reply[self._emitted:].strip()
        if rest:
            self._speak(rest)
        self._emitted = len(self.reply)

    def finish(self):
        """Call after the stream ends."""
        self.flush()

    def _speak(self, text: str):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        self.sentences.append(text)
        try:
            self.on_sentence(text)
        except Exception:
            pass
