"""
Start MXB with Windows (per-user, no admin): HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\MXB.

Installed build -> "...\\MXB.exe". Source checkout -> pythonw.exe (no console window) + main.py.
The registry is injectable so the logic is testable on any OS.
"""
import sys
from pathlib import Path
from utils.paths import APP_DIR, is_frozen

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MXB"


class WinRegistry:
    def get(self, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def launch_command() -> str:
    if is_frozen():
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    return f'"{runner}" "{APP_DIR / "main.py"}"'


def _registry(reg=None):
    if reg is not None:
        return reg
    if sys.platform != "win32":
        raise RuntimeError("Starting with Windows is only available on Windows.")
    return WinRegistry()


def is_enabled(reg=None) -> bool:
    try:
        return bool(_registry(reg).get(VALUE_NAME))
    except RuntimeError:
        return False


def enable(reg=None) -> str:
    try:
        _registry(reg).set(VALUE_NAME, launch_command())
    except RuntimeError as e:
        return str(e)
    return "Done. MXB will start automatically when you sign in to Windows."


def disable(reg=None) -> str:
    try:
        _registry(reg).delete(VALUE_NAME)
    except RuntimeError as e:
        return str(e)
    return "Done. MXB won't start with Windows anymore."


def handle(mode: str, reg=None) -> str:
    mode = (mode or "status").lower().strip()
    if mode in ("on", "enable", "yes", "true"):
        return enable(reg)
    if mode in ("off", "disable", "no", "false"):
        return disable(reg)
    return "MXB starts with Windows." if is_enabled(reg) else "MXB doesn't start with Windows. Say 'start with windows' to turn it on."
