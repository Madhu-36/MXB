import glob  # noqa: F401  (kept for plugins that import it from here)
import json
import os
import subprocess

from thefuzz import fuzz, process

# Windows' own tools: started by name, so they work even though most have no Start-menu shortcut
# (Notepad, Paint and Calculator are Store apps on Windows 11).
SYSTEM_APPS = {
    "notepad": "notepad", "calc": "calc", "calculator": "calc", "paint": "mspaint", "mspaint": "mspaint",
    "ms paint": "mspaint", "cmd": "cmd", "command prompt": "cmd", "explorer": "explorer",
    "file explorer": "explorer", "files": "explorer", "this pc": "explorer", "control": "control",
    "control panel": "control", "task manager": "taskmgr", "taskmgr": "taskmgr", "settings": "ms-settings:",
    "windows settings": "ms-settings:", "snipping tool": "snippingtool", "terminal": "wt", "windows terminal": "wt",
    "powershell": "powershell", "registry editor": "regedit", "device manager": "devmgmt.msc",
}
# What speech recognition writes instead of an app's name.
MISHEARD = {
    "notebook": "notepad", "note pad": "notepad", "notepads": "notepad", "not pad": "notepad", "no pad": "notepad",
    "calculate": "calculator", "calculater": "calculator", "calcutta": "calculator",
    "crome": "chrome", "chrom": "chrome", "krome": "chrome", "google chrome browser": "google chrome",
    "control pannel": "control panel", "vs code": "visual studio code", "vscode": "visual studio code",
    "v s code": "visual studio code", "spotify app": "spotify", "what's app": "whatsapp", "whats app": "whatsapp",
}


class SmartAppLauncher:
    def __init__(self):
        self.shortcuts = {}
        self._store_apps = None          # name -> AppUserModelID, loaded on the first miss
        self._index_start_menu()

    def _index_start_menu(self):
        # Index all .lnk files in common start menu locations
        paths = [
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")
        ]

        for path in paths:
            if not os.path.exists(path):
                continue
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        app_name = os.path.splitext(file)[0].lower()
                        self.shortcuts[app_name] = os.path.join(root, file)

    @staticmethod
    def clean(query: str) -> str:
        """Lowercase, no punctuation or filler words around the name ("the Spotify app" -> "spotify")."""
        q = " ".join((query or "").lower().strip().strip(".!?,").split())
        for prefix in ("the ", "my ", "app ", "application "):
            if q.startswith(prefix):
                q = q[len(prefix):]
        for suffix in (" app", " application", " please"):
            if q.endswith(suffix):
                q = q[: -len(suffix)]
        return q

    @classmethod
    def normalize(cls, query: str) -> str:
        """clean() plus the usual speech-recognition mistakes ("notebook" -> "notepad")."""
        q = cls.clean(query)
        return MISHEARD.get(q, q)

    def store_apps(self) -> dict:
        """
        Start-menu apps without a .lnk file: Microsoft Store apps (WhatsApp, Spotify, Calculator on
        Windows 11). Listed once with PowerShell's Get-StartApps, only when a name isn't found otherwise.
        """
        if self._store_apps is None:
            self._store_apps = {}
            if os.name == "nt":
                try:
                    out = subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                         "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
                        capture_output=True, text=True, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self._store_apps = parse_start_apps(out.stdout)
                except Exception:
                    pass
        return self._store_apps

    def _start(self, name: str, kind: str, target: str) -> str:
        try:
            if kind == "store":
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
            else:
                os.startfile(target)
            return f"Launched '{name}'" if kind != "system" else f"Launched {name}"
        except Exception as e:
            return f"Found '{name}' but failed to launch: {e}"

    def launch(self, query: str) -> str:
        spoken = self.clean(query)
        if not spoken:
            return "Which app should I open?"
        # 1. The user's own app with exactly this name wins over any correction.
        if spoken in self.shortcuts:
            return self._start(spoken, "shortcut", self.shortcuts[spoken])
        query = MISHEARD.get(spoken, spoken)

        # 2. Windows' built-in tools by name (also the misheard ones: "notebook" -> Notepad).
        if query in SYSTEM_APPS:
            result = self._start(query, "system", SYSTEM_APPS[query])
            if result.startswith("Launched"):
                return result

        # 3. Start-menu shortcuts: exact, then fuzzy (token-aware, so "chrome" finds "Google Chrome").
        if query in self.shortcuts:
            return self._start(query, "shortcut", self.shortcuts[query])
        if self.shortcuts:
            best_match, score = process.extractOne(query, list(self.shortcuts.keys()), scorer=fuzz.WRatio)
            if score > 70:
                return self._start(best_match, "shortcut", self.shortcuts[best_match])

        # 4. Store apps, which have no shortcut file at all.
        apps = self.store_apps()
        if apps:
            if query in apps:
                best_match, score = query, 100
            else:
                best_match, score = process.extractOne(query, list(apps.keys()), scorer=fuzz.WRatio)
            if score > 80:
                return self._start(best_match, "store", apps[best_match])

        if not self.shortcuts and not apps:
            return "No applications indexed."
        return f"Could not find an app matching '{query}'"


def parse_start_apps(stdout: str) -> dict:
    """Get-StartApps JSON (one object or a list) -> {lowercase name: AppID}."""
    try:
        data = json.loads(stdout or "[]")
    except ValueError:
        return {}
    if isinstance(data, dict):
        data = [data]
    apps = {}
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("Name") and item.get("AppID"):
            apps[str(item["Name"]).lower()] = str(item["AppID"])
    return apps
