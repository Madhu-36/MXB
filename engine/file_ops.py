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
