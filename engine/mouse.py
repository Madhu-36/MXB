import time
import ctypes
from ctypes import wintypes
from utils.logger import log

class MouseController:
    """
    High-precision mouse controller for MXB.
    Provides cursor navigation, clicks (left, right, double, middle),
    click-and-drag, and mouse wheel scrolling using Windows native SendInput / user32 API.
    """

    # Windows mouse input event constants
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x00010
    MOUSEEVENTF_MIDDLEDOWN = 0x00020
    MOUSEEVENTF_MIDDLEUP = 0x00040
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x1000
    MOUSEEVENTF_ABSOLUTE = 0x8000

    WHEEL_DELTA = 120

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()

    def get_position(self) -> tuple[int, int]:
        """Returns the current mouse cursor (x, y) coordinates on the primary virtual screen."""
        pt = wintypes.POINT()
        if self.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
        return 0, 0

    def get_screen_size(self) -> tuple[int, int]:
        """Returns the virtual screen resolution (width, height)."""
        w = self.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        h = self.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        return w, h

    def move_to(self, x: int, y: int, smooth: bool = False, steps: int = 15):
        """Moves cursor to absolute coordinates (x, y)."""
        screen_w, screen_h = self.get_screen_size()
        x = max(0, min(screen_w - 1, int(x)))
        y = max(0, min(screen_h - 1, int(y)))

        if not smooth:
            self.user32.SetCursorPos(x, y)
            return

        start_x, start_y = self.get_position()
        for i in range(1, steps + 1):
            curr_x = int(start_x + (x - start_x) * (i / steps))
            curr_y = int(start_y + (y - start_y) * (i / steps))
            self.user32.SetCursorPos(curr_x, curr_y)
            time.sleep(0.008)
        self.user32.SetCursorPos(x, y)

    def move_relative(self, dx: int, dy: int):
        """Moves cursor relative to current position by (dx, dy)."""
        curr_x, curr_y = self.get_position()
        self.move_to(curr_x + dx, curr_y + dy)

    def left_click(self, x: int = None, y: int = None):
        """Clicks the left mouse button at current or specified (x, y) position."""
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        log.info(f"Mouse: Left click at {self.get_position()}")

    def right_click(self, x: int = None, y: int = None):
        """Clicks the right mouse button at current or specified (x, y) position."""
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(self.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        self.user32.mouse_event(self.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        log.info(f"Mouse: Right click at {self.get_position()}")

    def double_click(self, x: int = None, y: int = None):
        """Performs a double left-click."""
        if x is not None and y is not None:
            self.move_to(x, y)
        self.left_click()
        time.sleep(0.1)
        self.left_click()
        log.info(f"Mouse: Double click at {self.get_position()}")

    def middle_click(self, x: int = None, y: int = None):
        """Clicks the middle mouse button."""
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(self.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        self.user32.mouse_event(self.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)

    def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int):
        """Drags mouse from (start_x, start_y) and drops at (end_x, end_y)."""
        log.info(f"Mouse: Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y})")
        self.move_to(start_x, start_y)
        time.sleep(0.05)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.08)
        self.move_to(end_x, end_y, smooth=True, steps=20)
        time.sleep(0.08)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def scroll(self, direction: str = "down", amount: int = 3):
        """
        Scrolls the mouse wheel.
        direction: 'up', 'down', 'left', 'right'
        amount: number of notches (each notch is 120 delta)
        """
        clicks = int(amount)
        if direction.lower() in ["up", "forward"]:
            delta = self.WHEEL_DELTA * clicks
            self.user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        elif direction.lower() in ["down", "backward"]:
            delta = -self.WHEEL_DELTA * clicks
            self.user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        elif direction.lower() == "left":
            delta = -self.WHEEL_DELTA * clicks
            self.user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, delta, 0)
        elif direction.lower() == "right":
            delta = self.WHEEL_DELTA * clicks
            self.user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, delta, 0)
        log.info(f"Mouse: Scrolled {direction} by {clicks} notches")
