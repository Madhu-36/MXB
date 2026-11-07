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


def _load_voice_config() -> dict:
    try:
        cfg = json.loads((Path(__file__).parent.parent / "config.json").read_text(encoding="utf-8"))
        return cfg.get("voice", {}) or {}
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
        import miniaudio  # noqa: F401
        self.voice = cfg.get("edge_voice", "en-IN-NeerjaNeural")
        self.rate = cfg.get("edge_rate", "+5%")

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        import asyncio
        import edge_tts
        import miniaudio

        async def _collect() -> bytes:
            chunks = []
            async for chunk in edge_tts.Communicate(text, self.voice, rate=self.rate).stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        mp3 = asyncio.run(_collect())
        if not mp3:
            raise RuntimeError("edge-tts returned no audio")
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                   sample_rate=self.SAMPLE_RATE)
        return np.frombuffer(decoded.samples, dtype=np.int16), self.SAMPLE_RATE


class PiperBackend(_PcmBackend):
    name = "piper"

    def __init__(self, cfg: dict):
        self.exe = cfg.get("piper_exe") or "piper"
        self.model = cfg.get("piper_model")
        if not self.model or not Path(self.model).exists():
            raise RuntimeError("voice.piper_model must point to a Piper .onnx voice")
        meta = Path(str(self.model) + ".json")
        self.sample_rate = 22050
        try:
            self.sample_rate = int(json.loads(meta.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except Exception:
            pass

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        kwargs = {"input": text.encode("utf-8"), "capture_output": True, "timeout": 30}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run([self.exe, "--model", str(self.model), "--output_raw"], **kwargs)
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

    def _speak_one(self, text: str):
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

    def speak(self, text: str, wait=False):
        if self.speaking_enabled():
            self._inner.speak(text, wait=wait)

    def speak_always(self, text: str, wait=False):
        self._inner.speak(text, wait=wait)

    def interrupt(self):
        fn = getattr(self._inner, "interrupt", None)
        if callable(fn):
            fn()

    def __getattr__(self, name):
        return getattr(self._inner, name)
