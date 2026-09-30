from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QBrush, QPen

class FloatingHUD(QWidget):
    def __init__(self):
        super().__init__()
        # Frameless, Always on Top, Tool window (doesn't show in taskbar alt-tab)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Initial size
        self.resize(450, 220)
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, screen.height() - self.height() - 80)

        # UI Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(10)

        # Title / VAD Status
        self.status_label = QLabel("MXB // Idle")
        self.status_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: #00E5FF; letter-spacing: 2px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Transcription text
        self.transcript_label = QLabel("Waiting for voice command...")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setFont(QFont("Segoe UI", 13))
        self.transcript_label.setStyleSheet("color: #FFFFFF;")
        self.transcript_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Action Feedback
        self.action_label = QLabel("")
        self.action_label.setFont(QFont("Consolas", 10))
        self.action_label.setStyleSheet("color: #A0A0A0; font-style: italic;")
        self.action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.status_label)
        layout.addWidget(self.transcript_label)
        layout.addWidget(self.action_label)
        
        self.setLayout(layout)
        
        # Add beautiful drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 5)
        self.setGraphicsEffect(shadow)
        
        # Fade out animation setup
        self.opacity = 1.0
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(500)
        
        # Auto-hide timer
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self._fade_out)
        self.hide_timer.setSingleShot(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Modern glass background
        brush = QBrush(QColor(15, 15, 22, 230))
        painter.setBrush(brush)
        
        # Cyan border accent
        pen = QPen(QColor(0, 229, 255, 120))
        pen.setWidth(2)
        painter.setPen(pen)
        
        # Draw rounded rect
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawRoundedRect(rect, 15, 15)

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
        if "Listening" in status or "Active" in status:
            self.status_label.setText("MXB // LISTENING")
            self.status_label.setStyleSheet("color: #FF2A5F; letter-spacing: 2px;")
        else:
            self.status_label.setText(f"MXB // {status.upper()}")
            self.status_label.setStyleSheet("color: #00E5FF; letter-spacing: 2px;")
            
        if status.lower() == "idle":
            self.hide_timer.start(5000) # Auto-hide after 5 seconds of idle

    def update_transcript(self, text: str):
        self._wake_up()
        self.transcript_label.setText(text)

    def update_action(self, action_text: str):
        self._wake_up()
        self.action_label.setText(action_text)
