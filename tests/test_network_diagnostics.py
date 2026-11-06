import unittest
import socket
from unittest.mock import patch, MagicMock
from utils.diagnostics import SystemDiagnostics

class TestNetworkDiagnostics(unittest.TestCase):

    def test_live_network_probe_structure(self):
        diag = SystemDiagnostics.check_network_rtt(timeout=2.0)
        self.assertIsInstance(diag, dict)
        self.assertIn("connected", diag)
        self.assertIn("target", diag)
        self.assertIn("rating", diag)
        self.assertIn(diag["rating"], ["excellent", "good", "fair", "poor", "offline"])

    @patch("socket.create_connection")
    @patch("socket.gethostbyname", return_value="1.1.1.1")
    def test_rtt_excellent_rating(self, mock_dns, mock_conn):
        mock_conn.return_value.__enter__.return_value = MagicMock()
        with patch("time.perf_counter", side_effect=[0.0, 0.001, 0.010, 0.025]):
            diag = SystemDiagnostics.check_network_rtt("1.1.1.1")
            self.assertTrue(diag["connected"])
            self.assertEqual(diag["rating"], "excellent")
            self.assertLess(diag["rtt_ms"], 30.0)

    @patch("socket.create_connection")
    @patch("socket.gethostbyname", return_value="8.8.8.8")
    def test_rtt_fair_rating(self, mock_dns, mock_conn):
        mock_conn.return_value.__enter__.return_value = MagicMock()
        # Simulated 150ms latency
        with patch("time.perf_counter", side_effect=[0.0, 0.002, 0.010, 0.160]):
            diag = SystemDiagnostics.check_network_rtt("8.8.8.8")
            self.assertTrue(diag["connected"])
            self.assertEqual(diag["rating"], "fair")

    @patch("socket.create_connection", side_effect=OSError("Network unreachable"))
    def test_offline_probe(self, mock_conn):
        diag = SystemDiagnostics.check_network_rtt("192.0.2.1", timeout=0.1)
        self.assertFalse(diag["connected"])
        self.assertEqual(diag["rating"], "offline")
        self.assertIsNone(diag["rtt_ms"])

if __name__ == "__main__":
    unittest.main()
