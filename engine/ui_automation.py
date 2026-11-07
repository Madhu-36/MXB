"""
MXB UI Automation — finds real controls (search boxes, text fields, buttons,
links, tabs) in the foreground window through the Windows UI Automation (UIA)
accessibility tree, the same tree screen readers use.

This is far more reliable than OCR for "go to the search box and type X":
a search box usually shows no readable text, but UIA exposes it as an Edit
control named "Search", "Address and search bar", "Search YouTube", etc.

The pure scoring functions (score_search_candidate, pick_search_box,
pick_element) have no Windows dependency so they are unit-tested on any OS.
"""
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from rapidfuzz import fuzz
from utils.logger import log

SEARCH_WORDS = ("search", "find", "query", "look up", "lookup", "address and search", "type here", "ask", "filter")
TEXT_INPUT_TYPES = {"Edit", "ComboBox"}
CLICKABLE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "ListItem", "TabItem", "CheckBox", "RadioButton",
    "TreeItem", "SplitButton", "Image", "Text", "DataItem", "Edit", "ComboBox", "MenuBar",
}
INTERACTIVE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "TabItem", "CheckBox", "RadioButton", "SplitButton",
    "Edit", "ComboBox", "ListItem", "TreeItem",
}


@dataclass
class UIElement:
    name: str
    control_type: str
    automation_id: str = ""
    help_text: str = ""
    class_name: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom (physical pixels)
    has_focus: bool = False
    depth: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return (l + r) // 2, (t + b) // 2

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    def label(self) -> str:
        return self.name or self.help_text or self.automation_id or self.control_type


# ---------------------------------------------------------------------------
# Pure scoring logic (OS independent)
# ---------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def score_search_candidate(el: UIElement, hint: str = "", window_top: int = 0) -> int:
    """Higher = more likely to be the search box the user means."""
    if el.control_type not in TEXT_INPUT_TYPES or el.width < 20 or el.height < 8:
        return 0
    haystack = " ".join([el.name, el.automation_id, el.help_text, el.class_name]).lower()
    score = 5  # it's a text input at all
    if any(w in haystack for w in SEARCH_WORDS):
        score += 40
    if "address" in haystack and "search" in haystack:
        score -= 10  # browser address bar: prefer an in-page search box when one exists
    hint_words = [w for w in _words(hint) if w not in {"the", "a", "box", "bar", "field", "search"}]
    if hint_words:
        hits = sum(1 for w in hint_words if w in haystack)
        score += 25 * hits
    if el.has_focus:
        score += 5
    if el.width >= 200:
        score += 5
    if window_top and el.rect[1] - window_top < 250:
        score += 5  # search boxes usually live near the top
    if any(w in haystack for w in ("password", "otp", "pin")):
        score -= 50
    return max(score, 0)


def pick_search_box(elements: list[UIElement], hint: str = "", window_top: int = 0) -> UIElement | None:
    scored = [(score_search_candidate(e, hint, window_top), e) for e in elements]
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1].width), reverse=True)
    best_score, best = scored[0]
    # A bare text box with no search signal is only accepted when it's the only input.
    if best_score < 40 and len(scored) > 1:
        return None
    return best


def pick_element(elements: list[UIElement], name: str, types: set[str] | None = None,
                 min_score: int = 78) -> UIElement | None:
    """Fuzzy-matches an element by its visible/accessible name."""
    query = (name or "").lower().strip()
    if not query:
        return None
    best, best_score = None, 0
    for el in elements:
        if types and el.control_type not in types:
            continue
        if el.width <= 1 or el.height <= 1:
            continue
        for cand in (el.name, el.help_text, el.automation_id):
            cand = (cand or "").lower().strip()
            if not cand:
                continue
            if cand == query:
                score = 100
            else:
                score = max(fuzz.ratio(query, cand), fuzz.token_set_ratio(query, cand) - 4)
                if query in cand and len(cand) <= len(query) + 25:
                    score = max(score, 88)
            if el.control_type in INTERACTIVE_TYPES:
                score += 3
            if score > best_score:
                best, best_score = el, score
    return best if best_score >= min_score else None


def summarize_elements(elements: list[UIElement], limit: int = 40) -> list[dict]:
    """Compact list for LLM context: interactive, named, on-screen elements."""
    out = []
    for el in elements:
        if el.control_type not in INTERACTIVE_TYPES:
            continue
        label = el.label().strip()
        if not label or el.width < 4 or el.height < 4:
            continue
        cx, cy = el.center
        out.append({"type": el.control_type, "name": label[:60], "x": cx, "y": cy})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Windows UIA access
