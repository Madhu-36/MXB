"""
Semantic long-term memory (SQLite + embeddings).

- remember / recall by meaning, not just keywords ("what's my favourite editor?"
  finds "I use VS Code for everything").
- Learns preferences automatically from first-person statements ("I prefer dark mode",
  "my manager is Ravi", "call me S10"), but never from anything that looks like a
  secret (passwords, PINs, card or account numbers).
- Imports the old memory_bank.json once.
- Everything stays on this PC (mxb_memory.db).
"""
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
import numpy as np
from utils.logger import log

SENSITIVE = re.compile(r"\b(password|passcode|pin|otp|cvv|card number|credit card|debit card|account number|"
                       r"aadhaar|aadhar|pan number|ssn|social security|bank account|ifsc|secret key|api key|token)\b", re.I)

_COMMANDISH = re.compile(r"\b(remind me|open|close|search|play|turn (?:on|off)|set (?:a|the)|send|create|delete|"
                        r"launch|start|stop|click|type|schedule|check|show|find|read|tell|help|fix|clean|increase|"
                        r"decrease|mute|unmute|lock|shut|restart|run|go to|download|install|update|explain|analy[sz]e|"
                        r"summari[sz]e|can you|could you|please|call (?!me\b))\b", re.I)
_PREF_PATTERNS = [
    re.compile(r"^i\s+(?:really\s+|usually\s+|always\s+|mostly\s+|never\s+)?"
               r"(?:like|love|prefer|hate|dislike|enjoy|use|work (?:at|as|in|on)|study|live in|speak)\b", re.I),
    re.compile(r"^my\s+(?:[\w'-]+\s+){0,4}(?:is|are|was)\s+\S", re.I),
    re.compile(r"^call me\s+\S", re.I),
    re.compile(r"^(?:from now on|in future|in the future)\b", re.I),
    re.compile(r"^(?:i'm|i am)\s+(?:a|an)\s+\S", re.I),
]
_QUESTION_START = re.compile(r"^(?:what|who|why|how|when|where|which|is|are|do|does|did|can|could|should|would)\b", re.I)


def extract_preference(utterance: str) -> str | None:
    """Returns the statement worth remembering, or None."""
    text = (utterance or "").strip().rstrip(".!")
    if len(text) < 8 or len(text) > 220 or text.endswith("?") or _QUESTION_START.match(text):
        return None
    if SENSITIVE.search(text) or len(text.split()) > 30:
        return None
    if _COMMANDISH.search(text) or "," in text or " but " in text.lower():
        return None  # "I'm going out, remind me at 6" is a command, not a preference
    if any(p.match(text) for p in _PREF_PATTERNS):
        return text[0].upper() + text[1:]
    return None


