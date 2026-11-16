"""Embedding-based semantic similarity, normalized to a 0–1 ranking signal."""

from __future__ import annotations

import logging

import numpy as np

from ..gemini.client import GeminiService, GeminiUnavailable
from ..gemini.embeddings import chunk_text_for_embedding, embed_texts, query_text
from ..sections import Chunk

log = logging.getLogger("intellidoc.semantic")

MAX_EMBED_CHUNKS = 500  # very long documents: embed the strongest local candidates only
SPREAD_FLOOR = 0.10     # a chunk only reaches 1.0 if it stands this far above the median


def normalize_similarity(cos: np.ndarray) -> np.ndarray:
    """Map raw cosine similarities to 0–1 relative to the document's own baseline.

    Embedding cosines have a high floor between any two texts, so the median chunk is treated as
    "unrelated" (0). A chunk reaches 1 only if it is clearly separated from that baseline, which keeps
    off-topic queries (where nothing stands out) from producing confident-looking scores.
    """
    if cos.size == 0:
        return cos
    med = float(np.median(cos))
    spread = max(float(cos.max()) - med, SPREAD_FLOOR)
    return np.clip((cos - med) / spread, 0.0, 1.0)


def chunk_embeddings(svc: GeminiService, chunks: list[Chunk], prefilter: np.ndarray | None = None
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Embed chunks (capped for very long docs). Returns (matrix, indices of embedded chunks)."""
    idx = np.arange(len(chunks))
    if len(chunks) > MAX_EMBED_CHUNKS and prefilter is not None:
        idx = np.sort(np.argsort(-prefilter)[:MAX_EMBED_CHUNKS])
    texts = [chunk_text_for_embedding(chunks[i].section.path, chunks[i].text) for i in idx]
    return embed_texts(svc, texts, "RETRIEVAL_DOCUMENT"), idx


def semantic_scores(svc: GeminiService, chunks: list[Chunk], objective: str, persona: str, expertise: str,
                    focus_terms: list[str], prefilter: np.ndarray | None = None
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Return (normalized scores for every chunk, chunk matrix, embedded indices) or None on failure."""
    try:
        mat, idx = chunk_embeddings(svc, chunks, prefilter)
        q = embed_texts(svc, [query_text(objective, persona, expertise, focus_terms)], "RETRIEVAL_QUERY")[0]
    except GeminiUnavailable as exc:
        log.info("Semantic embeddings unavailable (%s); using local similarity", exc)
        return None
    cos = mat @ q
    scores = np.zeros(len(chunks), dtype=np.float32)
    scores[idx] = normalize_similarity(cos)
    return scores, mat, idx
