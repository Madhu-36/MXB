"""
Click-through overlay that draws numbered boxes over every clickable element
("MXB, show numbers" -> "click 12"). Works like browser hint extensions, but for
any Windows app the accessibility tree can see.

Signals are thread-safe: the executor (worker thread) emits show_requested /
hide_requested and Qt delivers them on the GUI thread.
"""
from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QGuiApplication
from PySide6.QtWidgets import QWidget


class MarksOverlay(QWidget):
    show_requested = Signal(list)   # [(number, (left, top, right, bottom), label), ...] in physical pixels
    hide_requested = Signal()

    def __init__(self, auto_hide_ms: int = 20000):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.marks: list = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.auto_hide_ms = auto_hide_ms
        self.show_requested.connect(self.display)
        self.hide_requested.connect(self.hide)

    def display(self, marks: list):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.marks = marks
        self.show()
        self.raise_()
        self.update()
        self._timer.start(self.auto_hide_ms)

    def paintEvent(self, event):
        if not self.marks:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        origin = self.geometry().topLeft()
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        for number, rect, _label in self.marks:
            l, t, r, b = [v / dpr for v in rect]
            box = QRect(int(l - origin.x()), int(t - origin.y()), int(r - l), int(b - t))
            painter.setPen(QPen(QColor(255, 42, 95, 230), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)
            tag = str(number)
            tag_rect = QRect(box.left(), max(0, box.top() - 16), 10 + 8 * len(tag), 16)
            painter.fillRect(tag_rect, QColor(255, 42, 95, 235))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag)
