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

    def remember(self, fact: str) -> bool:
        fact = fact.strip()
        if not fact:
            return False

        with self._lock:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    memories = json.load(f)

                # Avoid duplicate entries
                if any(fuzz.ratio(fact.lower(), m.lower()) > 92 for m in memories):
                    log.info(f"Memory: Fact already exists in memory: '{fact}'")
                    return False

                memories.append(fact)
                # Keep up to 100 recent facts
                if len(memories) > 100:
                    memories = memories[-100:]

                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(memories, f, indent=2)

                log.info(f"Memory: Successfully saved fact: '{fact}'")
                return True
            except Exception as e:
                log.error(f"Memory: Failed to save fact: {e}")
                return False

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

    def export_json(self, export_path: str = None) -> str:
        """Exports all memories to an external JSON file."""
        out_p = Path(export_path) if export_path else self.filepath.with_suffix(".export.json")
        memories = self.get_memories(limit=100)
        with self._lock:
            data = {"version": "2.1", "count": len(memories), "memories": memories}
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log.info(f"Memory: Exported {len(memories)} facts to '{out_p}'")
            return str(out_p)

    def import_json(self, import_path: str, merge: bool = True) -> int:
        """Imports memories from a JSON file. Returns count of newly imported facts."""
        in_p = Path(import_path)
        if not in_p.exists():
            return 0
        imported_count = 0
        try:
            with open(in_p, "r", encoding="utf-8") as f:
                data = json.load(f)
            facts = data.get("memories", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for fact in facts:
                if isinstance(fact, str) and self.remember(fact):
                    imported_count += 1
            log.info(f"Memory: Successfully imported {imported_count} new facts from '{in_p}'")
        except Exception as e:
            log.error(f"Memory: Failed importing from '{in_p}': {e}")
        return imported_count

# Shared singleton instance
memory_bank = MemoryBank()
