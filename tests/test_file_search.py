import os
import unittest
from pathlib import Path
from engine.file_ops import FileOperationsManager

class TestFileSearch(unittest.TestCase):

    def setUp(self):
        self.ops = FileOperationsManager()
        self.test_dir = Path(__file__).parent / "_test_temp_files"
        self.test_dir.mkdir(exist_ok=True)
        self.test_file = self.test_dir / "sample.txt"
        self.test_file.write_text("Hello MXB FileOps Test", encoding="utf-8")

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()
        if self.test_dir.exists():
            self.test_dir.rmdir()

    def test_search_files_finds_created_sample(self):
        results = self.ops.search_files("*.txt", str(self.test_dir))
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any("sample.txt" in r for r in results))

    def test_file_hash_computation(self):
        sha256 = self.ops.get_file_hash(str(self.test_file), "sha256")
        self.assertIsNotNone(sha256)
        self.assertEqual(len(sha256), 64)

        md5 = self.ops.get_file_hash(str(self.test_file), "md5")
        self.assertIsNotNone(md5)
        self.assertEqual(len(md5), 32)

    def test_nonexistent_file_hash_returns_none(self):
        h = self.ops.get_file_hash("nonexistent_file_xyz123.bin")
        self.assertIsNone(h)

if __name__ == "__main__":
    unittest.main()
