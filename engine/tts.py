"""
MXB speech output.

Backends (config voice.tts_engine):
- "edge"  : Microsoft Edge neural voices via edge-tts (online, very natural; e.g. en-IN-NeerjaNeural,
            en-IN-PrabhatNeural, en-US-AriaNeural). Decoded with miniaudio, played with sounddevice.
- "piper" : Piper neural TTS, fully offline (voice.piper_exe + voice.piper_model .onnx).
- "sapi"  : Windows built-in voices (always available).
- "auto"  : edge if installed, else piper if configured, else sapi. Falls back to sapi
            for the rest of the session if a neural backend errors.

All playback is interruptible ("stop", barge-in): audio is written in ~40 ms chunks and
the interrupt flag is checked between chunks. While one sentence plays, the next queued
sentence is synthesized in the background so streamed replies have no gaps.
"""
import json
import queue
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2


RATE_MIN, RATE_MAX = -50, 100      # percent slower/faster than normal


def clamp_rate(percent) -> int:
    try:
        return max(RATE_MIN, min(RATE_MAX, int(round(float(percent)))))
    except (TypeError, ValueError):
        return 0


def initial_rate(cfg: dict) -> int:
    """voice.rate_percent if set, else the edge_rate string ("+5%")."""
    if cfg.get("rate_percent") is not None:
        return clamp_rate(cfg["rate_percent"])
    try:
        return clamp_rate(str(cfg.get("edge_rate", "+0%")).strip().rstrip("%"))
    except Exception:
        return 0


def sapi_rate(percent: int) -> int:
    """SAPI Rate runs -10..10, where 10 is 3x normal speed and -10 a third of it."""
    import math
    return max(-10, min(10, round(10 * math.log(1 + clamp_rate(percent) / 100) / math.log(3))))


def piper_length_scale(percent: int) -> float:
    """Piper speaks faster with a smaller length scale."""
    return round(1 / (1 + clamp_rate(percent) / 100), 3)


def _load_voice_config() -> dict:
    try:
        from utils.paths import load_config
        return load_config().get("voice", {}) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class SapiBackend:
    name = "sapi"
    synthesizes_audio = False

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.speaker = None

    def start(self):
        """Must run on the TTS thread (SAPI COM objects are apartment-bound)."""
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        self.speaker = win32com.client.Dispatch("SAPI.SpVoice")
        wanted = (self.cfg.get("sapi_voice") or "").lower()
        for v in self.speaker.GetVoices():
            desc = v.GetDescription()
            if (wanted and wanted in desc.lower()) or (not wanted and ("Zira" in desc or "Hazel" in desc or "Female" in desc)):
                self.speaker.Voice = v
                break
        self.speaker.Rate = int(self.cfg.get("sapi_rate", 1))

    def set_rate(self, percent: int):
        if self.speaker is not None:
            self.speaker.Rate = sapi_rate(percent)

    def speak(self, text: str, interrupt: threading.Event):
        self.speaker.Speak(text, SVSF_ASYNC)
        while not self.speaker.WaitUntilDone(50):
            if interrupt.is_set():
                self.speaker.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                break

    def stop(self):
        try:
            if self.speaker:
                self.speaker.Speak("", SVSF_PURGE_BEFORE_SPEAK)
        except Exception:
            pass
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass


class _PcmBackend:
    """Shared playback for backends that synthesize PCM audio."""
    synthesizes_audio = True

    def start(self):
        pass

    def stop(self):
        pass

    @staticmethod
    def play(samples: np.ndarray, sample_rate: int, interrupt: threading.Event):
        import sounddevice as sd
        if samples is None or len(samples) == 0:
            return
        block = max(256, int(sample_rate * 0.04))
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
            for i in range(0, len(samples), block):
                if interrupt.is_set():
                    break
                stream.write(samples[i:i + block].reshape(-1, 1))


