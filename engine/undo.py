"""
Undo journal for MXB's file actions ("undo that", "undo the last file action").

Every successful move / rename / copy / create / recycle / overwrite done by MXB is
recorded with enough information to reverse it:
  move/rename  -> move it back
  copy/create  -> send the new item to the Recycle Bin
  recycle      -> restore it from the Recycle Bin (Windows Shell)
  overwrite    -> put the backed-up previous version back
Permanent deletes cannot be undone, and MXB says so.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path
from utils.logger import log
from utils.paths import data_file, data_dir

BACKUP_LIMIT_BYTES = 50 * 1024 * 1024


class UndoJournal:
    def __init__(self, store_path: str | Path | None = None, backup_dir: str | Path | None = None, max_entries: int = 50):
        self.store_path = Path(store_path) if store_path else data_file("undo_journal.json")
        self.backup_dir = Path(backup_dir) if backup_dir else data_dir() / "backups"
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            if self.store_path.exists():
                self.entries = json.loads(self.store_path.read_text(encoding="utf-8"))[-self.max_entries:]
        except Exception:
            self.entries = []

    def _save(self):
        try:
            self.store_path.write_text(json.dumps(self.entries[-self.max_entries:], indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Undo: could not save journal: {e}")

    # ------------------------------------------------------------------ recording
    def record(self, kind: str, **data):
        entry = {"kind": kind, "time": time.time(), **{k: str(v) for k, v in data.items()}}
        with self._lock:
            self.entries.append(entry)
            self.entries = self.entries[-self.max_entries:]
            self._save()
        log.info(f"Undo: recorded {kind} {data}")

    def backup_before_overwrite(self, path: Path) -> str | None:
        """Copies a file about to be overwritten. Returns the backup path."""
        try:
            if not path.is_file() or path.stat().st_size > BACKUP_LIMIT_BYTES:
                return None
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            dest = self.backup_dir / f"{int(time.time() * 1000)}_{path.name}"
            shutil.copy2(path, dest)
            return str(dest)
        except Exception as e:
            log.warning(f"Undo: backup failed for {path}: {e}")
            return None

    def last(self) -> dict | None:
        with self._lock:
            return dict(self.entries[-1]) if self.entries else None

    def seconds_since_last(self) -> float | None:
        entry = self.last()
        return None if entry is None else time.time() - float(entry["time"])

    def describe_last(self) -> str:
        e = self.last()
        if not e:
            return "nothing"
        names = {"move": "moving", "rename": "renaming", "copy": "copying", "create": "creating",
                 "recycle": "deleting", "overwrite": "overwriting"}
        target = Path(e.get("src") or e.get("path") or e.get("dst") or "").name
        return f"{names.get(e['kind'], e['kind'])} {target}"

    # ------------------------------------------------------------------ undo
    def undo_last(self, recycle_fn=None, restore_fn=None) -> str:
        with self._lock:
            if not self.entries:
                return "There's nothing of mine to undo."
            entry = self.entries.pop()
            self._save()
        kind = entry["kind"]
        try:
            if kind in ("move", "rename"):
                src, dst = Path(entry["src"]), Path(entry["dst"])
                if not dst.exists():
                    return f"I can't undo that: {dst.name} is no longer where I put it."
                if src.exists():
                    return f"I can't undo that: something already exists at {src}."
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
                return f"Undone: {src.name} is back in {src.parent}."
            if kind in ("copy", "create"):
                path = Path(entry.get("dst") or entry.get("path"))
                if not path.exists():
                    return f"{path.name} is already gone."
                recycle = recycle_fn or _default_recycle
                if recycle(path):
                    return f"Undone: removed {path.name} (it's in the Recycle Bin)."
                return f"I couldn't remove {path.name}."
            if kind == "overwrite":
                path, backup = Path(entry["path"]), Path(entry.get("backup", ""))
                if not backup.is_file():
                    return f"The backup of {path.name} is missing, so I can't restore it."
                shutil.copy2(backup, path)
                return f"Undone: restored the previous version of {path.name}."
            if kind == "recycle":
                path = entry["path"]
                restore = restore_fn or restore_from_recycle_bin
                if restore(path):
                    return f"Undone: restored {Path(path).name} from the Recycle Bin."
                return f"I couldn't find {Path(path).name} in the Recycle Bin. Restore it from there manually."
            if kind == "permanent_delete":
                return "That was a permanent delete, so it can't be undone."
            return f"I don't know how to undo '{kind}'."
        except Exception as e:
            log.error(f"Undo failed: {e}")
            return f"Undo failed: {e}"


def _default_recycle(path: Path) -> bool:
    try:
        from send2trash import send2trash
        send2trash(str(path))
        return True
    except Exception:
        return False


def restore_from_recycle_bin(original_path: str) -> bool:
    """Restores an item to its original location via the Windows Shell (Recycle Bin = namespace 10)."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("Shell.Application")
        bin_folder = shell.Namespace(10)
        target = os.path.normcase(os.path.abspath(original_path))
        stem = os.path.splitext(os.path.basename(target))[0]
        candidates = []
        for item in bin_folder.Items():
            original_dir = bin_folder.GetDetailsOf(item, 1) or ""
            name = item.Name or ""
            full = os.path.normcase(os.path.join(original_dir, name))
            if full == target or (os.path.normcase(original_dir) == os.path.dirname(target)
                                  and os.path.splitext(name)[0].lower() == stem.lower()):
                candidates.append(item)
        if not candidates:
            return False
        candidates[-1].InvokeVerb("undelete")
        return True
    except Exception as e:
        log.warning(f"Undo: Recycle Bin restore failed: {e}")
        return False
