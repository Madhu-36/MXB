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

# Ensure project root is in sys.path even when smoke_test.py is run directly
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OWN_MODULES = [
    # engine
    "engine.accessibility", "engine.actions_catalog", "engine.agent_loop", "engine.audio",
    "engine.barge_in", "engine.color_picker", "engine.command_bus", "engine.embeddings",
    "engine.executor", "engine.file_ops", "engine.focus_coach", "engine.grounding",
    "engine.hardware", "engine.indic", "engine.keyboard_ext", "engine.knowledge",
    "engine.kws_engine", "engine.listening", "engine.llm_client", "engine.mcp_client",
    "engine.meetings", "engine.memory", "engine.mouse", "engine.persona",
    "engine.planner", "engine.proactive", "engine.remote_server", "engine.router",
    "engine.routines", "engine.scam_shield", "engine.scheduler", "engine.screen",
    "engine.semantic_memory", "engine.skills", "engine.streaming", "engine.tts",
    "engine.turn_detector", "engine.ui_automation", "engine.undo", "engine.voice_id",
    "engine.wake_engine", "engine.wake_word", "engine.web", "engine.window_manager",
    # safety
    "safety.audit", "safety.hotkeys", "safety.injection", "safety.permissions", "safety.policy",
    # ui
    "ui.chat", "ui.hud", "ui.marks_overlay", "ui.settings", "ui.setup_wizard", "ui.tray",
    # utils
    "utils.app_launcher", "utils.audio_benchmark", "utils.audio_feedback", "utils.autostart",
    "utils.clipboard_monitor", "utils.config_schema", "utils.credentials", "utils.diagnostics",
    "utils.environment", "utils.fetch_models", "utils.llm_builder", "utils.logger",
    "utils.math_evaluator", "utils.mic_setup", "utils.model_setup", "utils.notifications",
    "utils.paths", "utils.power_manager", "utils.process_manager", "utils.single_instance",
    "utils.smoke_test", "utils.timer_manager", "utils.updater", "utils.vault",
    "utils.version", "utils.weather", "utils.web_search", "utils.windows_check",
]

THIRD_PARTY = [
    "PySide6.QtWidgets", "numpy", "requests", "psutil", "pyperclip", "rapidfuzz", "thefuzz.fuzz",
    "faster_whisper", "ctranslate2", "onnxruntime", "sounddevice", "edge_tts", "miniaudio", "qrcode",
    "pypdf", "docx", "send2trash", "PIL.Image", "pynput.keyboard", "pynput.mouse", "keyboard",
    "playwright.sync_api", "mcp", "mcp.client.stdio", "mcp.client.streamable_http", "zxingcpp",
    "sherpa_onnx", "icalendar", "recurring_ical_events", "win11toast", "duckduckgo_search",
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
    "sherpa_onnx",
    "openwakeword",
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
    if not ((base / "mxb.ico").is_file() or (base / "packaging" / "mxb.ico").is_file()):
        out["icon"] = "FAIL: missing mxb.ico"
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


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
