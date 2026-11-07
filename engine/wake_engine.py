"""
Offline audio wake-word engine (openWakeWord).

With listening.engine = "openwakeword", the wake word is detected directly in the
audio stream on the CPU: nothing is transcribed (or sent to any cloud ASR) until
the wake word is heard, which saves cost and keeps room audio private.

Pretrained models: "hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy"; custom
models (e.g. a trained "hey_mxb.onnx") can be given as a file path.
Install: pip install openwakeword
"""
import time
from pathlib import Path
import numpy as np
from utils.logger import log

FRAME = 1280  # 80 ms at 16 kHz — openWakeWord's native chunk size


def wake_phrase_words(model_name: str) -> list[str]:
    """Words to strip from transcripts for a model, e.g. 'hey_jarvis' -> ['jarvis']."""
    stem = Path(model_name).stem.lower()
    stem = stem.split("_v")[0]
    words = [w for w in stem.replace("-", "_").split("_") if w and w not in {"hey", "ok", "hi"}]
    return [" ".join(words)] if words else []


class OpenWakeWordEngine:
    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5, cooldown: float = 1.5):
        self.model_name = model_name
        self.threshold = float(threshold)
        self.cooldown = float(cooldown)
        self._buffer = np.zeros(0, dtype=np.int16)
        self._last_hit = 0.0
        self.model = None

    def load(self) -> bool:
        try:
            import openwakeword
            from openwakeword.model import Model
            if not Path(self.model_name).exists():
                try:
                    openwakeword.utils.download_models(model_names=[self.model_name])
                except TypeError:
                    openwakeword.utils.download_models()
                except Exception as e:
                    log.warning(f"WakeEngine: model download skipped: {e}")
            self.model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
            log.info(f"WakeEngine: openWakeWord '{self.model_name}' loaded (threshold {self.threshold}).")
            return True
        except Exception as e:
            log.warning(f"WakeEngine: openWakeWord unavailable ({e}); using transcript wake words instead.")
            self.model = None
            return False

    def process(self, chunk_float32: np.ndarray) -> bool:
        """Feed 16 kHz float32 audio of any length; returns True when the wake word fires."""
        if self.model is None:
            return False
        pcm = (np.clip(chunk_float32, -1.0, 1.0) * 32767).astype(np.int16)
        self._buffer = np.concatenate([self._buffer, pcm])
        fired = False
        while len(self._buffer) >= FRAME:
            frame, self._buffer = self._buffer[:FRAME], self._buffer[FRAME:]
            scores = self.model.predict(frame)
            score = max(scores.values()) if scores else 0.0
            now = time.time()
            if score >= self.threshold and now - self._last_hit > self.cooldown:
                self._last_hit = now
                fired = True
                log.info(f"WakeEngine: wake word detected (score {score:.2f}).")
        return fired
