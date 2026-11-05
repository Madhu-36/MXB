import unittest
from engine.executor import OSExecutionManager

class TestExecutorApps(unittest.TestCase):

    def setUp(self):
        self.executor = OSExecutionManager()

    def test_list_running_apps_returns_list(self):
        apps = self.executor.list_running_apps(limit=5)
        self.assertIsInstance(apps, list)

    def test_get_app_resource_usage_structure(self):
        usage = self.executor.get_app_resource_usage("python")
        self.assertIn("app", usage)
        self.assertIn("instances", usage)
        self.assertIn("memory_mb", usage)
        self.assertIn("cpu_percent", usage)
        self.assertGreaterEqual(usage["instances"], 1)

    def test_action_execution_app_resources(self):
        res = self.executor.execute_action("app_resources", "python")
        self.assertIn("python", res)
        self.assertIn("MB RAM", res)

if __name__ == "__main__":
    unittest.main()
