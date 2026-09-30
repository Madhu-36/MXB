import os
import glob
from thefuzz import process

class SmartAppLauncher:
    def __init__(self):
        self.shortcuts = {}
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

    def launch(self, query: str) -> str:
        query = query.lower().strip()
        
        # Direct shell fallback for things like 'notepad', 'calc'
        if query in ["notepad", "calc", "cmd", "explorer"]:
            try:
                os.startfile(query)
                return f"Launched {query} via system path"
            except Exception:
                pass
                
        if not self.shortcuts:
            return "No applications indexed."
            
        # Fuzzy match
        best_match, score = process.extractOne(query, self.shortcuts.keys())
        
        if score > 70:
            target_path = self.shortcuts[best_match]
            try:
                os.startfile(target_path)
                return f"Launched '{best_match}'"
            except Exception as e:
                return f"Found '{best_match}' but failed to launch: {e}"
        else:
            return f"Could not find an app matching '{query}'"