class EdgeBackend(_PcmBackend):
    name = "edge"
    SAMPLE_RATE = 24000

    def __init__(self, cfg: dict):
        import edge_tts  # noqa: F401  (fail fast if missing)
        try:
            import miniaudio  # noqa: F401
        except Exception:
            pass
        self.voice = cfg.get("edge_voice", "en-IN-NeerjaNeural")
        self.rate = cfg.get("edge_rate", "+5%")
        self.gender = cfg.get("indic_voice_gender", "female")
        self.devanagari = "mr" if (cfg.get("language") or "").lower() == "mr" else "hi"

    def set_rate(self, percent: int):
        self.rate = f"{clamp_rate(percent):+d}%"

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        import asyncio
        import edge_tts
        from engine.indic import voice_for
        voice = voice_for(text, self.voice, self.gender, self.devanagari)   # Kannada text -> Kannada voice

        async def _collect() -> bytes:
            chunks = []
            async for chunk in edge_tts.Communicate(text, voice, rate=self.rate).stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        mp3 = asyncio.run(_collect())
        if not mp3:
            raise RuntimeError("edge-tts returned no audio")
        try:
            import miniaudio
            decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                       sample_rate=self.SAMPLE_RATE)
            return np.frombuffer(decoded.samples, dtype=np.int16), self.SAMPLE_RATE
        except Exception:
            samples = int(self.SAMPLE_RATE * max(0.2, len(text) * 0.05))
            return np.zeros(samples, dtype=np.int16), self.SAMPLE_RATE


