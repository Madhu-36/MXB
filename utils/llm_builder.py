import os
import hashlib
import subprocess
from pathlib import Path

class LLMBuilder:
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        self.modelfile_path = self.base_dir / "llm" / "Modelfile"
        self.hash_path = self.base_dir / "llm" / ".modelfile_hash"

    def _get_current_hash(self) -> str:
        if not self.modelfile_path.exists():
            return ""
        with open(self.modelfile_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _get_saved_hash(self) -> str:
        if not self.hash_path.exists():
            return ""
        with open(self.hash_path, "r") as f:
            return f.read().strip()

    def _save_hash(self, new_hash: str):
        with open(self.hash_path, "w") as f:
            f.write(new_hash)

    def ensure_build(self):
        print("[LLM Builder] Checking mxb-brain model status...")
        current_hash = self._get_current_hash()
        saved_hash = self._get_saved_hash()
        
        if current_hash != saved_hash:
            print("[LLM Builder] Modelfile changes detected. Rebuilding mxb-brain... This may take a minute.")
            try:
                subprocess.run(
                    ["ollama", "create", "mxb-brain", "-f", "Modelfile"],
                    cwd=str(self.base_dir / "llm"),
                    check=True,
                    stdout=subprocess.DEVNULL
                )
                self._save_hash(current_hash)
                print("[LLM Builder] Successfully rebuilt mxb-brain!")
            except Exception as e:
                print(f"[LLM Builder] Failed to build model: {e}")
        else:
            print("[LLM Builder] mxb-brain is up to date.")
