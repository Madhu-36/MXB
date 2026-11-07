"""
MXB Chat Window — talk to MXB by typing, see everything it says and does.

- Type a command or question and press Enter (Up/Down recalls history).
- Voice commands and their replies appear here too, so voice and text share one conversation.
- Live progress line shows what MXB is doing right now.
- Stop button = voice "stop" (aborts actions, clears queue, silences speech).
- Mic button mutes/unmutes listening.
- When MXB needs permission (delete, shutdown, ...) Yes / No buttons appear.
Toggle with the tray menu, the hotkey (default Ctrl+Alt+Space) or by saying "MXB, open chat".
"""
import html
import time
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QFrame,
)

STYLE = """
QWidget#MXBChat { background-color: #0C0E14; }
QLabel#Title { color: #00E5FF; letter-spacing: 2px; }
QLabel#Status { color: #8A93A6; }
QLabel#Progress { color: #A0FFA0; font-family: Consolas; }
QTextBrowser { background-color: #12151E; color: #E8ECF4; border: 1px solid #1F2433; border-radius: 10px; padding: 6px; }
QLineEdit { background-color: #12151E; color: #FFFFFF; border: 1px solid #00E5FF; border-radius: 8px; padding: 8px; }
QPushButton { background-color: #1A1F2C; color: #FFFFFF; border: 1px solid #2B3245; border-radius: 8px; padding: 7px 12px; }
QPushButton:hover { border-color: #00E5FF; }
QPushButton#Stop { background-color: #3A0F1A; border-color: #FF2A5F; color: #FFB3C4; font-weight: bold; }
QPushButton#Yes { background-color: #0F3A22; border-color: #2BD67B; }
QPushButton#No { background-color: #3A0F1A; border-color: #FF2A5F; }
QFrame#ConfirmBar { background-color: #2A2410; border: 1px solid #FFD700; border-radius: 8px; }
QLabel#ConfirmText { color: #FFE680; }
"""


class _HistoryLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: list[str] = []
        self._index = 0

    def remember(self, text: str):
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._index = len(self.history)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up and self.history:
            self._index = max(0, self._index - 1)
            self.setText(self.history[self._index])
            return
        if event.key() == Qt.Key.Key_Down and self.history:
            self._index = min(len(self.history), self._index + 1)
            self.setText(self.history[self._index] if self._index < len(self.history) else "")
            return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    toggle_requested = Signal()  # safe to emit from any thread (hotkeys)

    def __init__(self, bus, voice_pipeline=None):
        super().__init__()
        self.bus = bus
        self.voice = voice_pipeline
        self.setObjectName("MXBChat")
        self.setWindowTitle("MXB Companion")
        self.resize(460, 620)
        self.setStyleSheet(STYLE)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("MXB // COMPANION")
        title.setObjectName("Title")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("Status")
        self.mic_button = QPushButton("🎙 Listening")
        self.mic_button.clicked.connect(self._toggle_mic)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.setObjectName("Stop")
        self.stop_button.clicked.connect(lambda: self.bus.submit("stop", "text"))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        header.addWidget(self.mic_button)
        header.addWidget(self.stop_button)
        root.addLayout(header)

        # Conversation
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setFont(QFont("Segoe UI", 10))
        root.addWidget(self.transcript, 1)

        # Live progress
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Progress")
        self.progress_label.setWordWrap(True)
        root.addWidget(self.progress_label)

        # Confirmation bar
        self.confirm_bar = QFrame()
        self.confirm_bar.setObjectName("ConfirmBar")
        cb = QHBoxLayout(self.confirm_bar)
        cb.setContentsMargins(10, 6, 10, 6)
        self.confirm_text = QLabel("")
        self.confirm_text.setObjectName("ConfirmText")
        self.confirm_text.setWordWrap(True)
        self.yes_button = QPushButton("Yes")
        self.yes_button.setObjectName("Yes")
        self.no_button = QPushButton("No")
        self.no_button.setObjectName("No")
        self.yes_button.clicked.connect(lambda: self.bus.resolve_confirmation(True))
        self.no_button.clicked.connect(lambda: self.bus.resolve_confirmation(False))
        cb.addWidget(self.confirm_text, 1)
        cb.addWidget(self.yes_button)
        cb.addWidget(self.no_button)
        self.confirm_bar.hide()
        root.addWidget(self.confirm_bar)

        # Input
        row = QHBoxLayout()
        self.input = _HistoryLineEdit()
        self.input.setPlaceholderText("Type a command or question… e.g. “search for lofi music in the search box”")
        self.input.returnPressed.connect(self._send)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        root.addLayout(row)

        # Wiring (bus signals are emitted from worker threads -> queued into the GUI thread)
        bus.user_message.connect(self.add_user_message)
        bus.reply_ready.connect(self.add_reply)
        bus.feedback.connect(self.set_progress)
        bus.status_changed.connect(self.set_status)
        bus.confirmation_requested.connect(self.show_confirmation)
        bus.confirmation_resolved.connect(self.hide_confirmation)
        bus.open_chat_requested.connect(self.show_and_focus)
        self.toggle_requested.connect(self.toggle_visible)

        self._append_html(self._bubble("MXB", "Hi! Talk to me (say “MXB” first) or type here. "
                                       "I can control apps, the mouse and keyboard, files, Bluetooth, Wi-Fi, volume and more. "
                                       "Say or press Stop any time.", "#00E5FF"))

    # ------------------------------------------------------------------ rendering
    @staticmethod
    def _bubble(who: str, text: str, color: str, small: str = "") -> str:
        safe = html.escape(text).replace("\n", "<br>")
        stamp = time.strftime("%H:%M")
        tag = f' <span style="color:#5D667A;font-size:8pt;">{html.escape(small)}</span>' if small else ""
        return (f'<p style="margin:6px 0;"><span style="color:{color};font-weight:bold;">{who}</span>'
                f'<span style="color:#5D667A;font-size:8pt;"> {stamp}</span>{tag}<br>'
                f'<span style="color:#E8ECF4;">{safe}</span></p>')

    def _append_html(self, fragment: str):
        self.transcript.append(fragment)
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user_message(self, text: str, source: str):
        label = "🎙 voice" if source == "voice" else "⌨ text"
        self._append_html(self._bubble("You", text, "#FF7AA2", label))

    def add_reply(self, text: str, source: str):
        if text:
            self._append_html(self._bubble("MXB", text, "#00E5FF"))

    def set_progress(self, text: str):
        self.progress_label.setText(text[:220])

    def set_status(self, text: str):
        self.status_label.setText(text[:40])
        if text == "Idle":
            self.progress_label.setText("")

    def show_confirmation(self, question: str):
        self.confirm_text.setText(question)
        self.confirm_bar.show()
        self.show_and_focus()

    def hide_confirmation(self, _approved: bool = False):
        self.confirm_bar.hide()

    # ------------------------------------------------------------------ actions
    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.remember(text)
        self.input.clear()
        self.bus.submit(text, "text")

    def _toggle_mic(self):
        if self.voice is None:
            return
        if getattr(self.voice, "is_listening", True):
            self.voice.pause_listening()
            self.mic_button.setText("🔇 Muted")
        else:
            self.voice.resume_listening()
            self.mic_button.setText("🎙 Listening")

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def toggle_visible(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_and_focus()
