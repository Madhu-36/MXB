import unittest
import tempfile
import json
from pathlib import Path
from utils.vault import SecureVault

class TestSecureVault(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.vault_file = Path(self.tmp_dir.name) / "test_vault.enc"
        self.vault = SecureVault(str(self.vault_file))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_store_and_retrieve_secret(self):
        key = "openai_api_key"
        val = "sk-proj-test1234567890abcdef"
        self.assertTrue(self.vault.set_secret(key, val))

        retrieved = self.vault.get_secret(key)
        self.assertEqual(retrieved, val)

    def test_ciphertext_is_encrypted_on_disk(self):
        key = "master_token"
        secret_text = "SuperSecretPassword123!"
        self.vault.set_secret(key, secret_text)

        # Read the raw file directly from disk
        raw_text = self.vault_file.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        self.assertIn("master_token", data)
        # Ensure plaintext is never exposed in the file
        self.assertNotIn(secret_text, raw_text)

    def test_list_and_has_secrets(self):
        self.vault.set_secret("token_a", "111")
        self.vault.set_secret("token_b", "222")

        self.assertTrue(self.vault.has_secret("token_a"))
        self.assertTrue(self.vault.has_secret("token_b"))
        self.assertFalse(self.vault.has_secret("token_missing"))

        keys = self.vault.list_keys()
        self.assertEqual(keys, ["token_a", "token_b"])

    def test_delete_secret(self):
        self.vault.set_secret("temp_pin", "9988")
        self.assertTrue(self.vault.delete_secret("temp_pin"))
        self.assertFalse(self.vault.has_secret("temp_pin"))
        self.assertIsNone(self.vault.get_secret("temp_pin"))
        self.assertFalse(self.vault.delete_secret("temp_pin"))

if __name__ == "__main__":
    unittest.main()