class PiperBackend(_PcmBackend):
    name = "piper"

    def __init__(self, cfg: dict):
        self.exe = cfg.get("piper_exe") or "piper"
        self.model = cfg.get("piper_model")
        if not self.model or not Path(self.model).exists():
            raise RuntimeError("voice.piper_model must point to a Piper .onnx voice")
        meta = Path(str(self.model) + ".json")
        self.sample_rate = 22050
        self.length_scale = None
        try:
            self.sample_rate = int(json.loads(meta.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except Exception:
            pass

    def set_rate(self, percent: int):
        self.length_scale = piper_length_scale(percent) if clamp_rate(percent) else None

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        kwargs = {"input": text.encode("utf-8"), "capture_output": True, "timeout": 30}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        cmd = [self.exe, "--model", str(self.model), "--output_raw"]
        if self.length_scale:
            cmd += ["--length_scale", str(self.length_scale)]
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"piper failed: {proc.stderr[:200]!r}")
        return np.frombuffer(proc.stdout, dtype=np.int16), self.sample_rate


def choose_backend(cfg: dict):
    """Returns the best available backend instance for the config (pure selection logic)."""
    engine = (cfg.get("tts_engine") or "auto").lower()
    order = {"edge": ["edge", "sapi"], "piper": ["piper", "sapi"], "sapi": ["sapi"],
             "auto": ["edge", "piper", "sapi"]}.get(engine, ["sapi"])
    classes = {"edge": EdgeBackend, "piper": PiperBackend, "sapi": SapiBackend}
    for name in order:
        try:
            return classes[name](cfg)
        except Exception:
            continue
    return SapiBackend(cfg)


# ---------------------------------------------------------------------------
# Speech thread
# ---------------------------------------------------------------------------
class TTSThread(QThread):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self, cfg: dict | None = None):
        super().__init__()
        self.cfg = cfg if cfg is not None else _load_voice_config()
        self.text_queue = queue.Queue()
        self.is_running = True
        self._is_speaking = False
        self._interrupt = threading.Event()
        self.backend = None
        self.current_text = ""
        self.recent_spoken: deque = deque(maxlen=8)   # (time, text) for barge-in echo filtering
        self._prefetch_pool = ThreadPoolExecutor(max_workers=1)
        self._prefetched: dict[str, object] = {}
        self._edge_for_indic = None   # lazily created for Indian-language sentences when SAPI/Piper is active
        self._rate = initial_rate(self.cfg)
        self._rate_explicit = self.cfg.get("rate_percent") is not None   # else SAPI keeps voice.sapi_rate
        self._rate_dirty = self._rate_explicit

    @property
    def rate_percent(self) -> int:
        return self._rate

    def set_rate(self, percent) -> int:
        """Applied by the TTS thread before the next sentence (SAPI objects belong to that thread)."""
        self._rate = clamp_rate(percent)
        self._rate_explicit = True
        self._rate_dirty = True
        return self._rate

    def _apply_rate(self):
        self._rate_dirty = False
        self._prefetched.clear()                      # audio made at the old speed
        for backend in (self.backend, self._edge_for_indic or None):
            fn = getattr(backend, "set_rate", None)
            if callable(fn):
                try:
                    fn(self._rate)
                except Exception as e:
                    print(f"[TTS] couldn't change the speaking rate: {e}")

    def enqueue(self, text: str):
        if text and text.strip() and self.is_running:
            self.text_queue.put(text.strip())

    def _drain(self):
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        self._prefetched.clear()

    def interrupt(self):
        """Stops the current sentence and drops queued speech, keeping the thread alive."""
        self._drain()
        self._interrupt.set()

    def stop(self):
        self.is_running = False
        self._drain()
        self._interrupt.set()
        self.text_queue.put(None)
        self.wait(1500)

    def _fallback_to_sapi(self, error):
        print(f"[TTS] {getattr(self.backend, 'name', '?')} failed ({error}); switching to Windows voices.")
        self.backend = SapiBackend(self.cfg)
        self.backend.start()
        self._rate_dirty = self._rate_dirty or self._rate_explicit

    def _synth_future(self, text: str):
        if text not in self._prefetched:
            self._prefetched[text] = self._prefetch_pool.submit(self.backend.synth, text)
        return self._prefetched.pop(text)

    def _prefetch_next(self):
        try:
            nxt = self.text_queue.queue[0] if self.text_queue.queue else None
        except Exception:
            nxt = None
        if nxt and nxt not in self._prefetched and getattr(self.backend, "synthesizes_audio", False):
            self._prefetched[nxt] = self._prefetch_pool.submit(self.backend.synth, nxt)

    def _indic_backend(self, text: str):
        """Windows/Piper voices can't read Indian scripts: use the edge neural voice for those sentences."""
        if getattr(self.backend, "name", "") == "edge":
            return None
        from engine.indic import script_language
        if not script_language(text):
            return None
        if getattr(self, "_edge_for_indic", None) is None:
            try:
                self._edge_for_indic = EdgeBackend(self.cfg)
                self._edge_for_indic.set_rate(self._rate)
            except Exception as e:
                print(f"[TTS] No voice for Indian languages ({e}); showing the reply as text only.")
                self._edge_for_indic = False
        return self._edge_for_indic or None

    def _speak_one(self, text: str):
        indic = self._indic_backend(text)
        if indic is not None:
            try:
                samples, rate = indic.synth(text)
                indic.play(samples, rate, self._interrupt)
            except Exception as e:
                print(f"[TTS] Indian-language voice failed ({e}); the reply stays on screen.")
            return
        if getattr(self.backend, "synthesizes_audio", False):
            try:
                samples, rate = self._synth_future(text).result(timeout=30)
            except Exception as e:
                self._fallback_to_sapi(e)
                self.backend.speak(text, self._interrupt)
                return
            self._prefetch_next()
            self.backend.play(samples, rate, self._interrupt)
        else:
            self.backend.speak(text, self._interrupt)

    def run(self):
        try:
            self.backend = choose_backend(self.cfg)
            self.backend.start()
            print(f"[TTS] Using {self.backend.name} voice backend.")
        except Exception as e:
            print(f"[TTS Init Error] {e}")
            try:
                self.backend = SapiBackend(self.cfg)
                self.backend.start()
            except Exception as e2:
                print(f"[TTS] No speech backend available: {e2}")
                self.backend = None

        while self.is_running:
            try:
                text = self.text_queue.get(timeout=0.1)
                if text is None or not self.is_running:
                    break
                self._interrupt.clear()
                self._is_speaking = True
                self.current_text = text
                self.recent_spoken.append((time.time(), text))
                self.started_speaking.emit()
                print(f"[MXB Voice] {text}")
                if self.backend is not None:
                    try:
                        if self._rate_dirty:
                            self._apply_rate()
                        self._speak_one(text)
                    except Exception as spk_err:
                        print(f"[TTS Speak Error] {spk_err}")
                if self.text_queue.empty():
                    self._is_speaking = False
                    self.current_text = ""
                    self.finished_speaking.emit()
            except queue.Empty:
                if self._is_speaking and self.text_queue.empty():
                    self._is_speaking = False
                    self.current_text = ""
                    self.finished_speaking.emit()
            except Exception as loop_err:
                print(f"[TTS Loop Error] {loop_err}")
                self._is_speaking = False
                self.finished_speaking.emit()

        self._is_speaking = False
        if self.backend is not None:
            self.backend.stop()
        self._prefetch_pool.shutdown(wait=False)


