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

    def resolve_path(self, path_str: str) -> Path:
        """Resolves friendly folder names (e.g. 'desktop/test') to absolute Path objects."""
        clean = path_str.strip().strip('"').strip("'")
        lower = clean.lower()

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
        try:
            target.mkdir(parents=True, exist_ok=True)
            log.info(f"FileOps: Created directory '{target}'")
            return f"Created folder at: {target.name}"
        except Exception as e:
            log.error(f"FileOps: Failed to create folder '{target}': {e}")
            return f"Failed to create folder: {e}"

    def create_file(self, file_path: str, content: str = "") -> str:
        """Creates or overwrites a text file with content."""
        target = self.resolve_path(file_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
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
            return f"Path does not exist: {target_path}"

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

    def delete_file(self, target_path: str) -> str:
        """Safely removes a file."""
        target = self.resolve_path(target_path)
        if not target.exists():
            return f"File does not exist: {target_path}"

        try:
            if target.is_dir():
                shutil.rmtree(target)
                log.info(f"FileOps: Removed directory '{target}'")
                return f"Deleted folder: {target.name}"
            else:
                target.unlink()
                log.info(f"FileOps: Removed file '{target}'")
                return f"Deleted file: {target.name}"
        except Exception as e:
            log.error(f"FileOps: Failed to delete '{target}': {e}")
            return f"Failed to delete {target.name}: {e}"

    def search_files(self, pattern: str, root_path: str = "desktop", max_results: int = 15) -> list[str]:
        """Searches for files matching a glob pattern starting from root_path."""
        base = self.resolve_path(root_path)
        if not base.exists() or not base.is_dir():
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
