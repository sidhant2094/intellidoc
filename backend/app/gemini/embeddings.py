"""Chunk / query embeddings with a bounded, in-memory, TTL cache (never written to disk)."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

import numpy as np

from .client import GeminiService

CACHE_MAX = 6000
CACHE_TTL_S = 3600
MAX_CHUNK_CHARS = 6000  # ~1.5k tokens: inside the embedding model's input limit


class _Cache:
    def __init__(self):
        self._d: OrderedDict[str, tuple[float, np.ndarray]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> np.ndarray | None:
        with self._lock:
            hit = self._d.get(key)
            if not hit:
                return None
            ts, vec = hit
            if time.monotonic() - ts > CACHE_TTL_S:
                del self._d[key]
                return None
            self._d.move_to_end(key)
            return vec

    def put(self, key: str, vec: np.ndarray) -> None:
        with self._lock:
            self._d[key] = (time.monotonic(), vec)
            self._d.move_to_end(key)
            while len(self._d) > CACHE_MAX:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


cache = _Cache()


def _key(svc: GeminiService, task: str, text: str) -> str:
    h = hashlib.sha256(f"{svc.settings.embedding_model}|{svc.settings.embedding_dim}|{task}|{text}".encode()).hexdigest()
    return h


def embed_texts(svc: GeminiService, texts: list[str], task: str) -> np.ndarray:
    """Embed with de-duplication and caching. Raises GeminiUnavailable on failure."""
    texts = [t[:MAX_CHUNK_CHARS] for t in texts]
    keys = [_key(svc, task, t) for t in texts]
    missing: dict[str, str] = {}
    for k, t in zip(keys, texts):
        if cache.get(k) is None and k not in missing:
            missing[k] = t
    if missing:
        vecs = svc.embed(list(missing.values()), task)
        for k, v in zip(missing.keys(), vecs):
            cache.put(k, v)
    return np.vstack([cache.get(k) for k in keys])


def chunk_text_for_embedding(path: list[str], text: str) -> str:
    return f"{' › '.join(path)}\n{text}"


def query_text(objective: str, persona: str, expertise: str, focus_terms: list[str]) -> str:
    parts = [f"Find passages that answer: {objective}"]
    if focus_terms:
        parts.append(f"Key topics: {', '.join(focus_terms)}")
    parts.append(f"Reader: {persona} ({expertise.lower()} level)")
    return "\n".join(parts)
