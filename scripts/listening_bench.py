"""
Listening bench: plays voice commands through MXB's real voice pipeline (input gain, voice
detection, Whisper, transcript cleanup) and scores them with the wake-word gate, with no
microphone in the loop, so a listening fix can be measured on the PC that has the problem.

Speech comes from Windows' built-in voice (or your own --wav recordings), scaled to the level a
quiet laptop mic delivers, mixed with a few seconds of real room noise recorded from your
microphone. The first segment is room noise only: anything "heard" there is a false trigger.

    python -m scripts.listening_bench                  # quiet-mic level (speech RMS 0.004, as measured)
    python -m scripts.listening_bench --gain off       # the same without the input gain
    python -m scripts.listening_bench --level 0.02     # a normal-loudness mic
    python -m scripts.listening_bench --wav a.wav b.wav --expect "open notepad" "open chrome"

Each command is followed by a second of near-silence, so what was heard can be credited to the right
command; it is scored the way the CommandBus decides (wake word, follow-up window) and counts only if
every expected word was heard. Prints a table and writes logs/listening_bench.json. Only uses the
pipeline's public pieces, so a copy also runs against older MXB versions (to measure before/after).
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RATE = 16000
FRAME = 512
PHRASES = [
    ("MXB, open Notepad.", "open notepad"),
    ("Hey MXB, what time is it?", "what time is it"),
    ("MXB, turn up the volume.", "turn up the volume"),
    ("MXB, open Chrome.", "open chrome"),
    ("MXB, take a screenshot.", "take a screenshot"),
    ("Ahh, MXB, open the calculator.", "open the calculator"),
]


# ---------------------------------------------------------------------------- audio helpers
def read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: needs 16-bit PCM")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        x = np.interp(np.arange(0, len(x), rate / RATE), np.arange(len(x)), x).astype(np.float32)
    return x


def frame_rms(x: np.ndarray) -> np.ndarray:
    n = len(x) // FRAME
    f = x[: n * FRAME].reshape(n, FRAME)
    return np.sqrt((f * f).mean(axis=1))


def speech_mask(x: np.ndarray) -> np.ndarray:
    r = frame_rms(x)
    return r > (r.max() * 0.1 if len(r) else 0)


def scale_to(x: np.ndarray, level: float) -> np.ndarray:
    r = frame_rms(x)
    active = r[speech_mask(x)]
    med = float(np.median(active)) if len(active) else 0.0
    return (x * (level / med)).astype(np.float32) if med > 0 else x


def synthesize(text: str, path: Path) -> bool:
    """Windows' built-in voice (System.Speech) straight to a 16 kHz mono WAV."""
    if os.name != "nt":
        return False
    safe_text, safe_path = text.replace("'", "''"), str(path).replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo -ArgumentList 16000, "
          "([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono); "
          f"$s.SetOutputToWaveFile('{safe_path}', $f); $s.Speak('{safe_text}'); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    return path.exists() and path.stat().st_size > 1000


def write_wav(path, x: np.ndarray):
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def describe_noise(x: np.ndarray) -> str:
    """Where the noise energy sits: mains hum / fan (low), voices / TV (speech band) or hiss (high)."""
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    total = float(spec.sum()) or 1.0
    bands = [("<150 Hz hum/rumble", 0, 150), ("150-3400 Hz speech band", 150, 3400), (">3400 Hz hiss", 3400, RATE / 2)]
    parts = [f"{name} {100 * float(spec[(freqs >= lo) & (freqs < hi)].sum()) / total:.0f}%" for name, lo, hi in bands]
    peak = float(freqs[int(np.argmax(spec[1:])) + 1])
    return ", ".join(parts) + f"; strongest at {peak:.0f} Hz"


def record_noise(pipe, seconds: float, fallback_rms: float):
    """A few seconds of the real room through the real microphone (nobody needs to talk)."""
    try:
        import sounddevice as sd
        idx, info, native = pipe._resolve_audio_device()
        rate = int(native or RATE)
        rec = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="float32", device=idx)
        sd.wait()
        x = rec.reshape(-1).astype(np.float32)
        if rate != RATE:
            x = np.interp(np.arange(0, len(x), rate / RATE), np.arange(len(x)), x).astype(np.float32)
        x = x[int(0.3 * RATE):]                     # skip the device's start-up click
        if len(x) > RATE and float(np.max(np.abs(x))) > 0:
            return x - float(np.mean(x)), f"recorded {seconds:.0f} s from '{info.get('name', idx)}'"
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
    else:
        reason = "the microphone returned silence"
    rng = np.random.default_rng(0)
    return rng.normal(0, fallback_rms, int(seconds * RATE)).astype(np.float32), f"synthetic ({reason})"


