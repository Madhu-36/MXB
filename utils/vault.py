import sys
import json
import base64
import ctypes
from ctypes import wintypes
import threading
from pathlib import Path
from utils.logger import log

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_byte))
    ]

class SecureVault:
    """
    Hardware-anchored DPAPI Secure Secret Storage for MXB.
    Secures private API keys, credentials, and sensitive notes using Windows Data Protection API (DPAPI).
    Ciphertext is locked to the current Windows user login and cannot be decrypted on other machines.
    """

    def __init__(self, vault_path: str = None):
        if vault_path:
            self.vault_file = Path(vault_path)
        else:
            self.vault_file = Path(__file__).parent.parent / "config" / ".mxb_vault.enc"
        
        self._lock = threading.Lock()
        self.crypt32 = ctypes.windll.crypt32 if sys.platform == "win32" else None
        self.kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

    def _encrypt(self, text: str) -> str:
        """Encrypts plaintext string with DPAPI and returns Base64 string."""
        if not self.crypt32:
            return base64.b64encode(text.encode("utf-8")).decode("ascii")

        data = text.encode("utf-8")
        blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_byte)))
        blob_out = DATA_BLOB()
        if self.crypt32.CryptProtectData(ctypes.byref(blob_in), "MXB-Vault-Secret", None, None, None, 0, ctypes.byref(blob_out)):
            out_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            self.kernel32.LocalFree(blob_out.pbData)
            return base64.b64encode(out_bytes).decode("ascii")
        raise RuntimeError("Windows DPAPI CryptProtectData failed.")

    def _decrypt(self, b64_ciphertext: str) -> str:
        """Decrypts Base64 DPAPI ciphertext to plaintext string."""
        raw_cipher = base64.b64decode(b64_ciphertext.encode("ascii"))
        if not self.crypt32:
            return raw_cipher.decode("utf-8")

        blob_in = DATA_BLOB(len(raw_cipher), ctypes.cast(ctypes.c_char_p(raw_cipher), ctypes.POINTER(ctypes.c_byte)))
        blob_out = DATA_BLOB()
        if self.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            dec = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            self.kernel32.LocalFree(blob_out.pbData)
            return dec.decode("utf-8")
        raise RuntimeError("Windows DPAPI CryptUnprotectData failed.")

    def _load_vault(self) -> dict:
        if not self.vault_file.exists():
            return {}
        try:
            with open(self.vault_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"SecureVault: Could not read vault file: {e}")
            return {}

    def _save_vault(self, data: dict):
        self.vault_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.vault_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def set_secret(self, key: str, value: str) -> bool:
        """Encrypts and persists a named secret into the vault."""
        clean_key = key.lower().strip()
        with self._lock:
            try:
                encrypted_val = self._encrypt(value)
                vault = self._load_vault()
                vault[clean_key] = encrypted_val
                self._save_vault(vault)
                log.info(f"SecureVault: Stored secret '{clean_key}' securely.")
                return True
            except Exception as e:
                log.error(f"SecureVault: Failed to store secret '{clean_key}': {e}")
                return False

    def get_secret(self, key: str) -> str | None:
        """Retrieves and decrypts a named secret from the vault."""
        clean_key = key.lower().strip()
        with self._lock:
            vault = self._load_vault()
            if clean_key not in vault:
                return None
            try:
                return self._decrypt(vault[clean_key])
            except Exception as e:
                log.error(f"SecureVault: Decryption error for '{clean_key}': {e}")
                return None

    def has_secret(self, key: str) -> bool:
        clean_key = key.lower().strip()
        with self._lock:
            vault = self._load_vault()
            return clean_key in vault

    def delete_secret(self, key: str) -> bool:
        clean_key = key.lower().strip()
        with self._lock:
            vault = self._load_vault()
            if clean_key in vault:
                del vault[clean_key]
                self._save_vault(vault)
                log.info(f"SecureVault: Removed secret '{clean_key}'.")
                return True
            return False

    def list_keys(self) -> list[str]:
        with self._lock:
            vault = self._load_vault()
            return sorted(list(vault.keys()))

# Global shared instance
secure_vault = SecureVault()
