"""
Windows integration check:  python -m utils.windows_check

The test suites replace Windows with fakes so they run anywhere. This does the opposite: it drives
the real Windows pieces MXB v4.3 depends on, one at a time, and prints PASS / FAIL / SKIP for each.

Safe to run on your own PC: it presses no keys, clicks nothing, speaks nothing and saves nothing.
It listens to your speakers' loopback for one second (nothing is stored), and it never prints
window titles or on-screen text, only types, counts and device names.
"""
import importlib
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, str]] = []
WINDOWS = sys.platform == "win32"
IMPORTS = [
    "PySide6.QtWidgets", "numpy", "sounddevice", "faster_whisper", "ctranslate2", "onnxruntime", "edge_tts",
    "miniaudio", "rapidfuzz", "psutil", "pyperclip", "qrcode", "zxingcpp", "playwright.sync_api", "mcp",
    "pypdf", "docx", "send2trash",
]
WINDOWS_IMPORTS = ["pywinauto", "comtypes", "win32com.client", "pythoncom", "pyaudiowpatch", "pycaw.pycaw",
                   "winrt.windows.media.ocr", "screen_brightness_control"]


def check(name: str, windows_only: bool = False):
    def wrap(fn):
        def run():
            if windows_only and not WINDOWS:
                RESULTS.append(("SKIP", name, "needs Windows"))
                return
            try:
                detail = fn() or ""
                RESULTS.append(("PASS", name, str(detail)))
            except Exception as e:
                tb = traceback.extract_tb(e.__traceback__)[-1]
                RESULTS.append(("FAIL", name, f"{type(e).__name__}: {e} ({Path(tb.filename).name}:{tb.lineno})"))
        run.__name__ = name
        return run
    return wrap


@check("python")
def _python():
    return f"{platform.python_version()} {platform.architecture()[0]} on {platform.platform()}"


@check("imports")
def _imports():
    missing = []
    for mod in IMPORTS + (WINDOWS_IMPORTS if WINDOWS else []):
        try:
            importlib.import_module(mod)
        except Exception as e:
            missing.append(f"{mod} ({type(e).__name__})")
    if missing:
        raise RuntimeError("missing: " + ", ".join(missing))
    return f"{len(IMPORTS) + (len(WINDOWS_IMPORTS) if WINDOWS else 0)} packages import"


@check("mxb modules")
def _modules():
    from utils.smoke_test import OWN_MODULES
    bad = []
    for mod in OWN_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as e:
            bad.append(f"{mod} ({type(e).__name__}: {e})")
    if bad:
        raise RuntimeError("; ".join(bad[:5]))
    return f"{len(OWN_MODULES)} modules import"


@check("ui automation: focused element", windows_only=True)
def _uia_focus():
    from engine.ui_automation import UIAutomation
    uia = UIAutomation()
    if not uia.available():
        raise RuntimeError("pywinauto UIA backend unavailable")
    t0 = time.perf_counter()
    el = uia.focused()
    ms = (time.perf_counter() - t0) * 1000
    if el is None:
        raise RuntimeError("no focused element returned")
    return f"{el.control_type or '?'} (named: {'yes' if el.name else 'no'}) in {ms:.0f} ms"


@check("ui automation: reading cursor", windows_only=True)
def _uia_cursor():
    from engine.accessibility import VirtualCursor, describe_element
    from engine.ui_automation import UIAutomation
    uia = UIAutomation()
    t0 = time.perf_counter()
    elements, _ = uia.collect()
    ms = (time.perf_counter() - t0) * 1000
    cursor = VirtualCursor(elements, uia.foreground_title())
    el, info = cursor.move("element", "first")
    spoken = describe_element(el, info) if el is not None else info
    return f"{len(elements)} elements in {ms:.0f} ms; first reads like '..., {spoken.split(', ', 1)[-1]}'"


@check("foreground tracker", windows_only=True)
def _probe():
    from engine.focus_coach import classify, windows_probe
    app, title, idle, hwnd = windows_probe()
    label, category, _ = classify(app, title)
    if not app or not hwnd:
        raise RuntimeError("no foreground window/process")
    return f"{app} -> {category}; idle {idle:.1f} s"


