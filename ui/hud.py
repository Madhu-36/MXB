from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt

class FloatingHUD(QWidget):
    def __init__(self):
        super().__init__()
        # Frameless, Always on Top, Tool window (no taskbar icon)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet("background-color: #222222; border: 2px solid #555555; border-radius: 10px;")

        
        # Initial size and positioning
        self.resize(400, 200)
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, screen.height() - self.height() - 100)

        # UI Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # VAD Status
        self.status_label = QLabel("VAD: Listening...")
        self.status_label.setStyleSheet("color: #00FF00; font-weight: bold; background-color: rgba(20, 20, 20, 200); padding: 5px; border-radius: 5px;")
        
        # Transcription text
        self.transcript_label = QLabel("...")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setStyleSheet("color: #FFFFFF; font-size: 14px; background-color: rgba(20, 20, 20, 200); padding: 10px; border-radius: 5px;")
        
        # Action Feedback
        self.action_label = QLabel("Idle")
        self.action_label.setStyleSheet("color: #00BFFF; font-size: 12px; font-style: italic; background-color: rgba(20, 20, 20, 200); padding: 5px; border-radius: 5px;")

        layout.addWidget(self.status_label)
        layout.addWidget(self.transcript_label)
        layout.addWidget(self.action_label)
        
        self.setLayout(layout)

    def update_status(self, status: str):
        self.status_label.setText(f"VAD: {status}")
        if status.lower() == "active":
            self.status_label.setStyleSheet("color: #FF4500; font-weight: bold; background-color: rgba(20, 20, 20, 200); padding: 5px; border-radius: 5px;")
        else:
            self.status_label.setStyleSheet("color: #00FF00; font-weight: bold; background-color: rgba(20, 20, 20, 200); padding: 5px; border-radius: 5px;")

    def update_transcript(self, text: str):
        self.transcript_label.setText(text)

    def update_action(self, action_text: str):
        self.action_label.setText(action_text)
