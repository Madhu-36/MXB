import time
import threading
import pyperclip
from datetime import datetime
from rapidfuzz import fuzz
from utils.logger import log

class ClipboardHistoryItem:
    def __init__(self, text: str):
        self.text = text
        self.timestamp = datetime.now()
        self.char_count = len(text)
        self.word_count = len(text.split())

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "char_count": self.char_count,
            "word_count": self.word_count
        }

class ClipboardMonitor:
    """
    Background clipboard history tracker for MXB.
    Keeps a deduplicated rolling buffer of recent clipboard texts
    and provides sub-millisecond fuzzy search and recall.
    """

    def __init__(self, max_items: int = 50):
        self.max_items = max_items
        self._history: list[ClipboardHistoryItem] = []
        self._lock = threading.Lock()
        self._is_running = False
        self._thread: threading.Thread | None = None
        self._last_content = ""

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._monitor_loop, name="MXB-ClipboardMonitor", daemon=True)
        self._thread.start()
        log.info("ClipboardMonitor: Started background clipboard tracking.")

    def stop(self):
        self._is_running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        log.info("ClipboardMonitor: Stopped clipboard tracking.")

    def _monitor_loop(self):
        while self._is_running:
            try:
                content = pyperclip.paste()
                if content and content != self._last_content:
                    self._last_content = content
                    self.add_item(content)
            except Exception:
                pass
            time.sleep(0.5)

    def add_item(self, text: str) -> bool:
        clean = text.strip()
        if not clean:
            return False

        with self._lock:
            # Check for recent identical content to avoid consecutive duplicates
            if self._history and self._history[0].text == clean:
                return False

            item = ClipboardHistoryItem(clean)
            self._history.insert(0, item)
            if len(self._history) > self.max_items:
                self._history.pop()
            log.info(f"ClipboardMonitor: Recorded new entry ({item.char_count} chars). Total: {len(self._history)}")
            return True

    def get_recent(self, limit: int = 5) -> list[dict]:
        with self._lock:
            return [item.to_dict() for item in self._history[:limit]]

    def search(self, query: str, limit: int = 3) -> list[dict]:
        clean_q = query.lower().strip()
        if not clean_q:
            return self.get_recent(limit)

        with self._lock:
            scored = []
            for item in self._history:
                ratio = fuzz.partial_ratio(clean_q, item.text.lower())
                if ratio > 45:
                    scored.append((ratio, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [item.to_dict() for _, item in scored[:limit]]

    def clear(self):
        with self._lock:
            self._history.clear()
            self._last_content = ""
            log.info("ClipboardMonitor: Cleared clipboard history.")

# Singleton instance
clipboard_monitor = ClipboardMonitor()