@check("speaker loopback (1 s, not saved)", windows_only=True)
def _loopback():
    import numpy as np
    from engine.meetings import LoopbackSource
    blocks = []
    src = LoopbackSource()
    src.start(blocks.append)
    try:
        time.sleep(1.2)
    finally:
        src.stop()
    if not blocks:
        raise RuntimeError("the loopback stream delivered no audio")
    audio = np.concatenate(blocks)
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    import pyaudiowpatch as pyaudio
    pa = pyaudio.PyAudio()
    try:
        name = pa.get_default_wasapi_loopback()["name"]
    finally:
        pa.terminate()
    return f"{len(blocks)} blocks, {len(audio) / 16000:.1f} s at 16 kHz, level {rms:.4f} ({'sound playing' if rms > 0.001 else 'silence'}) from '{name}'"


@check("microphone device")
def _mic():
    import sounddevice as sd
    dev = sd.query_devices(kind="input")
    return f"default input: {dev['name']} ({int(dev['max_input_channels'])} ch)"


@check("windows voice speed (SAPI)", windows_only=True)
def _sapi():
    from engine.tts import SapiBackend, sapi_rate
    backend = SapiBackend({})
    backend.start()
    try:
        backend.set_rate(20)
        got = int(backend.speaker.Rate)
        if got != sapi_rate(20):
            raise RuntimeError(f"Rate is {got}, expected {sapi_rate(20)}")
        voice = backend.speaker.Voice.GetDescription()
    finally:
        backend.stop()
    return f"rate +20% -> SAPI {got} on '{voice}'"


@check("accessibility shortcuts map to keys")
def _keys():
    from engine.accessibility import WINDOWS_TOOLS
    from engine.keyboard_ext import KeyboardExtended
    bad = [combo for combo, _ in WINDOWS_TOOLS.values()
           if not KeyboardExtended.validate_shortcut_keys(*combo.split("+"))["valid"]]
    if bad:
        raise RuntimeError("unknown keys in " + ", ".join(bad))
    return f"{len(WINDOWS_TOOLS)} shortcuts valid (not pressed)"


@check("scam shield: QR + rules (offline)")
def _scam():
    import qrcode
    from engine.scam_shield import ScamShield
    shield = ScamShield({"scam_shield": {"ai_second_opinion": False}})
    img = qrcode.make("upi://pay?pa=refund.desk@okaxis&pn=Refund%20Desk&am=4999&cu=INR").convert("RGB")
    qr = shield.check_qr_image(img)
    if qr is None or not qr.upi:
        raise RuntimeError("QR code not decoded")
    text = shield.check_text("Your SBI account will be blocked today. Share the OTP sent to your phone to "
                             "complete KYC: http://sbi-kyc-update.xyz/login", use_llm=False)
    if text.level != "high":
        raise RuntimeError(f"known scam scored '{text.level}'")
    return f"QR pays {qr.upi[0].get('payee', '?')} Rs {qr.upi[0].get('amount', '?')}; KYC/OTP scam -> {text.level}"


@check("focus coach database")
def _store():
    from engine.focus_coach import ActivityStore
    with tempfile.TemporaryDirectory() as tmp:
        store = ActivityStore(Path(tmp) / "activity.db")
        store.add_usage("2026-11-08", "VS Code", "focus", 90)
        store.add_usage("2026-11-08", "VS Code", "focus", 30)
        rows = store.usage("2026-11-08", "2026-11-08")
    if rows != [("VS Code", "focus", 120.0)]:
        raise RuntimeError(f"unexpected rows {rows}")
    return "sqlite add/report ok"


def main() -> int:
    checks = [_python, _imports, _modules, _uia_focus, _uia_cursor, _probe, _loopback, _mic, _sapi, _keys,
              _scam, _store]
    for fn in checks:
        fn()
    width = max(len(name) for _, name, _ in RESULTS)
    for status, name, detail in RESULTS:
        print(f"{status:4}  {name.ljust(width)}  {detail}", flush=True)
    fails = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    print(f"\n{len(RESULTS) - fails} ok, {fails} failed", flush=True)
    return min(fails, 99)


if __name__ == "__main__":
    sys.exit(main())
