"""Short-lived, in-memory analysis sessions for follow-up questions.

Holds extracted sections/chunks (not the PDF bytes), the reader profile, result ids, optional chunk
embeddings and a bounded conversation history. Nothing is written to disk; sessions expire.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

import numpy as np

from .ranking import Query
from .sections import Chunk, Section

TTL_S = 45 * 60
MAX_SESSIONS = 12
MAX_TURNS = 6


@dataclass
class Session:
    id: str
    filename: str
    sections: list[Section]
    chunks: list[Chunk]
    query: Query
    results: list[dict]  # [{id, section_id}] in rank order
    chunk_matrix: np.ndarray | None = None
    embedded_idx: np.ndarray | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=MAX_TURNS))
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    def __init__(self):
        self._d: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def create(self, **kwargs) -> Session:
        s = Session(id=secrets.token_urlsafe(16), **kwargs)
        with self._lock:
            self._evict()
            self._d[s.id] = s
            while len(self._d) > MAX_SESSIONS:
                self._d.popitem(last=False)
        return s

    def get(self, sid: str) -> Session | None:
        with self._lock:
            self._evict()
            s = self._d.get(sid)
            if s:
                s.touched = time.monotonic()
                self._d.move_to_end(sid)
            return s

    def _evict(self) -> None:
        now = time.monotonic()
        for k in [k for k, s in self._d.items() if now - s.touched > TTL_S]:
            del self._d[k]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


store = SessionStore()
