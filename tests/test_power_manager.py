import unittest
from unittest.mock import patch
from collections import namedtuple
from utils.power_manager import PowerManager

MockBattery = namedtuple("MockBattery", ["percent", "secsleft", "power_plugged"])

class TestPowerManager(unittest.TestCase):

    def test_live_battery_status_structure(self):
        status = PowerManager.get_battery_status()
        self.assertIsInstance(status, dict)
        self.assertIn("has_battery", status)
        self.assertIn("percent", status)
        self.assertIn("power_plugged", status)
        self.assertIn("status_level", status)
        self.assertIn("summary", status)

    @patch("psutil.sensors_battery", return_value=None)
    def test_desktop_system_fallback(self, mock_battery):
        status = PowerManager.get_battery_status()
        self.assertFalse(status["has_battery"])
        self.assertEqual(status["status_level"], "desktop")
        self.assertIn("Desktop workstation", status["summary"])

    @patch("psutil.sensors_battery", return_value=MockBattery(percent=98, secsleft=-2, power_plugged=True))
    def test_battery_full_charging(self, mock_battery):
        status = PowerManager.get_battery_status()
        self.assertTrue(status["has_battery"])
        self.assertTrue(status["power_plugged"])
        self.assertEqual(status["status_level"], "full")
        self.assertIn("98 percent", status["summary"])

    @patch("psutil.sensors_battery", return_value=MockBattery(percent=18, secsleft=3600, power_plugged=False))
    def test_battery_low_power_saving(self, mock_battery):
        status = PowerManager.get_battery_status()
        self.assertTrue(status["has_battery"])
        self.assertFalse(status["power_plugged"])
        self.assertEqual(status["status_level"], "low")
        self.assertTrue(PowerManager.is_power_saving_needed())

    @patch("psutil.sensors_battery", return_value=MockBattery(percent=8, secsleft=1200, power_plugged=False))
    def test_battery_critical(self, mock_battery):
        status = PowerManager.get_battery_status()
        self.assertEqual(status["status_level"], "critical")
        self.assertTrue(PowerManager.is_power_saving_needed())

if __name__ == "__main__":
    unittest.main()
