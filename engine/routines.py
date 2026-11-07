"""
Routines and record-and-replay workflows.

Routines (spoken):   "create a routine called work mode: open vs code; open chrome; set volume to 30"
                     "run work mode"
Recordings (shown):  "start recording expense report" -> you click and type -> "stop recording"
                     "run expense report" replays it through the abortable planner.

Recorded clicks store the accessibility name of the element under the cursor, so
replay clicks "the Submit button" even if the window moved; the original
coordinates are kept as a fallback. Keystrokes typed into password fields are
NOT recorded. Events that land in MXB's own windows are ignored.
"""
import json
import queue
import re
import threading
import time
from pathlib import Path
from rapidfuzz import fuzz, process
from utils.logger import log
from utils.paths import data_file

SPECIAL_KEYS = {"enter", "tab", "esc", "backspace", "delete", "up", "down", "left", "right", "home", "end",
                "page_up", "page_down", "space", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"}
MODIFIERS = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r"}
KEY_ALIASES = {"esc": "escape", "page_up": "pageup", "page_down": "pagedown", "cmd": "win"}


def _mod(name: str) -> str:
    return {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
            "shift_l": "shift", "shift_r": "shift", "cmd": "win", "cmd_l": "win", "cmd_r": "win"}.get(name, name)


def events_to_plan(events: list[dict], max_wait: float = 5.0) -> tuple[list[dict], int]:
    """
    Converts raw recorded events into planner steps.
    events: {"t": float, "type": "click", "x", "y", "button", "label", "password"} |
            {"t": float, "type": "key", "key": "a" | "enter" | ..., "mods": ["ctrl"]}
    Returns (steps, skipped_password_keys).
    """
    steps: list[dict] = []
    typed = ""
    skipped = 0
    in_password = False
    last_t = None
    last_click = None

    def flush_typed():
        nonlocal typed
        if typed:
            steps.append({"action": "type_text", "target": typed})
            typed = ""

    for ev in sorted(events, key=lambda e: e["t"]):
        if last_t is not None:
            gap = ev["t"] - last_t
            if gap > 1.5:
                flush_typed()
                steps.append({"action": "wait", "target": f"{min(gap, max_wait):.1f}"})
        last_t = ev["t"]

        if ev["type"] == "click":
            flush_typed()
            in_password = bool(ev.get("password"))
            action = {"left": "left_click", "right": "right_click", "middle": "left_click"}.get(ev.get("button", "left"), "left_click")
            # double click = two left clicks within 0.4 s at (almost) the same spot
            if (action == "left_click" and last_click and ev["t"] - last_click["t"] <= 0.4
                    and abs(ev["x"] - last_click["x"]) <= 4 and abs(ev["y"] - last_click["y"]) <= 4 and steps
                    and steps[-1]["action"] in ("left_click", "click_element")):
                steps[-1] = {"action": "double_click", "target": f"{ev['x']},{ev['y']}"}
                last_click = None
                continue
            label = (ev.get("label") or "").strip()
            if label and action == "left_click" and len(label) <= 60:
                # "label || x,y": replay clicks the element by name, falling back to the recorded spot.
                steps.append({"action": "click_element", "target": f"{label} || {ev['x']},{ev['y']}"})
            else:
                steps.append({"action": action, "target": f"{ev['x']},{ev['y']}"})
            last_click = ev
            continue

        if ev["type"] == "key":
            if in_password:
                skipped += 1
                continue
            key = ev["key"]
            mods = sorted({_mod(m) for m in ev.get("mods", []) if _mod(m) != "shift"})
            if key in MODIFIERS:
                continue
            if mods:
                flush_typed()
                steps.append({"action": "shortcut", "target": "+".join(mods + [KEY_ALIASES.get(key, key)])})
            elif len(key) == 1:
                typed += key
            elif key == "space":
                typed += " "
            elif key == "backspace" and typed:
                typed = typed[:-1]
            elif key in SPECIAL_KEYS:
                flush_typed()
                steps.append({"action": "press_key", "target": KEY_ALIASES.get(key, key)})
    flush_typed()
    while steps and steps[-1]["action"] == "wait":
        steps.pop()
    return steps, skipped


class RoutineStore:
    def __init__(self, store_path: str | Path | None = None):
        self.store_path = Path(store_path) if store_path else data_file("routines.json")
        self._lock = threading.Lock()
        self.items: dict[str, dict] = {}
        try:
            if self.store_path.exists():
                self.items = json.loads(self.store_path.read_text(encoding="utf-8"))
        except Exception:
            self.items = {}

    def _save(self):
        try:
            self.store_path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Routines: save failed: {e}")

    @staticmethod
    def _key(name: str) -> str:
        return re.sub(r"\s+", " ", (name or "").lower().strip().strip("'\""))

    def create(self, name: str, commands: list[str]) -> str:
        commands = [c.strip() for c in commands if c and c.strip()]
        if not name.strip() or not commands:
            return "A routine needs a name and at least one command, like 'work mode: open vs code; open chrome'."
        with self._lock:
            self.items[self._key(name)] = {"type": "commands", "commands": commands, "created": time.time()}
            self._save()
        return f"Saved routine '{name.strip()}' with {len(commands)} steps. Say 'run {name.strip()}' to use it."

    def save_recording(self, name: str, steps: list[dict]) -> str:
        with self._lock:
            self.items[self._key(name)] = {"type": "recording", "steps": steps, "created": time.time()}
            self._save()
        return f"Saved workflow '{name}' with {len(steps)} steps. Say 'run {name}' to replay it."

    def find(self, name: str) -> tuple[str, dict] | None:
        key = self._key(name)
        if key in self.items:
            return key, self.items[key]
        if not self.items:
            return None
        best = process.extractOne(key, list(self.items), scorer=fuzz.token_set_ratio)
        if best and best[1] >= 75:
            return best[0], self.items[best[0]]
        return None

    def delete(self, name: str) -> str:
        found = self.find(name)
        if not found:
            return f"No routine called '{name}'."
        with self._lock:
            self.items.pop(found[0], None)
            self._save()
        return f"Deleted '{found[0]}'."

    def list_text(self) -> str:
        if not self.items:
            return "No routines yet. Try: 'create a routine called work mode: open vs code; open chrome'."
        parts = []
        for name, item in self.items.items():
            n = len(item.get("commands") or item.get("steps") or [])
            kind = "routine" if item["type"] == "commands" else "recorded workflow"
            parts.append(f"{name} ({kind}, {n} steps)")
        return "Saved: " + "; ".join(parts) + "."


class WorkflowRecorder:
    """Records the user's own mouse clicks and typing with pynput (only while asked to)."""

    def __init__(self, element_at=None, foreground_title=None, ignore_titles=("MXB Companion",)):
        self.element_at = element_at              # fn(x, y) -> (label, is_password)
        self.foreground_title = foreground_title  # fn() -> str
        self.ignore_titles = ignore_titles
        self.name = ""
        self.events: list[dict] = []
        self._raw = queue.Queue()
        self._listeners = []
        self._resolver = None
        self.recording = False
        self._mods: set[str] = set()

    def _ignored(self) -> bool:
        if not self.foreground_title:
            return False
        try:
            title = self.foreground_title() or ""
        except Exception:
            return False
        return any(t.lower() in title.lower() for t in self.ignore_titles)

    def start(self, name: str) -> str:
        if self.recording:
            return f"I'm already recording '{self.name}'. Say 'stop recording' first."
        try:
            from pynput import keyboard, mouse
        except Exception as e:
            return f"Recording needs the pynput package: {e}"
        self.name, self.events, self._mods = name.strip() or "workflow", [], set()
        self.recording = True

        def on_click(x, y, button, pressed):
            if pressed and self.recording:
                self._raw.put({"t": time.time(), "type": "click", "x": int(x), "y": int(y),
                               "button": getattr(button, "name", "left")})

        def key_name(key):
            if hasattr(key, "char") and key.char:
                return key.char
            return getattr(key, "name", str(key)).lower()

        def on_press(key):
            if not self.recording:
                return
            name_ = key_name(key)
            if name_ in MODIFIERS:
                self._mods.add(name_)
                return
            self._raw.put({"t": time.time(), "type": "key", "key": name_, "mods": sorted(self._mods)})

        def on_release(key):
            self._mods.discard(key_name(key))

        self._listeners = [mouse.Listener(on_click=on_click), keyboard.Listener(on_press=on_press, on_release=on_release)]
        for listener in self._listeners:
            listener.start()
        # Element lookups happen off the input-hook thread so recording never lags the user's input.
        self._resolver = threading.Thread(target=self._resolve_loop, name="MXB-Recorder", daemon=True)
        self._resolver.start()
        log.info(f"Recorder: started '{self.name}'")
        return f"Recording '{self.name}'. Do the task now, then say 'stop recording'. Password fields are not recorded."

    def _resolve_loop(self):
        while self.recording or not self._raw.empty():
            try:
                ev = self._raw.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._ignored():
                continue
            if ev["type"] == "click" and self.element_at:
                try:
                    label, is_password = self.element_at(ev["x"], ev["y"])
                    ev["label"], ev["password"] = label, is_password
                except Exception:
                    pass
            self.events.append(ev)

    def stop(self) -> tuple[str, list[dict], int]:
        if not self.recording:
            return "", [], 0
        self.recording = False
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        if self._resolver:
            self._resolver.join(timeout=2)
        steps, skipped = events_to_plan(self.events)
        log.info(f"Recorder: stopped '{self.name}' with {len(steps)} steps ({skipped} password keys skipped)")
        return self.name, steps, skipped
