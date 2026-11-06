import ctypes
from ctypes import wintypes
import math
from utils.logger import log

class ColorPicker:
    """
    High-Performance Native Screen Color Picker & Eyedropper for MXB.
    Queries pixel color at cursor or designated coordinates using 64-bit safe Windows GDI.
    """

    NAMED_COLORS = {
        "Black": (0, 0, 0),
        "White": (255, 255, 255),
        "Red": (255, 0, 0),
        "Crimson": (220, 20, 60),
        "Green": (0, 128, 0),
        "Lime": (0, 255, 0),
        "Blue": (0, 0, 255),
        "Navy": (0, 0, 128),
        "Sky Blue": (135, 206, 235),
        "Cyan": (0, 255, 255),
        "Yellow": (255, 255, 0),
        "Gold": (255, 215, 0),
        "Orange": (255, 165, 0),
        "Purple": (128, 0, 128),
        "Magenta": (255, 0, 255),
        "Pink": (255, 192, 203),
        "Gray": (128, 128, 128),
        "Silver": (192, 192, 192),
        "Dark Gray": (64, 64, 64),
    }

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32

        # Explicit 64-bit ctypes signatures
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi32.GetPixel.restype = wintypes.DWORD

        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL

    @classmethod
    def get_approx_color_name(cls, r: int, g: int, b: int) -> str:
        """Finds closest human-friendly color name by Euclidean distance in RGB space."""
        best_name = "Unknown"
        min_dist = float("inf")
        for name, rgb in cls.NAMED_COLORS.items():
            dist = math.sqrt((r - rgb[0])**2 + (g - rgb[1])**2 + (b - rgb[2])**2)
            if dist < min_dist:
                min_dist = dist
                best_name = name
        return best_name

    def get_color_at(self, x: int, y: int) -> dict:
        """Samples the pixel color at (x, y) coordinates on the primary display."""
        hdc = self.user32.GetDC(0)
        try:
            colorref = self.gdi32.GetPixel(hdc, int(x), int(y))
        finally:
            self.user32.ReleaseDC(0, hdc)

        r = colorref & 0xFF
        g = (colorref >> 8) & 0xFF
        b = (colorref >> 16) & 0xFF
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        color_name = self.get_approx_color_name(r, g, b)

        summary = f"Pixel at ({x}, {y}) is {hex_code} ({color_name}, RGB: {r}, {g}, {b})."
        log.info(f"ColorPicker: ({x}, {y}) -> {hex_code} ({color_name})")

        return {
            "x": int(x),
            "y": int(y),
            "r": r,
            "g": g,
            "b": b,
            "hex": hex_code,
            "name": color_name,
            "summary": summary
        }

    def get_color_at_cursor(self) -> dict:
        """Samples pixel color at the current mouse cursor location."""
        pt = wintypes.POINT()
        if self.user32.GetCursorPos(ctypes.byref(pt)):
            return self.get_color_at(pt.x, pt.y)
        return self.get_color_at(0, 0)

# Global shared instance
color_picker = ColorPicker()
