import json
import os
import threading
from pathlib import Path
from thefuzz import fuzz
from utils.logger import log

class MemoryBank:
    """
    MXB Long-Term Memory Storage.
    Thread-safe persistent knowledge bank for personal facts, preferences,
    and user reminders with fuzzy semantic keyword scoring.
    """

    def __init__(self):
        self.filepath = Path(__file__).parent.parent / "memory_bank.json"
        self._lock = threading.Lock()
        self._ensure_db()

    def _ensure_db(self):
        with self._lock:
            try:
                if not self.filepath.exists() or self.filepath.stat().st_size == 0:
                    with open(self.filepath, "w", encoding="utf-8") as f:
                        json.dump([], f)
                else:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        json.load(f)
            except Exception:
                log.warning("Memory: Database corrupted or unreadable. Initializing fresh memory array.")
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump([], f)

    def remember(self, fact: str):
        fact = fact.strip()
        if not fact:
            return

        with self._lock:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    memories = json.load(f)

                # Avoid duplicate entries
                if any(fuzz.ratio(fact.lower(), m.lower()) > 92 for m in memories):
                    log.info(f"Memory: Fact already exists in memory: '{fact}'")
                    return

                memories.append(fact)
                # Keep up to 100 recent facts
                if len(memories) > 100:
                    memories = memories[-100:]

                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(memories, f, indent=2)

                log.info(f"Memory: Successfully saved fact: '{fact}'")
            except Exception as e:
                log.error(f"Memory: Failed to save fact: {e}")

    def get_memories(self, query: str = None, limit: int = 5) -> list[str]:
        self._ensure_db()
        with self._lock:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    memories = json.load(f)
            except Exception:
                return []

        if not memories:
            return []

        if not query or not query.strip():
            return memories[-limit:]

        query_clean = query.lower().strip()
        scored = []
        for mem in memories:
            ratio = fuzz.partial_ratio(query_clean, mem.lower())
            if ratio > 50:
                scored.append((ratio, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [m[1] for m in scored[:limit]]
        if not results:
            # Return last few as general context if query didn't match specifics
            return memories[-min(3, len(memories)):]
        return results

# Shared singleton instance
memory_bank = MemoryBank()