# ---------------------------------------------------------------------------
class UIAutomation:
    def __init__(self, max_nodes: int = 2500, time_budget: float = 2.5):
        self.max_nodes = max_nodes
        self.time_budget = time_budget
        self._local = threading.local()
        self._available = None

    def available(self) -> bool:
        if self._available is None:
            try:
                import pywinauto  # noqa: F401
                from pywinauto.uia_element_info import UIAElementInfo  # noqa: F401
                self._available = True
            except Exception as e:
                log.warning(f"UIAutomation: pywinauto UIA backend unavailable: {e}")
                self._available = False
        return self._available

    def _ensure_com(self):
        if getattr(self._local, "com_ready", False):
            return
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            try:
                import comtypes
                comtypes.CoInitialize()
            except Exception:
                pass
        self._local.com_ready = True

    @staticmethod
    def foreground_hwnd() -> int:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            return int(user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def foreground_title(self) -> str:
        hwnd = self.foreground_hwnd()
        if not hwnd:
            return ""
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
            return buf.value
        except Exception:
            return ""

    def collect(self, hwnd: int | None = None) -> tuple[list[UIElement], int]:
        """Walks the foreground window's UIA tree (breadth-first, time-boxed)."""
        if not self.available():
            return [], 0
        self._ensure_com()
        from pywinauto.uia_element_info import UIAElementInfo
        hwnd = hwnd or self.foreground_hwnd()
        if not hwnd:
            return [], 0
        try:
            root = UIAElementInfo(hwnd)
            window_top = int(root.rectangle.top)
        except Exception as e:
            log.warning(f"UIAutomation: cannot attach to foreground window: {e}")
            return [], 0

        deadline = time.time() + self.time_budget
        queue = deque([(root, 0)])
        found: list[UIElement] = []
        visited = 0
        while queue and visited < self.max_nodes and time.time() < deadline:
            info, depth = queue.popleft()
            visited += 1
            try:
                children = info.children()
            except Exception:
                children = []
            for child in children:
                queue.append((child, depth + 1))
            if info is root:
                continue
            el = self._to_element(info, depth)
            if el is not None:
                found.append(el)
        log.info(f"UIAutomation: scanned {visited} nodes, kept {len(found)} on-screen elements.")
        return found, window_top

    @staticmethod
    def _to_element(info, depth: int) -> UIElement | None:
        try:
            r = info.rectangle
            rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
            if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                return None
            try:
                if not info.visible:
                    return None
            except Exception:
                pass
            help_text = ""
            has_focus = False
            try:
                help_text = info.element.CurrentHelpText or ""
                has_focus = bool(info.element.CurrentHasKeyboardFocus)
            except Exception:
                pass
            return UIElement(
                name=(info.name or "").strip(),
                control_type=str(info.control_type or ""),
                automation_id=str(getattr(info, "automation_id", "") or ""),
                help_text=help_text.strip(),
                class_name=str(getattr(info, "class_name", "") or ""),
                rect=rect,
                has_focus=has_focus,
                depth=depth,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------ queries
    def find_search_box(self, hint: str = "") -> UIElement | None:
        elements, top = self.collect()
        return pick_search_box(elements, hint, top)

    def find_text_field(self, field_name: str) -> UIElement | None:
        elements, top = self.collect()
        if not field_name or field_name.lower().strip() in {"search", "search box", "search bar"}:
            return pick_search_box(elements, field_name, top)
        return pick_element(elements, field_name, TEXT_INPUT_TYPES, min_score=70) or (
            pick_search_box(elements, field_name, top) if "search" in field_name.lower() else None
        )

    def find_clickable(self, name: str) -> UIElement | None:
        elements, _ = self.collect()
        return pick_element(elements, name, CLICKABLE_TYPES)

    def summarize(self, limit: int = 40) -> list[dict]:
        elements, _ = self.collect()
        return summarize_elements(elements, limit)


BROWSER_PROCESS_HINTS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "arc")


def fallback_search_shortcut(window_title: str) -> tuple[str, list[str]]:
    """
    Keyboard fallback when no search box could be located.
    Returns (description, keys) for KeyboardExtended.shortcut.
    """
    title = (window_title or "").lower()
    if any(b in title for b in ("google chrome", "microsoft edge", "mozilla firefox", "brave", "opera", "vivaldi")):
        return "the browser address bar (Ctrl+L)", ["ctrl", "l"]
    if "file explorer" in title or title.endswith("- file explorer") or title in {"this pc", "home", "quick access"}:
        return "the File Explorer search box (Ctrl+E)", ["ctrl", "e"]
    if not title or title in {"program manager", "desktop"}:
        return "Windows Search (Win+S)", ["win", "s"]
    return "the app's find bar (Ctrl+F)", ["ctrl", "f"]
