import os
from pathlib import Path

class CredentialsManager:
    @staticmethod
    def get_nvidia_api_key() -> str:
        """
        Safely retrieves the NVIDIA API key from environment or .env files
        without exposing or logging the secret value.
        """
        # 1. Process environment
        key = os.environ.get("NVIDIA_API_KEY")
        if key and key.strip():
            return key.strip()

        # 2. MXB's own .env (data folder when installed, project folder otherwise)
        from utils.paths import data_dir, APP_DIR
        for local_env in dict.fromkeys([data_dir() / '.env', APP_DIR / '.env']):
            if not local_env.exists():
                continue
            try:
                with open(local_env, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("NVIDIA_API_KEY="):
                            val = line.split("NVIDIA_API_KEY=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass

        # 3. Home directory ~/.env
        home_env = Path.home() / '.env'
        if home_env.exists():
            try:
                with open(home_env, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("NVIDIA_API_KEY="):
                            val = line.split("NVIDIA_API_KEY=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass

        # 4. Windows User Registry Environment
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as reg_key:
                val, _ = winreg.QueryValueEx(reg_key, "NVIDIA_API_KEY")
                if val and val.strip():
                    return val.strip()
        except Exception:
            pass

        return ""

    @staticmethod
    def has_nvidia_api_key() -> bool:
        return bool(CredentialsManager.get_nvidia_api_key())
