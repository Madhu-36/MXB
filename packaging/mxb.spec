# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MXB: one folder, windowed (no console).

    powershell -ExecutionPolicy Bypass -File packaging\\build.ps1      (recommended: venv + exe + installer)
    python -m PyInstaller packaging\\mxb.spec --noconfirm --clean       (exe folder only)

Output: dist\\MXB\\MXB.exe with everything else in dist\\MXB\\_internal\\ (sys._MEIPASS).
User data never goes in here; it lives in %APPDATA%\\MXB (see utils/paths.py).
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = this file's folder (packaging/)
sys.path.insert(0, str(ROOT))


def optional(fn, *args, **kwargs):
    """Optional packages (openwakeword...) may be absent: bundle them only if installed."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return []


def local_modules(package: str) -> list[str]:
    """Every module of our own packages. Plugins import engine.* at runtime, so bundle all of it."""
    names = []
    for f in sorted((ROOT / package).rglob("*.py")):
        parts = list(f.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if "__pycache__" not in parts:
            names.append(".".join(parts))
    return names


datas = [
    (str(ROOT / "config.json"), "."),          # default config, copied to %APPDATA%\MXB on first run
    (str(ROOT / "plugins" / "*.py"), "plugins"),
]
if (ROOT / "llm" / "Modelfile").exists():
    datas.append((str(ROOT / "llm" / "Modelfile"), "llm"))
datas += optional(collect_data_files, "faster_whisper")   # Silero VAD .onnx assets
datas += optional(collect_data_files, "openwakeword")     # optional offline wake-word models
datas += optional(collect_data_files, "edge_tts")
datas += optional(collect_data_files, "playwright")       # the Playwright driver (talks to Edge/Chrome)

binaries = []
binaries += optional(collect_dynamic_libs, "ctranslate2")  # Whisper inference DLLs
binaries += optional(collect_dynamic_libs, "onnxruntime")
binaries += optional(collect_dynamic_libs, "sherpa_onnx")  # v4.4 voice ID + keyword spotting

hiddenimports = []
for pkg in ("engine", "safety", "utils", "ui"):
    hiddenimports += local_modules(pkg)
for pkg in ("winrt", "pycaw", "pywinauto", "screen_brightness_control", "edge_tts", "mcp", "playwright"):
    hiddenimports += optional(collect_submodules, pkg)
hiddenimports += [
    # imported dynamically by name, so static analysis can't see them
    "pyttsx3.drivers", "pyttsx3.drivers.sapi5",
    "pynput.keyboard._win32", "pynput.mouse._win32",
    "win32com.client", "pythoncom", "pywintypes",
    "comtypes.client", "comtypes.stream",
    "send2trash", "miniaudio", "qrcode.image.pil", "pypdf", "docx",
    "sounddevice", "onnxruntime",
    "zxingcpp", "pyaudiowpatch",   # v4.3: QR decoding, meeting loopback audio (imported lazily)
    "sherpa_onnx", "icalendar", "recurring_ical_events",   # v4.4: voice ID, wake word, calendar
]

excludes = [
    # never imported by MXB; keeping them out saves hundreds of MB
    "torch", "torchaudio", "tensorflow", "matplotlib", "tkinter", "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
]

icon = ROOT / "packaging" / "mxb.ico"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MXB",
    console=False,               # windowed: no console window (main.py redirects stdio to logs)
    disable_windowed_traceback=False,
    upx=False,                   # UPX-packed exes trigger antivirus false positives
    icon=str(icon) if icon.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MXB",
)
