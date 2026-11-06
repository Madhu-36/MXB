import unittest
from utils.process_manager import ProcessManager

class TestProcessManager(unittest.TestCase):

    def test_get_top_processes_structure(self):
        procs = ProcessManager.get_top_processes(limit=3)
        self.assertIsInstance(procs, list)
        self.assertLessEqual(len(procs), 3)
        if procs:
            first = procs[0]
            self.assertIn("pid", first)
            self.assertIn("name", first)
            self.assertIn("memory_mb", first)
            self.assertGreaterEqual(first["memory_mb"], 0)

    def test_critical_process_protection(self):
        res1 = ProcessManager.terminate_process("explorer.exe")
        self.assertFalse(res1["success"])
        self.assertIn("protected Windows core system process", res1["error"])

        res2 = ProcessManager.terminate_process("svchost")
        self.assertFalse(res2["success"])
        self.assertIn("protected Windows core system process", res2["error"])

        res3 = ProcessManager.terminate_process("dwm.exe")
        self.assertFalse(res3["success"])

    def test_non_existent_pid_termination(self):
        res = ProcessManager.terminate_process(99999999)
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_find_process_by_port_unused(self):
        res = ProcessManager.find_process_by_port(64321)
        # Port 64321 is an ephemeral port unlikely to have a permanent listener
        if res is not None:
            self.assertEqual(res["port"], 64321)
        else:
            self.assertIsNone(res)

if __name__ == "__main__":
    unittest.main()
