"""Hybrid retrieval: local signals + embedding similarity + reranker judgment, with safe fallbacks.

Paths (chosen automatically, never surfaced to the UI):
  full     embeddings ✓  rerank ✓   → HYBRID_WEIGHTS with contextual relevance
  semantic embeddings ✓  rerank ✗   → HYBRID_WEIGHTS, contextual weight redistributed
  rerank   embeddings ✗  rerank ✓   → LOCAL_WEIGHTS + contextual relevance
  local    neither                  → original local engine
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from ..config import HYBRID_WEIGHTS, LOCAL_WEIGHTS, RERANK_CANDIDATES
from ..gemini.client import GeminiService
from ..ranking import Query, Ranked, Scored, aggregate, combine, compute_signals, meta_for
from ..sections import Chunk
from ..text_utils import content_stems
from .semantic import semantic_scores

log = logging.getLogger("intellidoc.hybrid")


@dataclass
class HybridOutcome:
    ranked: list[Ranked]
    meta: dict
    path: str
    chunk_matrix: np.ndarray | None = None  # kept in the session for follow-up questions
    embedded_idx: np.ndarray | None = None
    priorities: dict[str, int] = field(default_factory=dict)


def passage(r: Ranked, q: Query, max_words: int = 260) -> str:
    """The most objective-relevant window of a result's span (keeps prompts small)."""
    text = r.section.text[r.start:r.end]
    ws = text.split()
    if len(ws) <= max_words:
        return " ".join(ws)
    keys = set(q.key_terms)
    hits = [1 if set(content_stems(w)) & keys else 0 for w in ws]
    best, best_i, run = -1, 0, sum(hits[:max_words])
    for i in range(0, len(ws) - max_words + 1):
        if i:
            run += hits[i + max_words - 1] - hits[i - 1]
        if run > best:
            best, best_i = run, i
    return ("… " if best_i else "") + " ".join(ws[best_i:best_i + max_words]) + " …"


def rank_hybrid(chunks: list[Chunk], q: Query, svc: GeminiService | None) -> HybridOutcome:
    from ..gemini.reranker import rerank  # local import keeps the local path import-light

    scored, tfidf_raw = compute_signals(chunks, q)
    mat = idx = None
    semantic_ok = False

    if svc and svc.available("embed"):
        sem = semantic_scores(svc, chunks, q.objective, q.persona, q.expertise, q.focus_terms, prefilter=tfidf_raw)
        if sem is not None:
            scores, mat, idx = sem
            for s, v in zip(scored, scores):
                s.signals["semantic"] = float(v)
            semantic_ok = True

    base = dict(HYBRID_WEIGHTS if semantic_ok else LOCAL_WEIGHTS)
    pre = dict(base, contextual=0.0)
    w = combine(scored, q, pre)

    if svc and svc.available("generate"):
        cands = aggregate(scored, q, limit=RERANK_CANDIDATES, relaxed=True)
        judged = rerank(svc, cands, q) if cands else None
        if judged:
            relevance, priorities = judged
            cand_ids = {r.section.id for r in cands}
            subset: list[Scored] = [s for s in scored if s.chunk.section.id in cand_ids]
            for s in subset:
                v = relevance.get(s.chunk.section.id)
                if v is not None:
                    s.signals["contextual"] = v
                    s.contextual_measured = True
                else:
                    s.signals["contextual"] = 0.5  # unassessed: neutral, never decisive
            final = dict(base, contextual=HYBRID_WEIGHTS["contextual"])
            w = combine(subset, q, final)
            ranked = aggregate(subset, q)
            ranked.sort(key=lambda r: (-round(r.score, 2), priorities.get(r.section.id, 99)))
            path = "full" if semantic_ok else "rerank"
            log.info("Ranking path: %s (%d candidates → %d results)", path, len(cands), len(ranked))
            return HybridOutcome(ranked, meta_for(subset, q, w), path, mat, idx, priorities)

    ranked = aggregate(scored, q)
    path = "semantic" if semantic_ok else "local"
    log.info("Ranking path: %s (%d results)", path, len(ranked))
    return HybridOutcome(ranked, meta_for(scored, q, w), path, mat, idx)


SECTION_REF_RE = re.compile(r"\bsections?\s+((?:\d+(?:\.\d+)*)(?:\s*(?:,|and|&)\s*\d+(?:\.\d+)*)*)", re.I)