def _to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class SemanticMemory:
    def __init__(self, db_path: str | Path | None = None, embedder=None, legacy_json: str | Path | None = None):
        base = Path(__file__).parent.parent
        self.db_path = Path(db_path) if db_path else base / "mxb_memory.db"
        if embedder is None:
            from engine.embeddings import Embedder
            embedder = Embedder()
        self.embedder = embedder
        self._lock = threading.Lock()
        self._init_db()
        self._migrate_legacy(Path(legacy_json) if legacy_json else base / "memory_bank.json")

    # ------------------------------------------------------------------ db plumbing
    def _conn(self):
        return sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10)

    def _init_db(self):
        with self._lock, self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY, text TEXT UNIQUE, kind TEXT, created REAL, last_used REAL,
                uses INTEGER DEFAULT 0, space TEXT, vec BLOB)""")
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def _meta(self, key: str, value: str | None = None) -> str | None:
        with self._conn() as c:
            if value is None:
                row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                return row[0] if row else None
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
            return value

    def _migrate_legacy(self, legacy: Path):
        try:
            if self._meta("legacy_imported") or not legacy.exists():
                return
            facts = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(facts, dict):
                facts = facts.get("memories", [])
            count = sum(1 for f in facts if isinstance(f, str) and self.add(f, kind="fact"))
            self._meta("legacy_imported", str(time.time()))
            if count:
                log.info(f"SemanticMemory: imported {count} facts from {legacy.name}.")
        except Exception as e:
            log.warning(f"SemanticMemory: legacy import skipped: {e}")

    def _rows(self):
        with self._conn() as c:
            return c.execute("SELECT id, text, kind, space, vec FROM memories").fetchall()

    def _reembed_stale(self, rows):
        space = self.embedder.space
        stale = [r for r in rows if r[3] != space or r[4] is None]
        if not stale:
            return rows
        vecs = self.embedder.embed([r[1] for r in stale], kind="passage")
        with self._lock, self._conn() as c:
            for r, v in zip(stale, vecs):
                c.execute("UPDATE memories SET space=?, vec=? WHERE id=?", (space, _to_blob(v), r[0]))
        return self._rows()

    # ------------------------------------------------------------------ public API
    def add(self, text: str, kind: str = "fact") -> bool:
        text = (text or "").strip()
        if not text:
            return False
        vec = self.embedder.embed([text], kind="passage")[0]
        for _id, existing, _kind, space, blob in self._rows():
            if existing.lower() == text.lower():
                return False
            if space == self.embedder.space and blob is not None:
                if float(np.dot(_from_blob(blob), vec)) >= 0.97:
                    return False  # near-duplicate
        now = time.time()
        try:
            with self._lock, self._conn() as c:
                c.execute("INSERT INTO memories(text, kind, created, last_used, uses, space, vec) VALUES(?,?,?,?,0,?,?)",
                          (text, kind, now, now, self.embedder.space, _to_blob(vec)))
            log.info(f"SemanticMemory: stored {kind}: '{text}'")
            return True
        except sqlite3.IntegrityError:
            return False

    def search(self, query: str, k: int = 5, min_score: float = 0.2) -> list[tuple[str, float, str]]:
        rows = self._reembed_stale(self._rows())
        if not rows or not (query or "").strip():
            return []
        q = self.embedder.embed([query], kind="query")[0]
        scored = []
        for _id, text, kind, _space, blob in rows:
            if blob is None:
                continue
            v = _from_blob(blob)
            if v.shape != q.shape:
                continue
            scored.append((float(np.dot(v, q)), text, kind, _id))
        scored.sort(reverse=True)
        hits = [(t, s, kd) for s, t, kd, _ in scored[:k] if s >= min_score]
        if hits:
            ids = [i for s, _t, _k, i in scored[:k] if s >= min_score]
            with self._lock, self._conn() as c:
                c.executemany("UPDATE memories SET uses=uses+1, last_used=? WHERE id=?", [(time.time(), i) for i in ids])
        return hits

    def recall_texts(self, query: str, k: int = 5) -> list[str]:
        return [t for t, _s, _k in self.search(query, k)]

    def list_all(self, limit: int = 30) -> list[tuple[str, str]]:
        with self._conn() as c:
            return c.execute("SELECT text, kind FROM memories ORDER BY created DESC LIMIT ?", (limit,)).fetchall()

    def forget(self, query: str, min_score: float = 0.55) -> list[str]:
        """Deletes memories that contain the query text or match it strongly."""
        query = (query or "").strip()
        if not query:
            return []
        targets = []
        for _id, text, _kind, _space, _blob in self._rows():
            if query.lower() in text.lower():
                targets.append((_id, text))
        if not targets:
            for text, score, _kind in self.search(query, k=3, min_score=min_score):
                targets += [(r[0], r[1]) for r in self._rows() if r[1] == text]
        if targets:
            with self._lock, self._conn() as c:
                c.executemany("DELETE FROM memories WHERE id=?", [(i,) for i, _ in targets])
        return [t for _, t in targets]

    def count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def learn_from_utterance(self, utterance: str) -> str | None:
        pref = extract_preference(utterance)
        if pref and self.add(pref, kind="preference"):
            return pref
        return None
