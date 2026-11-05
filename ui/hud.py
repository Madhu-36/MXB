from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QProgressBar, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QBrush, QPen

class FloatingHUD(QWidget):
    """
    Sleek, transparent floating HUD overlay for MXB.
    Displays real-time microphone volume, neural VAD listening state,
    recognized speech transcript, and live multi-step execution feedback.
    """

    def __init__(self):
        super().__init__()
        # Frameless, Always on Top, Tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.resize(500, 240)
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, screen.height() - self.height() - 75)

        layout = QVBoxLayout()
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(8)

        # Title / VAD Status
        self.status_label = QLabel("MXB // IDLE")
        self.status_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: #00E5FF; letter-spacing: 2px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Live Audio Input Bar
        self.mic_bar = QProgressBar()
        self.mic_bar.setRange(0, 100)
        self.mic_bar.setValue(0)
        self.mic_bar.setTextVisible(False)
        self.mic_bar.setFixedHeight(4)
        self.mic_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 2px;
                background-color: rgba(255, 255, 255, 20);
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E5FF, stop:1 #FF2A5F);
                border-radius: 2px;
            }
        """)

        # Transcription Display
        self.transcript_label = QLabel("Listening for your voice command...")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setFont(QFont("Segoe UI", 13))
        self.transcript_label.setStyleSheet("color: #FFFFFF;")
        self.transcript_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Action Feedback
        self.action_label = QLabel("")
        self.action_label.setFont(QFont("Consolas", 10))
        self.action_label.setStyleSheet("color: #A0FFA0; font-style: italic;")
        self.action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.status_label)
        layout.addWidget(self.mic_bar)
        layout.addWidget(self.transcript_label)
        layout.addWidget(self.action_label)

        self.setLayout(layout)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        # Dynamic cyber glow color state
        self._glow_color = QColor(0, 229, 255, 140)

        # Fade out animation
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(500)

        # Auto-hide timer
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self._fade_out)
        self.hide_timer.setSingleShot(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Cyber-executive dark frosted glass
        brush = QBrush(QColor(12, 14, 20, 235))
        painter.setBrush(brush)

        pen = QPen(self._glow_color)
        pen.setWidth(2)
        painter.setPen(pen)

        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawRoundedRect(rect, 16, 16)

    def _fade_out(self):
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_anim.start()

    def _wake_up(self):
        self.fade_anim.stop()
        self.setWindowOpacity(1.0)
        self.hide_timer.stop()

    def update_status(self, status: str):
        self._wake_up()
        upper = status.upper()
        if "LISTENING" in upper or "ACTIVE" in upper:
            self._glow_color = QColor(255, 42, 95, 200)
            self.status_label.setText("MXB // LISTENING")
            self.status_label.setStyleSheet("color: #FF2A5F; letter-spacing: 2px;")
        elif "PROCESSING" in upper or "REASONING" in upper or "PLANNING" in upper:
            self._glow_color = QColor(255, 215, 0, 200)
            self.status_label.setText("MXB // REASONING...")
            self.status_label.setStyleSheet("color: #FFD700; letter-spacing: 2px;")
        elif "ERROR" in upper:
            self._glow_color = QColor(255, 0, 128, 220)
            self.status_label.setText(f"MXB // {upper}")
            self.status_label.setStyleSheet("color: #FF0080; letter-spacing: 2px;")
        else:
            self._glow_color = QColor(0, 229, 255, 140)
            self.status_label.setText(f"MXB // {upper}")
            self.status_label.setStyleSheet("color: #00E5FF; letter-spacing: 2px;")

        self.update()

        if status.lower() == "idle":
            self.hide_timer.start(5000)

    def update_mic_level(self, level: float):
        """Updates the audio activity progress bar (0.0 to 1.0)."""
        val = int(min(max(level * 100.0, 0), 100))
        self.mic_bar.setValue(val)
        if val > 15 and self.windowOpacity() < 0.1:
            self._wake_up()

    def update_transcript(self, text: str):
        self._wake_up()
        self.transcript_label.setText(text)

    def update_action(self, action_text: str):
        self._wake_up()
        self.action_label.setText(action_text)
