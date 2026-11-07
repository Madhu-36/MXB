import os
import shutil
import subprocess
from pathlib import Path
from utils.logger import log

class FileOperationsManager:
    """
    File system automation for MXB.
    Safely navigates directories, creates files/folders, opens Explorer windows,
    lists folder contents, and manages file lifecycle.
    """

    FOLDER_ALIASES = {
        "desktop": Path.home() / "Desktop",
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "pictures": Path.home() / "Pictures",
        "music": Path.home() / "Music",
        "videos": Path.home() / "Videos",
        "home": Path.home(),
        "projects": Path.home() / "OneDrive" / "Desktop" / "PROJECTS"
    }

    SKIP_DIRS = {
        "node_modules", ".git", "__pycache__", ".venv", "venv", "$recycle.bin", "system volume information",
        "windows", "appdata", "program files", "program files (x86)", "programdata", ".cache", "site-packages",
    }
    TEXT_EXTENSIONS = {
        ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".log", ".ini", ".cfg", ".toml",
        ".yaml", ".yml", ".html", ".css", ".xml", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sql",
        ".sh", ".bat", ".ps1", ".tex", ".rtf",
    }

    def __init__(self, access=None, journal=None):
        """
        access: a safety.permissions.FileAccessManager. When given (as the executor
        does), every operation is checked against the user's granted folders.
        When None (direct library use / unit tests), no permission checks run.
        """
        self.access = access
        self.journal = journal  # engine.undo.UndoJournal (optional): makes file actions undoable

    def _record(self, kind: str, **data):
        if self.journal is not None:
            try:
                self.journal.record(kind, **data)
            except Exception as e:
                log.warning(f"FileOps: undo journal error: {e}")

    def _guard(self, path, write: bool = False) -> str | None:
        if self.access is None:
            return None
        ok, reason = self.access.check(path, write=write)
        return None if ok else reason

    def resolve_path(self, path_str: str) -> Path:
        """Resolves friendly folder names (e.g. 'desktop/test') to absolute Path objects."""
        clean = str(path_str).strip().strip('"').strip("'")
        lower = clean.lower()

        # Spoken drive names: "d drive", "drive d", "D:" -> D:\
        from safety.permissions import parse_location
        spoken = parse_location(clean)
        if spoken != clean and len(spoken) == 3 and spoken[1:] == ":\\":
            return Path(spoken)

        for alias, resolved in self.FOLDER_ALIASES.items():
            if lower == alias:
                return resolved
            if lower.startswith(alias + "/") or lower.startswith(alias + "\\"):
                remainder = clean[len(alias) + 1:]
                return resolved / remainder

        # If it's already an absolute path
        p = Path(clean)
        if p.is_absolute():
            return p

        # If it exists relative to current working directory
        cwd_relative = Path.cwd() / clean
        if cwd_relative.exists():
            return cwd_relative

        # Default relative to Desktop
        return (Path.home() / "Desktop") / clean

    def create_folder(self, folder_path: str) -> str:
        """Creates a directory at the given path."""
        target = self.resolve_path(folder_path)
        denied = self._guard(target, write=True)
        if denied:
            return denied
        try:
            existed = target.exists()
            target.mkdir(parents=True, exist_ok=True)
            if not existed:
                self._record("create", path=target)
            log.info(f"FileOps: Created directory '{target}'")
            return f"Created folder at: {target.name}"
        except Exception as e:
            log.error(f"FileOps: Failed to create folder '{target}': {e}")
            return f"Failed to create folder: {e}"

    def create_file(self, file_path: str, content: str = "") -> str:
        """Creates or overwrites a text file with content."""
        target = self.resolve_path(file_path)
        denied = self._guard(target, write=True)
        if denied:
            return denied
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and self.journal is not None:
                backup = self.journal.backup_before_overwrite(target)
                if backup:
                    self._record("overwrite", path=target, backup=backup)
            elif not target.exists():
                self._record("create", path=target)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            log.info(f"FileOps: Created file '{target}' ({len(content)} chars)")
            return f"Created file '{target.name}'"
        except Exception as e:
            log.error(f"FileOps: Failed to write file '{target}': {e}")
            return f"Failed to create file: {e}"

    def open_path(self, target_path: str) -> str:
        """Opens a file or directory in the default Windows application or File Explorer."""
        target = self.resolve_path(target_path)
        if not target.exists():
            matches = self.find_files(Path(str(target_path)).name, max_results=1)
            if not matches:
                return f"Path does not exist: {target_path}"
            target = Path(matches[0])
        denied = self._guard(target)
        if denied:
            return denied

        try:
            os.startfile(str(target))
            log.info(f"FileOps: Opened path '{target}'")
            return f"Opened {target.name}"
        except Exception as e:
            log.error(f"FileOps: Failed to open path '{target}': {e}")
            return f"Failed to open {target.name}: {e}"

    def list_directory(self, folder_name: str = "desktop") -> str:
        """Lists files and folders inside a given directory."""
        target = self.resolve_path(folder_name)
        if not target.exists() or not target.is_dir():
            return f"Folder not found: {folder_name}"
        denied = self._guard(target)
        if denied:
            return denied

        try:
            items = list(target.iterdir())
            if not items:
                return f"The {target.name} folder is currently empty."

            # Top 10 items
            sample = items[:10]
            names = [f"📁 {item.name}" if item.is_dir() else f"📄 {item.name}" for item in sample]
            summary = ", ".join(names)
            total = len(items)
            msg = f"{target.name} ({total} items): {summary}"
            if total > 10:
                msg += f" and {total - 10} more."
            log.info(f"FileOps: Listed directory '{target}': {total} items")
            return msg
        except Exception as e:
            log.error(f"FileOps: Failed to list directory '{target}': {e}")
            return f"Failed to list folder: {e}"

    def delete_file(self, target_path: str, permanent: bool = False) -> str:
        """Deletes a file or folder. Default: send to the Recycle Bin so it can be restored."""
        target = self.resolve_path(target_path)
        if not target.exists():
            return f"File does not exist: {target_path}"
        denied = self._guard(target, write=True)
        if denied:
            return denied

        try:
            if not permanent:
                if self._send_to_recycle_bin(target):
                    self._record("recycle", path=target)
                    log.info(f"FileOps: Recycled '{target}'")
                    return f"Moved {target.name} to the Recycle Bin."
                return (f"I couldn't use the Recycle Bin for {target.name}, so I didn't delete it. "
                        "Say 'permanently delete' if you really want it gone.")
            self._record("permanent_delete", path=target)
            if target.is_dir():
                shutil.rmtree(target)
                log.info(f"FileOps: Permanently removed directory '{target}'")
                return f"Permanently deleted folder: {target.name}"
            target.unlink()
            log.info(f"FileOps: Permanently removed file '{target}'")
            return f"Permanently deleted file: {target.name}"
        except Exception as e:
            log.error(f"FileOps: Failed to delete '{target}': {e}")
            return f"Failed to delete {target.name}: {e}"

    @staticmethod
    def _send_to_recycle_bin(target: Path) -> bool:
        try:
            from send2trash import send2trash
            send2trash(str(target))
            return True
        except ImportError:
            pass
        except Exception as e:
            log.warning(f"FileOps: send2trash failed: {e}")
            return False
        # Native Windows fallback: SHFileOperationW with FOF_ALLOWUNDO
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                            ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

            FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
            op = SHFILEOPSTRUCTW()
            op.wFunc = FO_DELETE
            op.pFrom = str(target) + "\0"
            op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
            return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not target.exists()
        except Exception as e:
            log.warning(f"FileOps: native recycle failed: {e}")
            return False

    # ------------------------------------------------------------------ copy / move / rename
    def _resolve_destination(self, src: Path, dest_str: str) -> Path:
        dest = self.resolve_path(dest_str)
        if dest.exists() and dest.is_dir():
            return dest / src.name
        return dest

    def copy_path(self, source: str, destination: str) -> str:
        src = self.resolve_path(source)
        if not src.exists():
            return f"Source not found: {source}"
        dest = self._resolve_destination(src, destination)
        for p, w in ((src, False), (dest, True)):
            denied = self._guard(p, write=w)
            if denied:
                return denied
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_file() and self.journal is not None:
                backup = self.journal.backup_before_overwrite(dest)
                if backup:
                    self._record("overwrite", path=dest, backup=backup)
            elif not dest.exists():
                self._record("copy", dst=dest)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            log.info(f"FileOps: Copied '{src}' -> '{dest}'")
            return f"Copied {src.name} to {dest.parent}."
        except Exception as e:
            return f"Failed to copy {src.name}: {e}"

    def move_path(self, source: str, destination: str) -> str:
        src = self.resolve_path(source)
        if not src.exists():
            return f"Source not found: {source}"
        dest = self._resolve_destination(src, destination)
        for p in (src, dest):
            denied = self._guard(p, write=True)
            if denied:
                return denied
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            self._record("move", src=src, dst=dest)
            log.info(f"FileOps: Moved '{src}' -> '{dest}'")
            return f"Moved {src.name} to {dest.parent}."
        except Exception as e:
            return f"Failed to move {src.name}: {e}"

    def rename_path(self, source: str, new_name: str) -> str:
        src = self.resolve_path(source)
        if not src.exists():
            return f"Not found: {source}"
        new_name = Path(new_name.strip().strip('"')).name
        if not Path(new_name).suffix and src.suffix:
            new_name += src.suffix  # "rename report to final" keeps .docx
        dest = src.with_name(new_name)
        denied = self._guard(src, write=True)
        if denied:
            return denied
        if dest.exists():
            return f"{dest.name} already exists in that folder."
        try:
            src.rename(dest)
            self._record("rename", src=src, dst=dest)
            return f"Renamed {src.name} to {dest.name}."
        except Exception as e:
            return f"Failed to rename {src.name}: {e}"

    def destination_exists(self, source: str, destination: str) -> tuple[bool, str]:
        src = self.resolve_path(source)
        dest = self._resolve_destination(src, destination)
        return dest.exists(), str(dest)

    # ------------------------------------------------------------------ find & read
    def search_roots(self) -> list[Path]:
        if self.access is not None:
            if self.access.full_access and os.name == "nt":
                import string
                drives = [Path(f"{d}:\\") for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
                return drives
            roots = [Path(r) for r in self.access.allowed_roots()]
        else:
            roots = [p for p in self.FOLDER_ALIASES.values()]
        seen, out = set(), []
        for r in roots:
            key = os.path.normcase(str(r))
            if key not in seen and r.exists():
                seen.add(key)
                out.append(r)
        return out

    def find_files(self, query: str, root: str | None = None, max_results: int = 20,
                   time_budget: float = 6.0) -> list[str]:
        """
        Finds files/folders whose name matches query (substring, all words, or glob).
        Walks granted roots (or `root`) breadth-first with a time budget, skipping
        system/vendor folders. Exact-name matches are returned first.
        """
        import fnmatch
        import time as _time
        q = (query or "").strip().strip('"').lower()
        if not q:
            return []
        is_glob = any(ch in q for ch in "*?[")
        words = [w for w in q.replace("_", " ").replace("-", " ").split() if w]
        roots = [self.resolve_path(root)] if root else self.search_roots()
        if root:
            denied = self._guard(roots[0])
            if denied:
                return []
        deadline = _time.time() + time_budget
        exact, partial = [], []
        for base in roots:
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                if _time.time() > deadline:
                    break
                dirnames[:] = [d for d in dirnames if d.lower() not in self.SKIP_DIRS and not d.startswith(".")]
                for name in dirnames + filenames:
                    low = name.lower()
                    stem = os.path.splitext(low)[0]
                    hit = fnmatch.fnmatch(low, q) if is_glob else (
                        q in low or (words and all(w in low.replace("_", " ").replace("-", " ") for w in words)))
                    if not hit:
                        continue
                    full = os.path.join(dirpath, name)
                    (exact if (low == q or stem == q) else partial).append(full)
                if len(exact) >= max_results:
                    break
            if len(exact) >= max_results or _time.time() > deadline:
                break
        partial.sort(key=lambda p: (len(os.path.basename(p)), p))
        return (exact + partial)[:max_results]

    def locate(self, path_or_name: str) -> Path | None:
        """Resolves a path, or finds a file by name if the path doesn't exist."""
        target = self.resolve_path(path_or_name)
        if target.exists():
            return target
        matches = self.find_files(Path(str(path_or_name)).name, max_results=1, time_budget=4.0)
        return Path(matches[0]) if matches else None

    def read_file_text(self, file_path: str, max_chars: int = 6000) -> dict:
        """Extracts readable text from text/code, PDF (pypdf) and DOCX (python-docx) files."""
        target = self.locate(file_path)
        if target is None or not target.is_file():
            return {"error": f"File not found: {file_path}"}
        denied = self._guard(target)
        if denied:
            return {"error": denied}
        ext = target.suffix.lower()
        try:
            if ext == ".pdf":
                try:
                    from pypdf import PdfReader
                except ImportError:
                    return {"error": "Reading PDFs needs the 'pypdf' package (pip install pypdf)."}
                reader = PdfReader(str(target))
                parts, total = [], 0
                for page in reader.pages:
                    t = page.extract_text() or ""
                    parts.append(t)
                    total += len(t)
                    if total >= max_chars:
                        break
                text = "\n".join(parts)
            elif ext == ".docx":
                try:
                    import docx
                except ImportError:
                    return {"error": "Reading Word files needs the 'python-docx' package (pip install python-docx)."}
                text = "\n".join(p.text for p in docx.Document(str(target)).paragraphs)
            else:
                preview = self.preview_file(str(target), max_lines=100000, max_bytes=max_chars * 2)
                if preview.get("error"):
                    return {"error": preview["error"]}
                if preview.get("is_binary"):
                    return {"error": f"{target.name} is a binary file, so I can't read it as text."}
                text = preview.get("content", "")
            return {"path": str(target), "name": target.name, "text": text[:max_chars],
                    "truncated": len(text) > max_chars}
        except Exception as e:
            return {"error": f"Could not read {target.name}: {e}"}

    def search_files(self, pattern: str, root_path: str = "desktop", max_results: int = 15) -> list[str]:
        """Searches for files matching a glob pattern starting from root_path."""
        base = self.resolve_path(root_path)
        if not base.exists() or not base.is_dir() or self._guard(base):
            return []
        try:
            matches = []
            for p in base.rglob(pattern):
                matches.append(str(p))
                if len(matches) >= max_results:
                    break
            return matches
        except Exception as e:
            log.error(f"FileOps: Search failed: {e}")
            return []

    def get_file_hash(self, file_path: str, algorithm: str = "sha256") -> str | None:
        """Computes the cryptographic hash (SHA-256 or MD5) of a target file."""
        import hashlib
        target = self.resolve_path(file_path)
        if not target.exists() or not target.is_file():
            return None
        try:
            hasher = hashlib.sha256() if algorithm.lower() == "sha256" else hashlib.md5()
            with open(target, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            log.error(f"FileOps: Hash calculation failed: {e}")
            return None

    def preview_file(self, file_path: str, max_lines: int = 15, max_bytes: int = 32768) -> dict:
        """
        Safely inspects a file and previews its leading lines.
        Detects binary files automatically to prevent terminal corruption.
        """
        target = self.resolve_path(file_path)
        denied = self._guard(target)
        if denied:
            return {"error": denied, "path": str(target), "is_binary": False, "content": ""}
        if not target.exists() or not target.is_file():
            return {
                "error": f"File does not exist: {file_path}",
                "path": str(target),
                "is_binary": False,
                "content": ""
            }

        try:
            size = target.stat().st_size
            with open(target, "rb") as f:
                header = f.read(min(1024, size))
                if b"\x00" in header:
                    return {
                        "path": str(target),
                        "name": target.name,
                        "size_bytes": size,
                        "is_binary": True,
                        "content": f"[Binary file: {target.name} ({size} bytes)]",
                        "truncated": False
                    }

                f.seek(0)
                raw_data = f.read(max_bytes)

            try:
                text_content = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                text_content = raw_data.decode("latin-1", errors="replace")

            lines = text_content.splitlines()
            preview_lines = lines[:max_lines]
            is_truncated = len(lines) > max_lines or size > max_bytes

            return {
                "path": str(target),
                "name": target.name,
                "size_bytes": size,
                "is_binary": False,
                "lines_shown": len(preview_lines),
                "total_lines": len(lines),
                "truncated": is_truncated,
                "content": "\n".join(preview_lines)
            }
        except Exception as e:
            log.error(f"FileOps: Preview failed for '{target}': {e}")
            return {
                "error": str(e),
                "path": str(target),
                "is_binary": False,
                "content": ""
            }

    def get_directory_tree(self, folder_path: str = "desktop", max_depth: int = 2, max_items_per_dir: int = 15) -> str:
        """
        Generates an ASCII hierarchy tree for the specified directory up to max_depth.
        """
        target = self.resolve_path(folder_path)
        if not target.exists() or not target.is_dir():
            return f"Directory not found: {folder_path}"
        denied = self._guard(target)
        if denied:
            return denied

        tree_lines = [f"[DIR] {target.name}/"]

        def _walk(curr_dir: Path, depth: int, prefix: str):
            if depth > max_depth:
                return
            try:
                entries = sorted(list(curr_dir.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                tree_lines.append(f"{prefix}\\-- [Permission Denied]")
                return

            visible_entries = entries[:max_items_per_dir]
            for idx, entry in enumerate(visible_entries):
                is_last = (idx == len(visible_entries) - 1) and (len(entries) <= max_items_per_dir)
                connector = "\\-- " if is_last else "+-- "
                tag = "[DIR] " if entry.is_dir() else "      "
                tree_lines.append(f"{prefix}{connector}{tag}{entry.name}")
                if entry.is_dir() and depth < max_depth:
                    new_prefix = prefix + ("    " if is_last else "|   ")
                    _walk(entry, depth + 1, new_prefix)

            if len(entries) > max_items_per_dir:
                tree_lines.append(f"{prefix}\\-- ... and {len(entries) - max_items_per_dir} more items")

        _walk(target, 1, "")
        return "\n".join(tree_lines)
