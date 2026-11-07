"""
MXB File Access Permissions.

Default scope: the user's own folders (Desktop, Documents, Downloads, Pictures,
Music, Videos, OneDrive). Anything else — other drives, project folders, or the
whole disk — must be granted by the user ("give access to D drive",
"give full file access"). Grants persist in permissions.json next to config.json.

Operating-system folders (Windows, Program Files) are always write-protected,
even with full access: one misheard command must never be able to break Windows.
"""
import json
import os
import re
import sys
import threading
from pathlib import Path

_ALL_WORDS = {"all", "everything", "full", "*", "all files", "entire disk", "whole computer", "all drives"}


def _norm(path) -> str:
    p = os.path.expanduser(str(path).strip().strip('"').strip("'"))
    return os.path.normcase(os.path.abspath(p))


def _is_under(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False  # different drives on Windows


def parse_location(text: str) -> str:
    """
    Turns spoken locations into paths:
      "d", "d drive", "drive d", "D:" -> "D:\\"
      "desktop" / "downloads" ...     -> user folder
      anything else                    -> unchanged
    """
    raw = (text or "").strip().strip('"').strip("'").rstrip(".")
    low = raw.lower()
    low = re.sub(r"^(?:the|my)\s+", "", low)
    m = re.fullmatch(r"(?:drive\s+)?([a-z])(?::\\?|:/?)?(?:\s+drive)?", low)
    if m:
        return f"{m.group(1).upper()}:\\"
    home_folders = {
        "desktop": "Desktop", "documents": "Documents", "downloads": "Downloads",
        "pictures": "Pictures", "music": "Music", "videos": "Videos", "home": "",
    }
    if low in home_folders:
        return str(Path.home() / home_folders[low])
    return raw


class FileAccessManager:
    def __init__(self, store_path: str | Path | None = None, default_roots: list | None = None,
                 protected_roots: list | None = None, extra_allowed: list | None = None):
        self.store_path = Path(store_path) if store_path else Path(__file__).parent.parent / "permissions.json"
        self._lock = threading.Lock()
        self._default_roots = default_roots
        self._protected_roots = protected_roots
        self.granted: list[str] = []
        self.full_access = False
        self._load()
        for extra in extra_allowed or []:
            if extra and _norm(extra) not in self.granted:
                self.granted.append(_norm(extra))

    # ------------------------------------------------------------------ roots
    def default_roots(self) -> list[str]:
        if self._default_roots is not None:
            return [_norm(p) for p in self._default_roots]
        home = Path.home()
        names = ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive"]
        return [_norm(home / n) for n in names]

    def protected_roots(self) -> list[str]:
        if self._protected_roots is not None:
            return [_norm(p) for p in self._protected_roots]
        if sys.platform == "win32":
            env_keys = ["SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"]
            roots = [os.environ.get(k) for k in env_keys]
            return [_norm(r) for r in roots if r]
        return [_norm(p) for p in ["/bin", "/boot", "/etc", "/lib", "/sbin", "/usr", "/System"]]

    def allowed_roots(self) -> list[str]:
        return self.default_roots() + list(self.granted)

    # ------------------------------------------------------------------ checks
    def can_read(self, path) -> bool:
        target = _norm(path)
        if self.full_access:
            return True
        return any(_is_under(target, root) for root in self.allowed_roots())

    def is_protected(self, path) -> bool:
        target = _norm(path)
        return any(_is_under(target, root) for root in self.protected_roots())

    def can_write(self, path) -> bool:
        return self.can_read(path) and not self.is_protected(path)

    def check(self, path, write: bool = False) -> tuple[bool, str]:
        if write and self.is_protected(path):
            return False, f"'{path}' is inside a protected system folder. MXB never modifies Windows or Program Files."
        if not self.can_read(path):
            return False, (f"I don't have access to '{path}'. Say 'give access to {self._suggest_grant(path)}' "
                           "if you want me to use it.")
        return True, ""

    @staticmethod
    def _suggest_grant(path) -> str:
        s = str(path)
        m = re.match(r"^([A-Za-z]):", s)
        if m:
            return f"{m.group(1).upper()} drive"
        return str(Path(s).parent) if Path(s).suffix else s

    # ------------------------------------------------------------------ grants
    def grant(self, location: str) -> str:
        loc = (location or "").strip().lower()
        with self._lock:
            if loc in _ALL_WORDS:
                self.full_access = True
                self._save()
                return "Full file access granted. System folders stay write-protected."
            path = parse_location(location)
            normed = _norm(path)
            if normed not in self.granted:
                self.granted.append(normed)
                self._save()
            return f"Access granted to {path}."

    def revoke(self, location: str) -> str:
        loc = (location or "").strip().lower()
        with self._lock:
            if loc in _ALL_WORDS:
                had = self.full_access or bool(self.granted)
                self.full_access = False
                self.granted = []
                self._save()
                return "Revoked all extra file access. Only your personal folders remain." if had else "No extra access was granted."
            normed = _norm(parse_location(location))
            before = len(self.granted)
            self.granted = [g for g in self.granted if not _is_under(g, normed)]
            removed = before - len(self.granted)
            self._save()
            if removed:
                return f"Revoked access to {parse_location(location)}."
            if any(_is_under(normed, d) or _is_under(d, normed) for d in self.default_roots()):
                return "That is one of your personal folders, which MXB can always use."
            return f"I didn't have special access to {parse_location(location)}."

    def describe(self) -> str:
        if self.full_access:
            return "I have full file access (system folders are read-only)."
        extra = ", ".join(self.granted) if self.granted else "none"
        return f"I can use your personal folders (Desktop, Documents, Downloads, Pictures, Music, Videos). Extra access: {extra}."

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            if self.store_path.exists():
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                self.granted = [_norm(p) for p in data.get("granted", []) if p]
                self.full_access = bool(data.get("full_access", False))
        except Exception:
            self.granted, self.full_access = [], False

    def _save(self):
        try:
            self.store_path.write_text(
                json.dumps({"full_access": self.full_access, "granted": self.granted}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


_shared: FileAccessManager | None = None


def get_file_access() -> FileAccessManager:
    """Process-wide shared instance (lazy, so tests can construct their own)."""
    global _shared
    if _shared is None:
        extra = []
        try:
            cfg = json.loads((Path(__file__).parent.parent / "config.json").read_text(encoding="utf-8"))
            extra = cfg.get("files", {}).get("extra_allowed_folders", []) or []
        except Exception:
            pass
        _shared = FileAccessManager(extra_allowed=extra)
    return _shared
