"""
Text embeddings for memory and document search.

Providers (config memory.embedding_provider):
- "auto"  : local Ollama embedding model if Ollama is running (private), else the local
            hashing embedder. Cloud is never used implicitly, because documents are private.
- "ollama": Ollama /api/embed (default model nomic-embed-text; `ollama pull nomic-embed-text`).
- "nvidia": NVIDIA Build /v1/embeddings (nvidia/nv-embedqa-e5-v5) with query/passage input types.
- "local" : dependency-free feature-hashing embedder (keyword-level similarity, always works).

Every vector is L2-normalized float32, so cosine similarity is a dot product.
`space` names the vector space; stores re-embed when it changes.
"""
import math
import re
import zlib
import numpy as np
import requests
from utils.credentials import CredentialsManager
from utils.logger import log

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "it", "this",
         "that", "with", "as", "at", "by", "be", "my", "me", "i", "you", "what", "do", "does", "about", "from"}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP]


def hash_embed(texts: list[str], dim: int = 512) -> np.ndarray:
    """Signed feature hashing of unigrams + bigrams with sublinear TF. Stable across runs."""
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        toks = tokens(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        counts: dict[str, int] = {}
        for f in feats:
            counts[f] = counts.get(f, 0) + 1
        for f, c in counts.items():
            h = zlib.crc32(f.encode("utf-8"))
            weight = (1.0 + math.log(c)) * (0.6 if "_" in f else 1.0)
            out[row, h % dim] += weight if (h >> 31) & 1 else -weight
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return out / norms


def normalize_rows(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class Embedder:
    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("memory", {}) if isinstance(config, dict) else {}
        llm = (config or {}).get("llm", {}) if isinstance(config, dict) else {}
        self.provider_setting = cfg.get("embedding_provider", "auto")
        self.ollama_model = cfg.get("ollama_embedding_model", "nomic-embed-text")
        self.nvidia_model = cfg.get("nvidia_embedding_model", "nvidia/nv-embedqa-e5-v5")
        base = llm.get("ollama_url", "http://localhost:11434/api/chat")
        self.ollama_embed_url = base.rsplit("/api/", 1)[0] + "/api/embed"
        self.nvidia_url = cfg.get("nvidia_embedding_url", "https://integrate.api.nvidia.com/v1/embeddings")
        self.hash_dim = int(cfg.get("hash_dim", 512))
        self._provider = None

    # ------------------------------------------------------------------ provider resolution
    @property
    def provider(self) -> str:
        if self._provider is None:
            setting = self.provider_setting.lower()
            if setting == "auto":
                self._provider = "ollama" if self._ollama_ok() else "local"
            else:
                self._provider = setting
            log.info(f"Embeddings: using '{self._provider}' provider.")
        return self._provider

    @property
    def space(self) -> str:
        p = self.provider
        if p == "ollama":
            return f"ollama:{self.ollama_model}"
        if p == "nvidia":
            return f"nvidia:{self.nvidia_model}"
        return f"hash:{self.hash_dim}"

    def _ollama_ok(self) -> bool:
        try:
            r = requests.post(self.ollama_embed_url, json={"model": self.ollama_model, "input": ["ping"]}, timeout=3)
            return r.status_code == 200 and bool(r.json().get("embeddings"))
        except Exception:
            return False

    # ------------------------------------------------------------------ embedding
    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        texts = [t if t.strip() else " " for t in texts]
        if not texts:
            return np.zeros((0, self.hash_dim), dtype=np.float32)
        try:
            if self.provider == "ollama":
                return self._embed_ollama(texts)
            if self.provider == "nvidia":
                return self._embed_nvidia(texts, kind)
        except Exception as e:
            log.warning(f"Embeddings: {self.provider} failed ({e}); using local hashing for this session.")
            self._provider = "local"
        return hash_embed(texts, self.hash_dim)

    def _embed_ollama(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for i in range(0, len(texts), 32):
            r = requests.post(self.ollama_embed_url, json={"model": self.ollama_model, "input": texts[i:i + 32]}, timeout=60)
            r.raise_for_status()
            vecs.extend(r.json()["embeddings"])
        return normalize_rows(np.array(vecs, dtype=np.float32))

    def _embed_nvidia(self, texts: list[str], kind: str) -> np.ndarray:
        key = CredentialsManager.get_nvidia_api_key()
        if not key:
            raise RuntimeError("NVIDIA_API_KEY not set")
        vecs = []
        for i in range(0, len(texts), 32):
            payload = {"model": self.nvidia_model, "input": texts[i:i + 32], "encoding_format": "float",
                       "input_type": "query" if kind == "query" else "passage", "truncate": "END"}
            r = requests.post(self.nvidia_url, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=60)
            r.raise_for_status()
            vecs.extend(item["embedding"] for item in r.json()["data"])
        return normalize_rows(np.array(vecs, dtype=np.float32))
