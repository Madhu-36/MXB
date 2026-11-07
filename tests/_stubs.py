"""
Cross-platform test helpers.

MXB targets Windows, but most of its logic (routing, safety, permissions,
command bus, wake word, parsing) is plain Python. On non-Windows CI machines
this module installs minimal stand-ins for Windows-only packages so those
modules can be imported and unit-tested. On Windows it does nothing.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _module(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def install():
    if sys.platform == "win32":
        return

    class _Dummy:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: None

    try:
        import pynput.keyboard  # noqa: F401
    except Exception:
        pynput = _module("pynput")
        kb = _module("pynput.keyboard", Controller=_Dummy, Key=_Dummy())
        pynput.keyboard = kb

    try:
        import pygetwindow  # noqa: F401
    except Exception:
        _module("pygetwindow", getActiveWindow=lambda: None, getAllWindows=lambda: [])

    if "pythoncom" not in sys.modules:
        _module("pythoncom", CoInitialize=lambda: None, CoUninitialize=lambda: None)
    if "win32com" not in sys.modules:
        w = _module("win32com")
        w.client = _module("win32com.client", Dispatch=_Dummy)


install()
