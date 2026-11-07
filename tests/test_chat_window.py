"""Chat window wiring (runs headless with QT_QPA_PLATFORM=offscreen)."""
import unittest
from unittest.mock import MagicMock

import tests._stubs  # noqa: F401
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from ui.chat import ChatWindow


class FakeBus(QObject):
    user_message = Signal(str, str)
    reply_ready = Signal(str, str)
    feedback = Signal(str)
    status_changed = Signal(str)
    confirmation_requested = Signal(str)
    confirmation_resolved = Signal(bool)
    open_chat_requested = Signal()
    qr_ready = Signal(str, bytes)

    def __init__(self):
        super().__init__()
        self.submitted = []
        self.resolved = []

    def submit(self, text, source="text"):
        self.submitted.append((text, source))

    def resolve_confirmation(self, approved):
        self.resolved.append(approved)


class TestChatWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bus = FakeBus()
        self.voice = MagicMock()
        self.voice.is_listening = True
        self.chat = ChatWindow(self.bus, self.voice)

    def test_send_text(self):
        self.chat.input.setText("open notepad")
        self.chat._send()
        self.assertEqual(self.bus.submitted, [("open notepad", "text")])
        self.assertEqual(self.chat.input.text(), "")

    def test_stop_button(self):
        self.chat.stop_button.click()
        self.assertEqual(self.bus.submitted, [("stop", "text")])

    def test_messages_render(self):
        self.bus.user_message.emit("MXB open chrome", "voice")
        self.bus.reply_ready.emit("Opening chrome <now>", "voice")
        html = self.chat.transcript.toHtml()
        self.assertIn("open chrome", html)
        self.assertIn("&lt;now&gt;", html)  # escaped

    def test_confirmation_bar(self):
        self.bus.confirmation_requested.emit("Delete a.txt?")
        self.assertFalse(self.chat.confirm_bar.isHidden())
        self.chat.yes_button.click()
        self.assertEqual(self.bus.resolved, [True])
        self.bus.confirmation_resolved.emit(True)
        self.assertTrue(self.chat.confirm_bar.isHidden())

    def test_mic_toggle(self):
        self.chat.mic_button.click()
        self.voice.pause_listening.assert_called_once()


if __name__ == "__main__":
    unittest.main()
