"""Reasoning-based reranking of retrieved candidates. Lean output to conserve quota."""

from __future__ import annotations

import logging

from ..ranking import Query, Ranked
from .client import GeminiService, GeminiUnavailable

log = logging.getLogger("intellidoc.rerank")

RELEVANCE_TO_SIGNAL = {3: 1.0, 2: 0.7, 1: 0.3, 0: 0.0}
MIN_COVERAGE = 0.6

SYSTEM = (
    "You assess whether document passages are useful for a specific reader's objective. "
    "Judge ONLY from the passage text supplied. Do not use outside knowledge about the document. "
    "Return only the requested JSON."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevance": {"type": "integer", "minimum": 0, "maximum": 3},
                    "priority": {"type": "integer", "minimum": 1},
                },
                "required": ["id", "relevance"],
            },
        }
    },
    "required": ["assessments"],
}


def reader_block(q: Query) -> str:
    lines = [f"Reader role: {q.persona}", f"Expertise: {q.expertise}", f"Objective: {q.objective}"]
    if q.focus_terms:
        lines.append(f"Focus terms: {', '.join(q.focus_terms)}")
    return "\n".join(lines)


def build_prompt(cands: list[Ranked], q: Query) -> tuple[str, dict[str, str]]:
    from ..retrieval.hybrid import passage

    ids: dict[str, str] = {}
    blocks = []
    for i, r in enumerate(cands, start=1):
        cid = f"C{i}"
        ids[cid] = r.section.id
        pages = f"{r.section.page_at(r.start)}–{r.section.page_at(max(r.start, r.end - 1))}"
        blocks.append(f"[{cid}] Section: {' > '.join(r.section.path)} | Pages: {pages}\n{passage(r, q, 180)}")
    prompt = (
        f"{reader_block(q)}\n\nPASSAGES\n" + "\n\n".join(blocks) +
        "\n\nFor EVERY passage id above, rate how useful it is for this reader's objective:\n"
        "3 = essential, 2 = useful, 1 = marginal, 0 = not relevant.\n"
        "Also give `priority`: suggested reading order among passages rated 2 or 3 (1 = read first).\n"
        "Use only the ids listed. Judge only what the passage text actually says."
    )
    return prompt, ids


def rerank(svc: GeminiService, cands: list[Ranked], q: Query) -> tuple[dict[str, float], dict[str, int]] | None:
    """Return ({section_id: contextual signal}, {section_id: priority}) or None to fall back."""
    prompt, ids = build_prompt(cands, q)
    try:
        data = svc.generate_json(SYSTEM, prompt, SCHEMA, max_tokens=1200, timeout_s=35)
    except GeminiUnavailable as exc:
        log.info("Rerank skipped: %s", exc)
        return None
    return validate(data, ids)


def validate(data: object, ids: dict[str, str]) -> tuple[dict[str, float], dict[str, int]] | None:
    items = data.get("assessments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        log.info("Rerank rejected: malformed response")
        return None
    relevance: dict[str, float] = {}
    priority: dict[str, int] = {}
    invalid = 0
    for it in items:
        if not isinstance(it, dict):
            invalid += 1
            continue
        cid = str(it.get("id", "")).strip().strip("[]")
        sid = ids.get(cid)
        rel = it.get("relevance")
        if sid is None or sid in relevance or not isinstance(rel, (int, float)) or isinstance(rel, bool):
            invalid += 1
            continue
        rel = int(max(0, min(3, round(rel))))
        relevance[sid] = RELEVANCE_TO_SIGNAL[rel]
        p = it.get("priority")
        if isinstance(p, int) and not isinstance(p, bool) and p >= 1 and rel >= 2:
            priority[sid] = p
    if invalid:
        log.info("Rerank: ignored %d invalid assessment(s)", invalid)
    if len(relevance) < MIN_COVERAGE * len(ids):
        log.info("Rerank rejected: only %d/%d candidates assessed", len(relevance), len(ids))
        return None
    return relevance, priority
