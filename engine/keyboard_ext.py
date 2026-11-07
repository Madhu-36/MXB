import time
import ctypes
from ctypes import wintypes
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
        "volume_mute": 0xAD,
        "volume_down": 0xAE,
        "volume_up": 0xAF,
        "media_next": 0xB0,
        "media_prev": 0xB1,
        "media_stop": 0xB2,
        "media_play_pause": 0xB3,
        "print_screen": 0x2C,
        "prtsc": 0x2C,
    }

    KEYEVENTF_KEYUP = 0x0002
    MODIFIERS = {"ctrl", "control", "alt", "shift", "win", "windows", "super"}

    @classmethod
    def validate_shortcut_keys(cls, *keys) -> dict:
        """
        Validates a hotkey combination sequence:
        - Flattens arguments and splits composite strings like 'ctrl+shift+t'.
        - Validates all key names against virtual key mappings.
        - Sorts modifiers before trigger keys in canonical execution order.
        - Detects OS-reserved combos like Ctrl+Alt+Del.
        """
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = keys[0]
        elif len(keys) == 1 and isinstance(keys[0], str) and ("+" in keys[0] or " " in keys[0]):
            delimiter = "+" if "+" in keys[0] else " "
            keys = [k.strip() for k in keys[0].split(delimiter) if k.strip()]

        raw_keys = [str(k).lower().strip() for k in keys if str(k).strip()]
        if not raw_keys:
            return {"valid": False, "error": "No keys specified in shortcut.", "normalized_keys": [], "vk_codes": []}

        # Check for kernel-reserved combinations
        raw_set = set(raw_keys)
        if ("ctrl" in raw_set or "control" in raw_set) and "alt" in raw_set and ("del" in raw_set or "delete" in raw_set):
            return {"valid": False, "error": "Ctrl+Alt+Del is reserved by Windows kernel.", "normalized_keys": [], "vk_codes": []}

        # Separate modifiers from trigger keys to ensure canonical press ordering
        mods = []
        triggers = []
        vk_codes = []

        for k in raw_keys:
            # Map aliases
            canonical = "ctrl" if k == "control" else ("win" if k in ["windows", "super"] else ("del" if k == "delete" else ("esc" if k == "escape" else k)))
            vk = cls.VK_MAP.get(canonical)
            if not vk and len(canonical) == 1:
                vk = ord(canonical.upper())

            if not vk:
                return {"valid": False, "error": f"Unknown key '{k}'", "normalized_keys": [], "vk_codes": []}

            if canonical in cls.MODIFIERS or canonical in ["ctrl", "alt", "shift", "win"]:
                if canonical not in mods:
                    mods.append(canonical)
            else:
                triggers.append(canonical)

        canonical_sequence = mods + triggers
        canonical_vks = []
        for k in canonical_sequence:
            vk = cls.VK_MAP.get(k) or (ord(k.upper()) if len(k) == 1 else 0)
            canonical_vks.append(vk)

        return {
            "valid": True,
            "error": None,
            "normalized_keys": canonical_sequence,
            "vk_codes": canonical_vks,
            "has_modifier": len(mods) > 0,
            "trigger_count": len(triggers)
        }

    def __init__(self):
        self.pynput_kb = PynputController()
        self.user32 = ctypes.windll.user32
        # Explicit 64-bit API signature definition to prevent stack corruption (0xC0000409)
        self.user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        self.user32.keybd_event.restype = None

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
            # Many apps (browsers, Electron) read the clipboard asynchronously after Ctrl+V;
            # restoring too early pastes the user's OLD clipboard instead of our text.
            time.sleep(0.3)

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

    def execute_macro(self, steps: list[dict]) -> int:
        """
        Executes a sequence of keyboard macro steps:
        [{"type": "tap", "key": "enter"}, {"type": "type", "text": "foo"}, {"type": "shortcut", "keys": ["ctrl", "s"]}, {"type": "wait", "delay": 0.2}]
        Returns the number of successfully executed macro steps.
        """
        executed = 0
        for step in steps:
            stype = step.get("type", "").lower()
            if stype == "tap":
                self.tap_key(step.get("key", ""))
                executed += 1
            elif stype == "type":
                self.type_text(step.get("text", ""))
                executed += 1
            elif stype in ["shortcut", "hotkey"]:
                keys = step.get("keys", [])
                if keys:
                    self.shortcut(*keys)
                    executed += 1
            elif stype == "wait":
                time.sleep(max(0.01, min(float(step.get("delay", 0.1)), 5.0)))
                executed += 1
            time.sleep(0.02)
        return executed

    def snap_window_up(self):
        self.shortcut("win", "up")