# ---------------------------------------------------------------------------- pipeline harness
class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in list(self._slots):
            fn(*args)


class _TTS:
    def __init__(self):
        self.started_speaking, self.finished_speaking = _Signal(), _Signal()

    def interrupt(self):
        pass

    def recent_spoken(self):
        return []

    def speaking_enabled(self):
        return False


class _Bus:
    """What VoicePipeline needs from the CommandBus; records what it would have been told."""

    def __init__(self, config):
        from engine.wake_word import WakeWordGate
        listen = config.get("listening", {})
        self.wake = WakeWordGate(mode="wake_word", wake_words=listen.get("wake_words"))
        self.router = types.SimpleNamespace(tts=_TTS())
        self.feedback = _Signal()
        self.action_queue = queue.Queue()
        self.busy = False
        self.heard = []

    def submit(self, text, source="voice", lang=None):
        self.heard.append((time.monotonic(), text))
        return "queued"


class _SessionSpy:
    """Wraps the Silero ONNX session to record each frame's speech probability (old and new code)."""

    def __init__(self, real):
        self.real, self.probs = real, []

    def get_inputs(self):
        return self.real.get_inputs()

    def run(self, outputs, feeds):
        result = self.real.run(outputs, feeds)
        self.probs.append(float(np.asarray(result[0]).reshape(-1)[-1]))
        return result


def wait_idle(pipe, timeout=90.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pipe.raw_audio_queue.empty() and pipe.utterance_queue.unfinished_tasks == 0:
            time.sleep(0.5)
            if pipe.raw_audio_queue.empty() and pipe.utterance_queue.unfinished_tasks == 0:
                return True
        time.sleep(0.1)
    return False


def feed(pipe, x: np.ndarray, speed: float = 2.0):
    for i in range(0, len(x) - FRAME + 1, FRAME):
        pipe.audio_callback(x[i:i + FRAME].reshape(-1, 1).astype(np.float32), FRAME, None, None)
        time.sleep(FRAME / RATE / speed)


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())


def covers(command: str, expected: str, fuzz) -> bool:
    """Every expected word was heard (allowing small spelling differences): "open" is not "open notepad"."""
    words = norm(command).split()
    if expected and expected.replace(" ", "") in "".join(words):          # "screen shot" = "screenshot"
        return True
    return bool(expected) and all(any(fuzz.ratio(e, w) >= 85 for w in words) for e in expected.split())


