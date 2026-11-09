"""
Frozen-build smoke test:  MXB.exe --smoke-test [report.json]

The commonest way a PyInstaller build breaks is a module or data file that wasn't bundled, which
only shows up when a user hits that feature. This imports every module MXB needs, checks every
shipped data file, loads the Silero VAD model, writes a JSON report and exits 0 (all good) or 1.

It never opens a window, a microphone or the network, and it never raises (an unhandled
exception in a windowed build pops a dialog that would hang CI).
"""
import importlib
import json
import platform
import sys
import time
from pathlib import Path

OWN_MODULES = [
    "engine.command_bus", "engine.executor", "engine.router", "engine.planner", "engine.agent_loop",
    "engine.audio", "engine.tts", "engine.streaming", "engine.barge_in", "engine.wake_engine",
    "engine.ui_automation", "engine.hardware", "engine.screen", "engine.file_ops", "engine.undo",
    "engine.knowledge", "engine.semantic_memory", "engine.embeddings", "engine.scheduler",
    "engine.routines", "engine.skills", "engine.remote_server",
    "safety.policy", "safety.permissions", "safety.injection", "safety.audit", "safety.hotkeys",
    "ui.chat", "ui.hud", "ui.tray", "ui.settings", "ui.setup_wizard", "ui.marks_overlay",
    "utils.updater", "utils.autostart", "utils.paths", "utils.version", "utils.single_instance",
    "engine.web", "engine.mcp_client", "engine.grounding", "engine.indic",
    "engine.scam_shield", "engine.meetings", "engine.accessibility", "engine.focus_coach",
]

THIRD_PARTY = [
    "PySide6.QtWidgets", "numpy", "requests", "psutil", "pyperclip", "rapidfuzz", "thefuzz.fuzz",
    "faster_whisper", "ctranslate2", "onnxruntime", "sounddevice", "edge_tts", "miniaudio", "qrcode",
    "pypdf", "docx", "send2trash", "PIL.Image", "pynput.keyboard", "pynput.mouse", "keyboard",
    "playwright.sync_api", "mcp", "mcp.client.stdio", "mcp.client.streamable_http", "zxingcpp",
]

WINDOWS_ONLY = [
    "pywinauto", "pycaw.pycaw", "comtypes", "win32com.client", "pythoncom", "pyttsx3",
    "pyttsx3.drivers.sapi5", "screen_brightness_control", "pygetwindow",
    "winrt.windows.media.ocr", "winrt.windows.graphics.imaging", "winrt.windows.storage.streams",
    "winrt.windows.devices.radios", "pyaudiowpatch",
]

# Gracefully fall back if blocked by App Control policy or absent
OPTIONAL_MODULES = {
    "miniaudio",
}


def default_modules() -> list[str]:
    mods = OWN_MODULES + THIRD_PARTY
    if sys.platform == "win32":
        mods += WINDOWS_ONLY
    return mods


def check_modules(names: list[str]) -> dict[str, str]:
    results = {}
    for name in names:
        try:
            importlib.import_module(name)
            results[name] = "ok"
        except BaseException as e:  # SystemExit/KeyboardInterrupt from a bad import still mustn't escape
            results[name] = f"FAIL: {type(e).__name__}: {e}"[:300]
    return results


def check_files(base: Path | None = None) -> dict[str, str]:
    from utils.paths import bundle_dir
    base = Path(base) if base else bundle_dir()
    out = {
        "config.json": "ok" if (base / "config.json").is_file() else "FAIL: missing",
        "plugins": "ok" if any((base / "plugins").glob("*.py")) else "FAIL: no plugins",
    }
    try:
        json.loads((base / "config.json").read_text(encoding="utf-8"))
    except Exception as e:
        out["config.json"] = f"FAIL: {e}"
    return out


def check_vad() -> str:
    try:
        from faster_whisper.vad import get_vad_model
        get_vad_model()
        return "ok"
    except BaseException as e:
        return f"FAIL: {type(e).__name__}: {e}"[:300]


def run(report_path: str | None = None, modules: list[str] | None = None, vad: bool = True) -> int:
    started = time.perf_counter()
    try:
        report = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "modules": check_modules(default_modules() if modules is None else modules),
            "files": check_files(),
        }
        if vad:
            report["files"]["silero_vad"] = check_vad()
        failures = [k for section in ("modules", "files") for k, v in report[section].items() if v != "ok" and k not in OPTIONAL_MODULES]
        report["failures"] = failures
        report["ok"] = not failures
    except BaseException as e:
        report = {"ok": False, "failures": ["smoke-test"], "error": f"{type(e).__name__}: {e}"}
    report["seconds"] = round(time.perf_counter() - started, 2)
    text = json.dumps(report, indent=2)
    if report_path:
        try:
            Path(report_path).write_text(text, encoding="utf-8")
        except OSError:
            pass
    try:
        print(text)
    except Exception:
        pass
    return 0 if report["ok"] else 1


def run_from_argv(argv: list[str]) -> int:
    """main.py hook: `MXB.exe --smoke-test [report.json]`."""
    args = argv[argv.index("--smoke-test") + 1:]
    return run(args[0] if args else None)
