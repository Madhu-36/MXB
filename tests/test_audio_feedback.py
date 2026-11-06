import unittest
from unittest.mock import patch, MagicMock
from utils.audio_feedback import AudioFeedback

class TestAudioFeedback(unittest.TestCase):

    def setUp(self):
        self.feedback = AudioFeedback(enabled=True)

    def test_sound_map_coverage(self):
        for name in ["listen", "ping", "success", "done", "abort", "cancel", "error"]:
            self.assertIn(name, self.feedback.SOUND_MAP)

    def test_disabled_playback(self):
        self.feedback.set_enabled(False)
        self.assertFalse(self.feedback.play("listen"))

    def test_unknown_sound_cue(self):
        self.assertFalse(self.feedback.play("non_existent_sound_name"))

    @patch("winsound.PlaySound")
    def test_successful_async_playback(self, mock_play):
        success = self.feedback.play("success")
        self.assertTrue(success)
        mock_play.assert_called_once()
        args, kwargs = mock_play.call_args
        self.assertEqual(args[0], "SystemQuestion")

    @patch("winsound.PlaySound")
    def test_abort_sound_trigger(self, mock_play):
        success = self.feedback.play("abort")
        self.assertTrue(success)
        args, _ = mock_play.call_args
        self.assertEqual(args[0], "SystemExclamation")

if __name__ == "__main__":
    unittest.main()