# ---------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--level", type=float, default=0.004, help="speech RMS (0.004 = the quiet mic that was measured)")
    ap.add_argument("--gain", default=None, help="engine.input_gain for this run: auto, off or a dB number")
    ap.add_argument("--noise-seconds", type=float, default=6.0)
    ap.add_argument("--synthetic-noise", type=float, default=None, help="use white noise at this RMS, don't record")
    ap.add_argument("--noise-wav", default=None, help="reuse a saved room-noise WAV (same noise for a before/after)")
    ap.add_argument("--save-noise", default=str(ROOT / "logs" / "room_noise.wav"), help="where to save the recording")
    ap.add_argument("--snr", type=float, default=None, help="speech this many dB above the room noise (overrides --level)")
    ap.add_argument("--turn", choices=["on", "off"], default=None, help="Smart Turn end-of-turn detection on or off")
    ap.add_argument("--wav", nargs="*", default=None, help="your own 16-bit WAV recordings instead of Windows' voice")
    ap.add_argument("--expect", nargs="*", default=None, help="expected command for each --wav (after the wake word)")
    ap.add_argument("--out", default=str(ROOT / "logs" / "listening_bench.json"))
    args = ap.parse_args(argv)

    from utils.paths import load_config
    from utils.version import __version__
    config = load_config()
    config.setdefault("engine", {})
    if args.gain is not None:
        config["engine"]["input_gain"] = args.gain
    if args.turn is not None:
        config.setdefault("turn_detection", {})["enabled"] = args.turn == "on"
    gain_setting = config["engine"].get("input_gain", "auto")

    try:
        from PySide6.QtCore import QCoreApplication
        _app = QCoreApplication.instance() or QCoreApplication([])    # noqa: F841 (keeps Qt objects happy)
    except Exception:
        pass

    from faster_whisper.vad import get_vad_model
    from thefuzz import fuzz
    from engine.wake_word import WakeWordGate
    import engine.audio as audio_mod
    from utils.credentials import CredentialsManager

    bus = _Bus(config)
    pipe = audio_mod.VoicePipeline(config, bus=bus)

    # 1. Room noise (before the fake stream replaces sounddevice for the pipeline).
    if args.synthetic_noise:
        noise = np.random.default_rng(0).normal(0, args.synthetic_noise, int(args.noise_seconds * RATE)).astype(np.float32)
        noise_src = f"synthetic white noise RMS {args.synthetic_noise}"
    elif args.noise_wav:
        noise, noise_src = read_wav(args.noise_wav), f"saved recording {args.noise_wav}"
    else:
        noise, noise_src = record_noise(pipe, args.noise_seconds, 0.0008)
        if args.save_noise and noise_src.startswith("recorded"):
            Path(args.save_noise).parent.mkdir(parents=True, exist_ok=True)
            write_wav(args.save_noise, noise)
            noise_src += f" (saved to {args.save_noise})"
    nr = frame_rms(noise)
    print(f"Room noise: {noise_src}; frame RMS median {np.median(nr):.4f}, p90 {np.percentile(nr, 90):.4f}")
    print(f"Room noise spectrum: {describe_noise(noise)}")
    if args.snr is not None:
        args.level = float(np.median(nr)) * 10 ** (args.snr / 20)
        print(f"Speech set {args.snr:.0f} dB above the noise: RMS {args.level:.4f}")

    # 2. Speech.
    tmp = Path(tempfile.mkdtemp(prefix="mxb_bench_"))
    clips = []
    if args.wav:
        expects = (args.expect or []) + [""] * len(args.wav)
        for path, expected in zip(args.wav, expects):
            clips.append((Path(path).name, norm(expected), read_wav(path)))
    else:
        for i, (text, expected) in enumerate(PHRASES):
            wav_path = tmp / f"phrase{i}.wav"
            if not synthesize(text, wav_path):
                print("Windows' voice (System.Speech) isn't available here; pass --wav recordings instead.")
                return 2
            clips.append((text, expected, read_wav(wav_path)))

    # 3. The real pipeline with a fake microphone stream.
    opened = threading.Event()

    class FakeStream:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            opened.set()
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            pass

    class SdProxy:
        InputStream = FakeStream

        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

    vad_model = get_vad_model()
    spy = _SessionSpy(vad_model.session)
    vad_model.session = spy
    pipe._vad_model = vad_model
    pipe._resolve_audio_device = lambda: (None, {"name": "listening bench (no microphone)"}, RATE)
    audio_mod.sd = SdProxy(audio_mod.sd)
    worker = threading.Thread(target=pipe.run, name="bench-pipeline", daemon=True)
    worker.start()
    if not opened.wait(timeout=300):
        print("The voice pipeline didn't start (speech model failed to load?). See logs/mxb_core.log.")
        return 3

    rng = np.random.default_rng(1)

    def room(n: int) -> np.ndarray:
        """n samples of the recorded room, from a random place in the recording."""
        start = int(rng.integers(0, len(noise) - n)) if len(noise) > n else 0
        return np.resize(noise[start:start + n] if len(noise) >= n else noise, n).astype(np.float32)

    def seconds(s: float) -> int:
        return int(s * RATE) // FRAME * FRAME          # whole frames, so speech starts on a frame boundary

    asr = "NVIDIA cloud" if CredentialsManager.has_nvidia_api_key() else f"local Whisper ({config['engine'].get('whisper_model', 'base.en')})"
    print(f"MXB v{__version__}, input gain setting: {gain_setting}, speech RMS {args.level}, recognizer: {asr}")

    results = []
    # Noise only first: settles the gain, and anything heard here is a false trigger.
    bus.heard.clear()
    first = len(spy.probs)
    feed(pipe, room(seconds(5.0)))
    wait_idle(pipe)
    false_triggers = [t for _, t in bus.heard]
    noise_probs = spy.probs[first:]

    for label, expected, clip in clips:
        speech = scale_to(clip, args.level)
        mask = speech_mask(speech)
        lead, tail = room(seconds(1.0)), room(seconds(1.8))
        # A second of near-silence after each command (the TV pauses), so the pipeline finishes the
        # utterance and what it heard is credited to this phrase rather than the next one.
        hush = np.random.default_rng(len(results)).normal(0, 0.0005, seconds(1.0)).astype(np.float32)
        mixed = np.concatenate([lead, speech + room(len(speech)), tail, hush])
        bus.heard.clear()
        start_frame = len(spy.probs) + len(lead) // FRAME
        feed(pipe, mixed)
        wait_idle(pipe)
        probs = np.array(spy.probs[start_frame:start_frame + len(mask)])
        speech_probs = probs[mask[: len(probs)]] if len(probs) else np.array([])
        # Score the way the CommandBus decides: one utterance at a time through a fresh wake-word gate,
        # so "MXB." followed by "Open the calculator." counts (the follow-up window), as it does live.
        gate = WakeWordGate(mode="wake_word", wake_words=config.get("listening", {}).get("wake_words"))
        commands, found = [], False
        for _, utterance in bus.heard:
            command = gate.process(utterance)
            if command is not None:
                found = True
                if command:
                    commands.append(command)
        rest = " ".join(commands)
        ok = bool(found and covers(rest, expected, fuzz))
        waited = getattr(pipe, "last_end_of_turn", (None, ""))
        results.append({"phrase": label, "expected": expected, "heard": [t for _, t in bus.heard], "wake_word": found,
                        "command": rest, "ok": ok, "end_of_turn_ms": waited[0], "end_of_turn_by": waited[1],
                        "vad_median": round(float(np.median(speech_probs)), 3) if speech_probs.size else None,
                        "vad_detected": round(float((speech_probs >= 0.35).mean()), 3) if speech_probs.size else None})

    pipe.is_running = False
    try:
        pipe.utterance_queue.put_nowait(None)
    except Exception:
        pass
    worker.join(timeout=5)

    agc = getattr(pipe, "agc", None)
    summary = {
        "version": __version__, "gain_setting": gain_setting, "gain_db_end": round(agc.gain_db, 1) if agc else None,
        "speech_rms": args.level, "noise": noise_src, "noise_rms_median": round(float(np.median(nr)), 5),
        "recognizer": asr, "false_triggers": false_triggers,
        "noise_vad_over_035": round(float((np.array(noise_probs) >= 0.35).mean()), 3) if noise_probs else None,
        "understood": sum(r["ok"] for r in results), "total": len(results), "results": results,
    }
    print(f"\nRoom noise only (5 s): {len(false_triggers)} false trigger(s) {false_triggers if false_triggers else ''}")
    print(f"{'phrase':34s} {'heard':42s} wake  ok   VAD med  speech found")
    for r in results:
        heard = " | ".join(r["heard"]) or "(nothing)"
        vad = f"{r['vad_median']:.2f}" if r["vad_median"] is not None else "  - "
        found_pct = f"{r['vad_detected'] * 100:.0f}%" if r["vad_detected"] is not None else "-"
        print(f"{r['phrase'][:34]:34s} {heard[:42]:42s} {'yes' if r['wake_word'] else 'no ':4s} "
              f"{'yes' if r['ok'] else 'NO ':4s} {vad:>7s}  {found_pct:>6s}")
    waits = [r["end_of_turn_ms"] for r in results if r.get("end_of_turn_ms")]
    if waits:
        by_turn = sum(r.get("end_of_turn_by") == "smart turn" for r in results)
        print(f"MXB stopped listening {int(np.median(waits))} ms after you stopped talking (median; "
              f"{by_turn}/{len(results)} turns ended by Smart Turn)")
    print(f"\nUnderstood {summary['understood']}/{summary['total']} commands"
          + (f"; input gain ended at {summary['gain_db_end']:+.1f} dB" if agc else "; (this version has no input gain)"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)          # the pipeline's model threads are daemons; don't wait on Qt at exit
