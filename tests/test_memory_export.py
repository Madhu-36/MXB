import json
import unittest
from pathlib import Path
from engine.memory import memory_bank

class TestMemoryExport(unittest.TestCase):

    def setUp(self):
        self.tmp_export = Path(__file__).parent / "_temp_mem_export.json"

    def tearDown(self):
        if self.tmp_export.exists():
            self.tmp_export.unlink()

    def test_export_creates_valid_json_file(self):
        memory_bank.remember("Test unique fact for export verification 987")
        out_path = memory_bank.export_json(str(self.tmp_export))
        self.assertTrue(Path(out_path).exists())

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("memories", data)
        self.assertIn("version", data)
        self.assertTrue(any("Test unique fact for export" in m for m in data["memories"]))

    def test_import_json_adds_facts(self):
        import uuid
        uid = str(uuid.uuid4())[:8]
        mock_facts = {
            "version": "2.1",
            "memories": [
                f"Fresh imported fact alpha {uid}",
                f"Fresh imported fact beta {uid}"
            ]
        }
        with open(self.tmp_export, "w", encoding="utf-8") as f:
            json.dump(mock_facts, f)

        imported = memory_bank.import_json(str(self.tmp_export))
        self.assertEqual(imported, 2)

        # Re-importing same facts should result in 0 new (deduplicated)
        reimported = memory_bank.import_json(str(self.tmp_export))
        self.assertEqual(reimported, 0)

if __name__ == "__main__":
    unittest.main()
