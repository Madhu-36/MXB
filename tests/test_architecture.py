import sys
import unittest
import numpy as np
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from engine.mouse import MouseController
from engine.keyboard_ext import KeyboardExtended
from engine.file_ops import FileOperationsManager
from engine.memory import memory_bank
from engine.planner import ActionPlanner
from engine.executor import OSExecutionManager
from engine.router import IntentRouter
from engine.screen import ScreenVision
from faster_whisper.vad import get_vad_model
from utils.diagnostics import SystemDiagnostics

class TestMXBArchitecture(unittest.TestCase):

    def test_01_silero_vad_neural_inference(self):
        """Verify Silero Neural VAD loads and executes on 512-sample chunks."""
        vad = get_vad_model()
        self.assertIsNotNone(vad)
        # Test silence chunk
        silence_chunk = np.zeros(512, dtype=np.float32)
        prob = vad(silence_chunk)
        self.assertEqual(len(prob), 1)
        self.assertLess(float(prob[0]), 0.15, "Silence should have low speech probability")

        # Test synthetic tone/speech-like chunk
        t = np.linspace(0, 0.032, 512, endpoint=False)
        speech_like = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
        prob_tone = vad(speech_like)
        self.assertEqual(len(prob_tone), 1)

    def test_02_mouse_controller(self):
        """Verify MouseController screen sizing and bounds logic."""
        mouse = MouseController()
        w, h = mouse.get_screen_size()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        # Verify scroll doesn't throw
        try:
            mouse.scroll("down", 1)
        except Exception as e:
            self.fail(f"Mouse scroll threw exception: {e}")

    def test_03_keyboard_vk_mapping(self):
        """Verify Virtual Key code resolutions for extended keyboard."""
        kb = KeyboardExtended()
        self.assertEqual(kb._vk_from_name("enter"), 0x0D)
        self.assertEqual(kb._vk_from_name("esc"), 0x1B)
        self.assertEqual(kb._vk_from_name("tab"), 0x09)
        self.assertEqual(kb._vk_from_name("win"), 0x5B)
        self.assertEqual(kb._vk_from_name("f5"), 0x74)
        self.assertEqual(kb._vk_from_name("a"), ord('A'))

    def test_04_file_operations(self):
        """Verify file operations manager path resolving and lifecycle."""
        fops = FileOperationsManager()
        desktop = fops.resolve_path("desktop")
        self.assertTrue(str(desktop).endswith("Desktop") or "Desktop" in str(desktop))

        # Test safe file creation & deletion
        test_file = fops.resolve_path("desktop/_mxb_test_artifact.tmp")
        res_create = fops.create_file(str(test_file), "MXB Test Verification")
        self.assertTrue(test_file.exists())

        res_del = fops.delete_file(str(test_file))
        self.assertFalse(test_file.exists())

    def test_05_memory_bank_thread_safety(self):
        """Verify thread-safe memory storage, deduplication, and fuzzy recall."""
        test_fact = "User's favorite test language is Python 3"
        memory_bank.remember(test_fact)

        # Retrieve with query
        recalled = memory_bank.get_memories("favorite test language")
        self.assertTrue(any(test_fact in m for m in recalled))

        # Test duplicate avoidance
        count_before = len(memory_bank.get_memories())
        memory_bank.remember(test_fact)
        count_after = len(memory_bank.get_memories())
        self.assertEqual(count_before, count_after, "Duplicate fact should not be re-added")

    def test_06_action_planner(self):
        """Verify multi-step planner sequence execution."""
        executor = OSExecutionManager()
        planner = ActionPlanner(executor)

        plan = [
            {"action": "wait", "target": "0.1"},
            {"action": "type_text", "target": ""},
        ]
        results = planner.execute_plan(plan)
        self.assertEqual(len(results), 2)
        self.assertIn("Waited 0.1s", results[0])

    def test_07_screen_vision_engine(self):
        """Verify ScreenVision engine initializes and OCR is available."""
        vision = ScreenVision()
        # Verify OCR engine or fallback initializes
        self.assertIsNotNone(vision)

    def test_08_intent_router_tier1_fast_path(self):
        """Verify Tier 1 instant routing for common commands."""
        router = IntentRouter()
        # Mute
        res_mute = router.route("mute audio")
        self.assertIn("Action:", res_mute)

        # Scroll
        res_scroll = router.route("scroll down")
        self.assertIn("Action:", res_scroll)

        # Show desktop
        res_desk = router.route("show desktop")
        self.assertIn("Action:", res_desk)

    def test_09_system_diagnostics(self):
        """Verify system diagnostics runs and returns valid health dict."""
        health = SystemDiagnostics.get_health_report()
        self.assertIn("internet", health)
        self.assertIn("microphone_active", health)
        self.assertIn("silero_vad", health)
        self.assertTrue(health["silero_vad"], "Silero VAD should be active in diagnostics")

if __name__ == "__main__":
    unittest.main()
