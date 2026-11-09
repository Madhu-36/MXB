"""
Runs MXB's real microphone loop (input gain, Silero voice detection, silence timer, Smart Turn
handling) on a real speech clip, with a fake microphone stream, a fake Whisper and a scripted Smart
Turn, and prints what the command bus received as JSON. tests/test_v44_turn.py runs it in a child
process, because engine.audio needs a sounddevice stand-in on machines without PortAudio.

    python -m tests._mic_loop
"""
import json
import os
import sys
import tempfile
import threading
import types
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MXB_DATA_DIR", tempfile.mkdtemp(prefix="mxb-mic-loop-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RATE, FRAME = 16000, 512


class _FakeStream:
    opened = threading.Event()

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        _FakeStream.opened.set()
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


try:
    import sounddevice  # noqa: F401
except Exception:                                   # no PortAudio (Linux CI): the stream is fake anyway
    sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=_FakeStream, query_devices=lambda *a, **k: [])

import tests._stubs  # noqa: E402,F401
import engine.audio as audio_mod  # noqa: E402
import scripts.listening_bench as lb  # noqa: E402
from engine.turn_detector import TurnDetector  # noqa: E402


class _Segment:
    def __init__(self, text):
        self.text, self.no_speech_prob, self.avg_logprob = text, 0.0, -0.2


class FakeWhisper:
    calls: list = []

    def __init__(self, *a, **k):
        self.model = types.SimpleNamespace(is_multilingual=False)

    def transcribe(self, audio, **k):
        FakeWhisper.calls.append(round(len(audio) / RATE, 2))
        info = types.SimpleNamespace(language="en", all_language_probs=None)
        return [_Segment(f"utterance {len(FakeWhisper.calls)}")], info


class ScriptedSession:
    """Smart Turn stand-in: returns the given probabilities in order (the last one repeats)."""

    def __init__(self, probabilities):
        self.probabilities, self.calls = list(probabilities), 0

    def run(self, outputs, feeds):
        p = self.probabilities[min(self.calls, len(self.probabilities) - 1)]
        self.calls += 1
        return [np.array([[p]], dtype=np.float32)]


def speech_parts():
    """The public-domain test clip: "And so my fellow Americans" ... ~1 s pause ... "ask not"."""
    with wave.open(str(ROOT / "tests" / "data" / "speech_jfk_4s.wav"), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return x[: 72 * FRAME], x[101 * FRAME: 120 * FRAME]


def run(scenarios):
    audio_mod.WhisperModel = FakeWhisper
    audio_mod.sd = types.SimpleNamespace(InputStream=_FakeStream, query_devices=lambda *a, **k: [])
    try:
        from PySide6.QtCore import QCoreApplication
        _app = QCoreApplication.instance() or QCoreApplication([])  # noqa: F841
    except Exception:
        pass
    a, b = speech_parts()
    rng = np.random.default_rng(0)

    def quiet(seconds):
        return rng.normal(0, 0.001, int(seconds * RATE) // FRAME * FRAME).astype(np.float32)

    results = {}
    for name, (pause, probabilities) in scenarios.items():
        config = {"engine": {"input_gain": "auto"}, "listening": {"wake_words": ["mxb"]},
                  "turn_detection": {"enabled": probabilities is not None}}
        bus = lb._Bus(config)
        pipe = audio_mod.VoicePipeline(config, bus=bus)
        session = ScriptedSession(probabilities) if probabilities is not None else None
        pipe.turn = TurnDetector(config, session=session)
        pipe._resolve_audio_device = lambda: (None, {"name": "test (no microphone)"}, RATE)
        _FakeStream.opened.clear()
        FakeWhisper.calls = []
        worker = threading.Thread(target=pipe.run, daemon=True)
        worker.start()
        if not _FakeStream.opened.wait(120):
            results[name] = {"error": "pipeline did not start"}
            continue
        lb.feed(pipe, quiet(3.0), speed=16.0)        # the gain settles on the room first
        lb.wait_idle(pipe, timeout=30)
        speech = [a] if pause is None else [a, np.zeros(int(pause * RATE) // FRAME * FRAME, np.float32), b]
        clip = np.concatenate(speech) * 0.3
        lb.feed(pipe, np.concatenate([quiet(0.5), clip + quiet(len(clip) / RATE), quiet(2.5)]), speed=16.0)
        lb.wait_idle(pipe, timeout=30)
        pipe.is_running = False
        try:
            pipe.utterance_queue.put_nowait(None)
        except Exception:
            pass
        worker.join(timeout=5)
        results[name] = {"submitted": [t for _, t in bus.heard], "transcribed_seconds": list(FakeWhisper.calls),
                         "turn_calls": session.calls if session else 0, "end_of_turn": list(pipe.last_end_of_turn)}
    return results


SCENARIOS = {
    "finished": (None, [0.9]),
    "short_pause_sounds_finished": (0.35, [0.9]),
    "long_pause_unfinished": (0.9, [0.1, 0.9]),
    "long_pause_no_model": (0.9, None),
}

if __name__ == "__main__":
    print("MIC-LOOP-RESULTS " + json.dumps(run(SCENARIOS)))
