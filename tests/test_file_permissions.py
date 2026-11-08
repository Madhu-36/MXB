"""File access permissions and permission-checked file operations."""
import tempfile
import unittest
from pathlib import Path

import tests._stubs  # noqa: F401
from safety.permissions import FileAccessManager, parse_location
from engine.file_ops import FileOperationsManager


class TestParseLocation(unittest.TestCase):
    def test_drive_letters(self):
        for spoken in ("d", "D drive", "drive d", "the d drive", "D:", "d:\\"):
            self.assertEqual(parse_location(spoken), "D:\\", spoken)

    def test_home_folders(self):
        self.assertTrue(parse_location("downloads").endswith("Downloads"))

    def test_plain_path_unchanged(self):
        self.assertEqual(parse_location("/srv/work"), "/srv/work")


class TestFileAccessManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.personal = base / "personal"
        self.other = base / "other"
        self.system = base / "system"
        for d in (self.personal, self.other, self.system):
            d.mkdir()
        self.store = base / "perms.json"
        self.fam = FileAccessManager(store_path=self.store, default_roots=[self.personal],
                                     protected_roots=[self.system])

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_scope(self):
        self.assertTrue(self.fam.can_read(self.personal / "a.txt"))
        self.assertFalse(self.fam.can_read(self.other / "a.txt"))

    def test_grant_and_revoke(self):
        self.fam.grant(str(self.other))
        self.assertTrue(self.fam.can_read(self.other / "deep" / "x.txt"))
        self.fam.revoke(str(self.other))
        self.assertFalse(self.fam.can_read(self.other / "x.txt"))

    def test_full_access_still_protects_system(self):
        self.fam.grant("all")
        self.assertTrue(self.fam.can_read(self.system / "kernel.dll"))
        self.assertFalse(self.fam.can_write(self.system / "kernel.dll"))
        ok, reason = self.fam.check(self.system / "kernel.dll", write=True)
        self.assertFalse(ok)
        self.assertIn("protected", reason)

    def test_persistence(self):
        self.fam.grant(str(self.other))
        reloaded = FileAccessManager(store_path=self.store, default_roots=[self.personal], protected_roots=[self.system])
        self.assertTrue(reloaded.can_read(self.other / "x"))

    def test_denied_message_suggests_grant(self):
        ok, reason = self.fam.check(self.other / "x.txt")
        self.assertFalse(ok)
        self.assertIn("give access", reason)


class TestPathCase(unittest.TestCase):
    """Windows normcase lowercases whole paths. Comparisons may use that; paths shown to the user must not."""

    def test_found_files_keep_their_real_letter_case(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(prefix="MXB_Case_") as tmp:
            home = Path(tmp)
            (home / "Projects").mkdir()
            target = home / "Projects" / "Old_Draft.txt"
            target.write_text("x")
            with mock.patch("os.path.normcase", side_effect=lambda p: p.lower()):   # behave like Windows
                access = FileAccessManager(store_path=home / "p.json", default_roots=[home], protected_roots=[])
                found = FileOperationsManager(access=access).find_files("old_draft.txt")
                self.assertTrue(access.can_read(str(target).upper()))          # matching stays case-insensitive
            self.assertEqual(found, [str(target)])                             # not "/tmp/mxb_case_x/Projects/..."


class TestGuardedFileOps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.allowed = base / "allowed"
        self.blocked = base / "blocked"
        self.allowed.mkdir()
        self.blocked.mkdir()
        self.fam = FileAccessManager(store_path=base / "p.json", default_roots=[self.allowed], protected_roots=[])
        self.ops = FileOperationsManager(access=self.fam)
        (self.allowed / "Quarterly Report.txt").write_text("Revenue grew 12% this quarter.", encoding="utf-8")
        (self.blocked / "secret.txt").write_text("hidden", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_blocked_outside_scope(self):
        res = self.ops.read_file_text(str(self.blocked / "secret.txt"))
        self.assertIn("don't have access", res["error"])

    def test_find_and_read_inside_scope(self):
        hits = self.ops.find_files("quarterly report")
        self.assertEqual(len(hits), 1)
        res = self.ops.read_file_text(hits[0])
        self.assertIn("Revenue grew", res["text"])

    def test_find_never_returns_blocked_files(self):
        self.assertEqual(self.ops.find_files("secret"), [])

    def test_copy_move_rename(self):
        src = self.allowed / "Quarterly Report.txt"
        sub = self.allowed / "archive"
        sub.mkdir()
        self.assertIn("Copied", self.ops.copy_path(str(src), str(sub)))
        self.assertTrue((sub / src.name).exists())
        self.assertIn("Renamed", self.ops.rename_path(str(sub / src.name), "Q3"))
        self.assertTrue((sub / "Q3.txt").exists())
        self.assertIn("Moved", self.ops.move_path(str(sub / "Q3.txt"), str(self.allowed)))
        self.assertTrue((self.allowed / "Q3.txt").exists())

    def test_move_into_blocked_folder_denied(self):
        res = self.ops.move_path(str(self.allowed / "Quarterly Report.txt"), str(self.blocked))
        self.assertIn("don't have access", res)
        self.assertTrue((self.allowed / "Quarterly Report.txt").exists())

    def test_permanent_delete(self):
        f = self.allowed / "junk.tmp"
        f.write_text("x")
        self.assertIn("Permanently deleted", self.ops.delete_file(str(f), permanent=True))
        self.assertFalse(f.exists())

    def test_default_delete_never_silently_destroys(self):
        f = self.allowed / "keep.tmp"
        f.write_text("x")
        res = self.ops.delete_file(str(f))
        # Either it went to the Recycle Bin, or it was refused; it is never unlinked permanently.
        self.assertTrue("Recycle Bin" in res or "didn't delete" in res, res)


if __name__ == "__main__":
    unittest.main()
