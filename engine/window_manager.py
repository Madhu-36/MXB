import ctypes
from ctypes import wintypes
import pygetwindow as gw
from utils.logger import log

class WindowManager:
    """
    Advanced Window Management and Geometry Manipulation for MXB.
    Provides quadrant snapping (corners), centering, and multi-window tiling.
    """

    def __init__(self):
        self.user32 = ctypes.windll.user32
        # Explicit 64-bit ctypes signatures
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.MoveWindow.argtypes = [
            wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL
        ]
        self.user32.MoveWindow.restype = wintypes.BOOL
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int

    @staticmethod
    def calculate_snap_rect(position: str, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
        """
        Calculates (x, y, width, height) bounding box for designated snap layout.
        Supported positions:
        - 'top_left', 'top_right', 'bottom_left', 'bottom_right'
        - 'left', 'right', 'top', 'bottom', 'center'
        """
        pos = position.lower().strip().replace(" ", "_").replace("-", "_")
        half_w = screen_w // 2
        half_h = screen_h // 2

        if pos == "top_left":
            return (0, 0, half_w, half_h)
        elif pos == "top_right":
            return (half_w, 0, half_w, half_h)
        elif pos == "bottom_left":
            return (0, half_h, half_w, half_h)
        elif pos == "bottom_right":
            return (half_w, half_h, half_w, half_h)
        elif pos == "left":
            return (0, 0, half_w, screen_h)
        elif pos == "right":
            return (half_w, 0, half_w, screen_h)
        elif pos == "top":
            return (0, 0, screen_w, half_h)
        elif pos == "bottom":
            return (0, half_h, screen_w, half_h)
        elif pos in ["center", "middle"]:
            w = int(screen_w * 0.70)
            h = int(screen_h * 0.70)
            x = (screen_w - w) // 2
            y = (screen_h - h) // 2
            return (x, y, w, h)
        else:
            return (0, 0, half_w, screen_h)

    def snap_active_window(self, position: str) -> str:
        """Snaps the currently focused window into a specific screen zone or corner."""
        try:
            hwnd = self.user32.GetForegroundWindow()
            if not hwnd:
                return "No active window in foreground."

            screen_w = self.user32.GetSystemMetrics(0)
            screen_h = self.user32.GetSystemMetrics(1)
            x, y, w, h = self.calculate_snap_rect(position, screen_w, screen_h)

            success = self.user32.MoveWindow(hwnd, x, y, w, h, True)
            if success:
                log.info(f"WindowManager: Snapped active window to '{position}' ({x}, {y}, {w}x{h})")
                return f"Snapped window to {position}"
            return f"Failed to reposition window to {position}"
        except Exception as e:
            log.error(f"WindowManager: Snap error: {e}")
            return f"Window snap failed: {e}"

    def minimize_all_except_active(self) -> str:
        """Minimizes all desktop windows except the currently active one (Aero Shake)."""
        try:
            active = gw.getActiveWindow()
            active_title = active.title if active else ""
            minimized_count = 0
            for w in gw.getAllWindows():
                if w.title and w.title != active_title and not w.isMinimized and w.visible:
                    try:
                        w.minimize()
                        minimized_count += 1
                    except Exception:
                        pass
            return f"Minimized {minimized_count} background windows."
        except Exception as e:
            return f"Failed to minimize background windows: {e}"

# Global shared instance
window_manager = WindowManager()
