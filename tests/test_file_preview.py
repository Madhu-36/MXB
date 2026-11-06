import unittest
import tempfile
from pathlib import Path
from engine.file_ops import FileOperationsManager

class TestFilePreview(unittest.TestCase):

    def setUp(self):
        self.file_ops = FileOperationsManager()
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_text_file_preview(self):
        sample_file = self.base_path / "sample.txt"
        lines = [f"Line {i} content" for i in range(20)]
        sample_file.write_text("\n".join(lines), encoding="utf-8")

        res = self.file_ops.preview_file(str(sample_file), max_lines=5)
        self.assertFalse(res["is_binary"])
        self.assertEqual(res["lines_shown"], 5)
        self.assertEqual(res["total_lines"], 20)
        self.assertTrue(res["truncated"])
        self.assertIn("Line 0 content", res["content"])
        self.assertIn("Line 4 content", res["content"])
        self.assertNotIn("Line 10 content", res["content"])

    def test_binary_file_detection(self):
        bin_file = self.base_path / "binary_sample.bin"
        bin_file.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00")

        res = self.file_ops.preview_file(str(bin_file))
        self.assertTrue(res["is_binary"])
        self.assertIn("Binary file", res["content"])

    def test_non_existent_file_preview(self):
        res = self.file_ops.preview_file(str(self.base_path / "missing.txt"))
        self.assertIn("error", res)
        self.assertEqual(res["content"], "")

    def test_directory_tree_generation(self):
        sub_folder = self.base_path / "sub_folder"
        sub_folder.mkdir()
        (sub_folder / "file_a.txt").write_text("hello", encoding="utf-8")
        (self.base_path / "root_file.txt").write_text("world", encoding="utf-8")

        tree_str = self.file_ops.get_directory_tree(str(self.base_path), max_depth=2)
        self.assertIn("[DIR]", tree_str)
        self.assertIn("sub_folder", tree_str)
        self.assertIn("file_a.txt", tree_str)
        self.assertIn("root_file.txt", tree_str)

    def test_missing_directory_tree(self):
        tree_str = self.file_ops.get_directory_tree(str(self.base_path / "not_found_dir"))
        self.assertIn("Directory not found", tree_str)

if __name__ == "__main__":
    unittest.main()
