"""
Personal knowledge base: "MXB, index my Notes folder" -> "What does my SIH plan say about the deadline?"

- Indexes text, Markdown, code, PDF and Word files in folders the user has granted.
- Incremental: only new/changed files are re-read; deleted files are dropped.
- Hybrid retrieval: embedding cosine similarity + keyword overlap.
- Answers are generated only from retrieved passages and cite the source files.
- Stored locally in mxb_knowledge.db.
"""
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
import numpy as np
from engine.embeddings import tokens
from utils.logger import log

INDEXABLE = {".txt", ".md", ".pdf", ".docx", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs",
             ".json", ".csv", ".html", ".css", ".tex", ".rst", ".yaml", ".yml", ".ini", ".toml", ".sql", ".ipynb"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", "$recycle.bin",
             "appdata", "site-packages", ".cache", ".idea", ".vscode"}
MAX_FILE_BYTES = 25 * 1024 * 1024

ANSWER_SYSTEM = ("You answer questions using ONLY the numbered passages from the user's own files. "
                 "Cite passages like [1] or [2]. If the passages don't contain the answer, say you couldn't find it "
                 "in their documents. Be concise: at most 4 sentences, no markdown.")


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunking with character overlap."""
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for para in paras:
        while len(para) > size:
            cut = para.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            piece, para = para[:cut].strip(), para[cut:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    if overlap and len(chunks) > 1:
        out = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            out.append((prev[-overlap:] + " " + cur).strip())
        return out
    return chunks


def keyword_score(query: str, passage: str) -> float:
    q = set(tokens(query))
    if not q:
        return 0.0
    p = set(tokens(passage))
    return len(q & p) / len(q)


class KnowledgeBase:
    def __init__(self, db_path: str | Path | None = None, embedder=None, file_ops=None,
                 chunk_chars: int = 900, overlap: int = 150):
        self.db_path = Path(db_path) if db_path else Path(__file__).parent.parent / "mxb_knowledge.db"
        if embedder is None:
            from engine.embeddings import Embedder
            embedder = Embedder()
        self.embedder = embedder
        self.file_ops = file_ops
        self.chunk_chars = chunk_chars
        self.overlap = overlap
        self._lock = threading.Lock()
        self.indexing = False
        self._init_db()

    def _conn(self):
        return sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)

    def _init_db(self):
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS folders (path TEXT PRIMARY KEY, added REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS docs (path TEXT PRIMARY KEY, folder TEXT, mtime REAL, size INTEGER, "
                      "chunks INTEGER, indexed_at REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, path TEXT, idx INTEGER, text TEXT, "
                      "space TEXT, vec BLOB)")
            c.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")

    # ------------------------------------------------------------------ indexing
    def _allowed(self, path: Path) -> bool:
        if self.file_ops is None or getattr(self.file_ops, "access", None) is None:
            return True
        return self.file_ops.access.can_read(path)

    def _extract(self, path: Path) -> str:
        if self.file_ops is not None:
            res = self.file_ops.read_file_text(str(path), max_chars=400_000)
            return "" if res.get("error") else res.get("text", "")
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def index_folder(self, folder: str | Path, progress=None, max_files: int = 3000, time_budget: float = 900.0) -> dict:
        root = Path(folder)
        if not root.is_dir():
            return {"error": f"Folder not found: {folder}"}
        if not self._allowed(root):
            return {"error": f"I don't have access to {root}. Say 'give access to {root}' first."}
        self.indexing = True
        start = time.time()
        stats = {"folder": str(root), "indexed": 0, "unchanged": 0, "skipped": 0, "removed": 0, "chunks": 0}
        try:
            with self._conn() as c:
                c.execute("INSERT OR REPLACE INTO folders(path, added) VALUES(?, ?)", (str(root), time.time()))
                known = {r[0]: (r[1], r[2]) for r in c.execute("SELECT path, mtime, size FROM docs WHERE folder=?", (str(root),))}
            seen = set()
            files = 0
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
                for name in filenames:
                    if time.time() - start > time_budget or files >= max_files:
                        break
                    path = Path(dirpath) / name
                    if path.suffix.lower() not in INDEXABLE:
                        continue
                    files += 1
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    seen.add(str(path))
                    if st.st_size > MAX_FILE_BYTES or not self._allowed(path):
                        stats["skipped"] += 1
                        continue
                    if known.get(str(path)) == (st.st_mtime, st.st_size):
                        stats["unchanged"] += 1
                        continue
                    n = self._index_file(path, root, st)
                    if n:
                        stats["indexed"] += 1
                        stats["chunks"] += n
                    else:
                        stats["skipped"] += 1
                    if progress and stats["indexed"] % 10 == 0 and n:
                        progress(f"Indexed {stats['indexed']} files from {root.name}...")
            removed = [p for p in known if p not in seen and not Path(p).exists()]
            if removed:
                with self._lock, self._conn() as c:
                    c.executemany("DELETE FROM chunks WHERE path=?", [(p,) for p in removed])
                    c.executemany("DELETE FROM docs WHERE path=?", [(p,) for p in removed])
                stats["removed"] = len(removed)
        finally:
            self.indexing = False
        stats["seconds"] = round(time.time() - start, 1)
        log.info(f"Knowledge: indexed {stats}")
        return stats

    def _index_file(self, path: Path, root: Path, st) -> int:
        text = self._extract(path)
        pieces = chunk_text(f"{path.name}\n\n{text}", self.chunk_chars, self.overlap) if text.strip() else []
        if not pieces:
            return 0
        vecs = self.embedder.embed(pieces, kind="passage")
        space = self.embedder.space
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM chunks WHERE path=?", (str(path),))
            c.executemany("INSERT INTO chunks(path, idx, text, space, vec) VALUES(?,?,?,?,?)",
                          [(str(path), i, t, space, np.asarray(v, dtype=np.float32).tobytes())
                           for i, (t, v) in enumerate(zip(pieces, vecs))])
            c.execute("INSERT OR REPLACE INTO docs(path, folder, mtime, size, chunks, indexed_at) VALUES(?,?,?,?,?,?)",
                      (str(path), str(root), st.st_mtime, st.st_size, len(pieces), time.time()))
        return len(pieces)

    # ------------------------------------------------------------------ retrieval
    def search(self, query: str, k: int = 6) -> list[dict]:
        space = self.embedder.space
        with self._conn() as c:
            rows = c.execute("SELECT path, idx, text, vec FROM chunks WHERE space=?", (space,)).fetchall()
            stale = c.execute("SELECT COUNT(*) FROM chunks WHERE space<>?", (space,)).fetchone()[0]
        if stale:
            log.warning(f"Knowledge: {stale} chunks were embedded with another model; re-index to include them.")
        if not rows or not query.strip():
            return []
        q = self.embedder.embed([query], kind="query")[0]
        mat = np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
        cos = mat @ q
        results = []
        for (path, idx, text, _), score in zip(rows, cos):
            hybrid = float(score) + 0.25 * keyword_score(query, text)
            results.append({"path": path, "idx": idx, "text": text, "score": hybrid})
        results.sort(key=lambda r: r["score"], reverse=True)
        out, per_file = [], {}
        for r in results:
            if per_file.get(r["path"], 0) >= 2:
                continue  # diversity: at most 2 passages per file
            per_file[r["path"]] = per_file.get(r["path"], 0) + 1
            out.append(r)
            if len(out) >= k:
                break
        return out

    def answer(self, question: str, llm=None, k: int = 6) -> str:
        hits = [h for h in self.search(question, k) if h["score"] > 0.15]
        if not hits:
            return "I couldn't find anything about that in your indexed documents."
        context = "\n\n".join(f"[{i}] ({Path(h['path']).name}) {h['text'][:1200]}" for i, h in enumerate(hits, 1))
        sources = []
        for h in hits:
            name = Path(h["path"]).name
            if name not in sources:
                sources.append(name)
        if llm is None:
            return f"Closest match in {Path(hits[0]['path']).name}: {hits[0]['text'][:400]}"
        answer = llm.chat(ANSWER_SYSTEM, f"PASSAGES:\n{context}\n\nQUESTION: {question}", max_tokens=350, json_mode=False)
        if not answer:
            return f"I found it in {sources[0]} but couldn't reach my reasoning engine. Closest passage: {hits[0]['text'][:300]}"
        return f"{answer.strip()}\nSources: {', '.join(sources[:4])}"

    # ------------------------------------------------------------------ management
    def status(self) -> str:
        with self._conn() as c:
            folders = [r[0] for r in c.execute("SELECT path FROM folders")]
            docs = c.execute("SELECT COUNT(*), COALESCE(SUM(chunks), 0) FROM docs").fetchone()
        if not folders:
            return "No folders are indexed yet. Say 'index my Documents folder' to start."
        busy = " (indexing now)" if self.indexing else ""
        return f"Indexed {docs[0]} documents ({docs[1]} passages) from: {', '.join(folders)}{busy}."

    def forget_folder(self, folder: str) -> str:
        target = str(Path(folder))
        with self._lock, self._conn() as c:
            paths = [r[0] for r in c.execute("SELECT path FROM docs WHERE folder=?", (target,))]
            c.executemany("DELETE FROM chunks WHERE path=?", [(p,) for p in paths])
            c.execute("DELETE FROM docs WHERE folder=?", (target,))
            c.execute("DELETE FROM folders WHERE path=?", (target,))
        return f"Removed {len(paths)} documents from {target} from my index." if paths else f"{target} wasn't indexed."

    def indexed_folders(self) -> list[str]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT path FROM folders")]
