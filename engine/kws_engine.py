"""
"MXB" heard in the audio itself (listening.engine = "kws").

An open-vocabulary keyword spotter (sherpa-onnx zipformer, GigaSpeech, 3.3M parameters, int8, CPU):
the wake word is a list of sub-word tokens, so "MXB" needs no training, unlike openWakeWord, whose
stock models are "hey jarvis" and friends. Until the keyword fires nothing is transcribed, which
keeps room audio private and Whisper idle.

Measured with Kokoro voices (8 voices incl. two Hindi-accented, 32 wake phrases such as "Ahh, MXB,
open the calculator"): 30/32 detected, 0/48 false alarms on look-alikes ("MP3 player", "Xbox",
"next bus", "inbox"), and 0 false wakes in 1.8 minutes of speech without the word.
"""
import time

import numpy as np

from utils.logger import log

# Token sequences for the default phrases (from the model's bpe.model), so the common case needs no
# sentencepiece at runtime. Custom phrases are encoded with sentencepiece when it is installed.
DEFAULT_KEYWORDS = {
    "M X B": ["▁", "M", "▁", "X", "▁B"],
    "HEY M X B": ["▁HE", "Y", "▁", "M", "▁", "X", "▁B"],
    "EM EX BEE": ["▁E", "M", "▁EX", "▁BE", "E"],
}


def keyword_lines(phrases: dict, boost: float, threshold: float) -> str:
    return "\n".join(f"{' '.join(tokens)} :{boost} #{threshold} @{name.replace(' ', '_')}"
                     for name, tokens in phrases.items()) + "\n"


def encode_phrases(words: list[str], bpe_model) -> dict:
    """Wake words from config ("jarvis", "hey mxb") as model tokens; MXB variants use the shipped tokens."""
    out = {}
    for w in words:
        key = w.upper().strip()
        compact = key.replace(" ", "")
        if compact in ("MXB", "HEYMXB"):
            out.update({k: v for k, v in DEFAULT_KEYWORDS.items() if ("HEY" in k) == compact.startswith("HEY")})
            continue
        try:
            import sentencepiece as spm
            sp = spm.SentencePieceProcessor(model_file=str(bpe_model))
            out[key] = sp.encode(key, out_type=str)
        except Exception as e:
            log.warning(f"KWS: can't encode wake word {w!r} without sentencepiece ({e}); skipping it.")
    return out or dict(DEFAULT_KEYWORDS)


class SherpaKWSEngine:
    """Same interface as OpenWakeWordEngine: load() then process(chunk) -> True when the keyword fires."""

    def __init__(self, wake_words=None, threshold: float = 0.2, boost: float = 1.5, cooldown: float = 1.5):
        self.wake_words = list(wake_words or ["mxb", "hey mxb"])
        self.threshold = float(threshold)
        self.boost = float(boost)
        self.cooldown = float(cooldown)
        self._last_hit = 0.0
        self.spotter = None
        self.stream = None

    def load(self) -> bool:
        try:
            import sherpa_onnx
            from utils.fetch_models import MODELS, fetch
            folder = fetch("kws", progress=lambda m: log.info(f"KWS: {m}"))
            enc, dec, join, tokens, bpe = (folder / f for f in MODELS["kws"]["files"])
            phrases = encode_phrases(self.wake_words, bpe)
            kw_file = folder / "mxb_keywords.txt"
            kw_file.write_text(keyword_lines(phrases, self.boost, self.threshold), encoding="utf-8")
            self.spotter = sherpa_onnx.KeywordSpotter(
                tokens=str(tokens), encoder=str(enc), decoder=str(dec), joiner=str(join),
                keywords_file=str(kw_file), num_threads=1, max_active_paths=4,
                keywords_score=self.boost, keywords_threshold=self.threshold)
            self.stream = self.spotter.create_stream()
            log.info(f"KWS: listening for {', '.join(phrases)} (threshold {self.threshold}).")
            return True
        except Exception as e:
            log.warning(f"KWS: keyword spotter unavailable ({e}); using transcript wake words instead.")
            self.spotter = None
            return False

    def process(self, chunk_float32: np.ndarray) -> bool:
        if self.spotter is None:
            return False
        self.stream.accept_waveform(16000, np.asarray(chunk_float32, dtype=np.float32))
        fired = False
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            hit = self.spotter.get_result(self.stream)
            if hit:
                self.spotter.reset_stream(self.stream)
                now = time.time()
                if now - self._last_hit > self.cooldown:
                    self._last_hit = now
                    fired = True
                    log.info(f"KWS: wake word detected ({hit}).")
        return fired
