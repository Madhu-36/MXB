"""
Where MXB keeps its code and its data.

- Source checkout (python main.py): everything stays next to the code, exactly as before.
- Installed / frozen build (MXB.exe): user data lives in %APPDATA%\\MXB so updates and
  uninstalls never touch it, and the program folder can stay read-only.
- MXB_DATA_DIR=<folder> overrides data location (portable installs, tests).
- MXB_BUNDLE_DIR=<folder> overrides shipped bundle location (tests).

bundle_dir() is where read-only shipped files live (default config, plugins, Modelfile).
"""
import json
import os
import shutil
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Read-only files shipped with MXB (PyInstaller unpacks them into sys._MEIPASS)."""
    override = os.environ.get("MXB_BUNDLE_DIR")
    if override:
        return Path(override)
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return APP_DIR


def data_dir() -> Path:
    override = os.environ.get("MXB_DATA_DIR")
    if override:
        path = Path(override)
    elif is_frozen():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "MXB"
    else:
        path = APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_file(*parts: str) -> Path:
    """A file inside the data folder (parent folders are created)."""
    path = data_dir().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """User config. On first run of an installed copy, the shipped default is copied in."""
    path = data_dir() / "config.json"
    if not path.exists():
        default = bundle_dir() / "config.json"
        if default.exists() and default.resolve() != path.resolve():
            shutil.copy2(default, path)
    return path


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config: dict) -> Path:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash mid-write can't corrupt the config
    return path


def plugin_dirs() -> list[Path]:
    """Shipped example plugins first, then the user's own plugins folder."""
    dirs = [bundle_dir() / "plugins"]
    user = data_dir() / "plugins"
    if user.resolve() != dirs[0].resolve():
        user.mkdir(parents=True, exist_ok=True)
        dirs.append(user)
    return dirs


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
