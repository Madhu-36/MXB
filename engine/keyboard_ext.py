import time
import ctypes
import pyperclip
from pynput.keyboard import Controller as PynputController, Key
from utils.logger import log

class KeyboardExtended:
    """
    Comprehensive keyboard automation for MXB.
    Supports single keys, combinations, Windows shortcuts, text dictation,
    and fast unicode clipboard pasting.
    """

    # Windows Virtual-Key Codes mapping
    VK_MAP = {
        "enter": 0x0D,
        "return": 0x0D,
        "escape": 0x1B,
        "esc": 0x1B,
        "tab": 0x09,
        "backspace": 0x08,
        "delete": 0x2E,
        "del": 0x2E,
        "space": 0x20,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "win": 0x5B,
        "windows": 0x5B,
        "super": 0x5B,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "capslock": 0x14,
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
    }

    KEYEVENTF_KEYUP = 0x0002

    def __init__(self):
        self.pynput_kb = PynputController()
        self.user32 = ctypes.windll.user32

    def _vk_from_name(self, name: str) -> int:
        name = name.lower().strip()
        if name in self.VK_MAP:
            return self.VK_MAP[name]
        if len(name) == 1:
            # For letters A-Z and digits 0-9, VK matches ASCII uppercase
            return ord(name.upper())
        return 0

    def press_vk(self, vk: int):
        self.user32.keybd_event(vk, 0, 0, 0)

    def release_vk(self, vk: int):
        self.user32.keybd_event(vk, 0, self.KEYEVENTF_KEYUP, 0)

    def tap_key(self, key_name: str):
        """Taps a single key (press and release)."""
        vk = self._vk_from_name(key_name)
        if vk:
            self.press_vk(vk)
            time.sleep(0.04)
            self.release_vk(vk)
            log.info(f"Keyboard: Tapped key '{key_name}' (VK: 0x{vk:02X})")
        else:
            try:
                self.pynput_kb.press(key_name)
                time.sleep(0.04)
                self.pynput_kb.release(key_name)
            except Exception as e:
                log.warning(f"Keyboard: Could not tap key '{key_name}': {e}")

    def shortcut(self, *keys):
        """
        Executes a multi-key combination in order and releases in reverse order.
        Example: shortcut('ctrl', 'shift', 't') or shortcut('alt', 'tab')
        """
        # Flatten if a list or tuple was passed as first arg
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = keys[0]

        vk_list = []
        for k in keys:
            vk = self._vk_from_name(str(k))
            if vk:
                vk_list.append(vk)

        if not vk_list:
            log.warning(f"Keyboard: No valid virtual keys found in combination: {keys}")
            return

        log.info(f"Keyboard: Executing shortcut: {' + '.join(str(k) for k in keys)}")

        # Press keys sequentially
        for vk in vk_list:
            self.press_vk(vk)
            time.sleep(0.03)

        time.sleep(0.06)

        # Release keys in reverse order
        for vk in reversed(vk_list):
            self.release_vk(vk)
            time.sleep(0.02)

    def type_text(self, text: str, fast_paste: bool = True):
        """
        Types text. If fast_paste is True and text is longer than 15 characters,
        uses clipboard injection for instantaneous, 100% accurate character entry.
        """
        if not text:
            return

        if fast_paste and len(text) > 15:
            # Preserve user's original clipboard
            old_clip = ""
            try:
                old_clip = pyperclip.paste()
            except Exception:
                pass

            pyperclip.copy(text)
            time.sleep(0.05)
            self.shortcut("ctrl", "v")
            time.sleep(0.05)

            # Restore original clipboard asynchronously if needed
            if old_clip:
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass
            log.info(f"Keyboard: Pasted {len(text)} characters via clipboard")
        else:
            self.pynput_kb.type(text)
            log.info(f"Keyboard: Typed '{text}'")

    # Common convenience shortcuts
    def select_all(self):
        self.shortcut("ctrl", "a")

    def copy(self):
        self.shortcut("ctrl", "c")

    def paste(self):
        self.shortcut("ctrl", "v")

    def cut(self):
        self.shortcut("ctrl", "x")

    def undo(self):
        self.shortcut("ctrl", "z")

    def redo(self):
        self.shortcut("ctrl", "y")

    def save(self):
        self.shortcut("ctrl", "s")

    def find(self):
        self.shortcut("ctrl", "f")

    def new_tab(self):
        self.shortcut("ctrl", "t")

    def close_tab(self):
        self.shortcut("ctrl", "w")

    def reopen_tab(self):
        self.shortcut("ctrl", "shift", "t")

    def switch_tab(self):
        self.shortcut("ctrl", "tab")

    def focus_url_bar(self):
        self.shortcut("ctrl", "l")

    def refresh(self):
        self.tap_key("f5")

    def show_desktop(self):
        self.shortcut("win", "d")

    def open_run_dialog(self):
        self.shortcut("win", "r")

    def open_file_explorer(self):
        self.shortcut("win", "e")

    def open_settings(self):
        self.shortcut("win", "i")

    def lock_pc(self):
        self.shortcut("win", "l")

    def task_switch(self):
        self.shortcut("alt", "tab")

    def close_window(self):
        self.shortcut("alt", "f4")

    def snap_window_left(self):
        self.shortcut("win", "left")

    def snap_window_right(self):
        self.shortcut("win", "right")

    def snap_window_up(self):
        self.shortcut("win", "up")