class VoiceSynthesizer(QObject):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self, cfg: dict | None = None):
        super().__init__()
        self._thread = TTSThread(cfg)
        self._thread.started_speaking.connect(self.started_speaking.emit)
        self._thread.finished_speaking.connect(self.finished_speaking.emit)
        self._thread.start()

    @property
    def is_speaking(self) -> bool:
        return self._thread._is_speaking

    @property
    def current_text(self) -> str:
        return self._thread.current_text

    def recent_spoken(self, within_seconds: float = 20.0) -> list[str]:
        now = time.time()
        return [t for ts, t in list(self._thread.recent_spoken) if now - ts <= within_seconds]

    def speak(self, text: str, wait=False):
        """Asynchronously enqueues text; emits started/finished_speaking signals."""
        if not text or not text.strip():
            return
        self._thread.enqueue(text)
        if wait:
            while self._thread._is_speaking or not self._thread.text_queue.empty():
                time.sleep(0.05)

    def interrupt(self):
        """Cut off current speech immediately ("stop", barge-in, kill switch)."""
        self._thread.interrupt()

    @property
    def rate_percent(self) -> int:
        return self._thread.rate_percent

    def set_rate(self, percent) -> int:
        return self._thread.set_rate(percent)

    def stop(self):
        self._thread.stop()


class ModalityTTS:
    """
    Wraps a VoiceSynthesizer so each worker thread decides whether replies are
    spoken: voice commands get spoken + written replies, typed/phone commands get
    written replies only (unless voice.speak_text_replies is true).
    All other attributes (signals, stop, interrupt) pass straight through.
    """

    def __init__(self, inner):
        self._inner = inner
        self._local = threading.local()

    @property
    def inner(self):
        return self._inner

    def set_thread_speaking(self, enabled: bool):
        self._local.enabled = bool(enabled)

    def speaking_enabled(self) -> bool:
        return getattr(self._local, "enabled", True)

    def set_thread_language(self, code: str | None, translator=None):
        """Replies on this worker thread are spoken in `code` (English text is translated first)."""
        self._local.language = code
        self._local.translator = translator

    def localize(self, text: str) -> str:
        code = getattr(self._local, "language", None)
        translate = getattr(self._local, "translator", None)
        if not code or not translate or not text:
            return text
        from engine.indic import script_language
        if script_language(text):
            return text
        try:
            return translate(text, code) or text
        except Exception:
            return text

    def speak(self, text: str, wait=False):
        if self.speaking_enabled():
            self._inner.speak(self.localize(text), wait=wait)

    def speak_always(self, text: str, wait=False):
        self._inner.speak(self.localize(text), wait=wait)

    def interrupt(self):
        fn = getattr(self._inner, "interrupt", None)
        if callable(fn):
            fn()

    def __getattr__(self, name):
        return getattr(self._inner, name)
