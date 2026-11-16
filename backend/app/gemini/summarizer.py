"""Grounded explanations, summaries and insights for the final results (one call)."""

from __future__ import annotations

import logging

from ..ranking import Query, Ranked
from .client import GeminiService, GeminiUnavailable
from .grounding import Source, clean_list, clean_text, section_numbers
from .insights import validate_insights
from .reranker import reader_block

log = logging.getLogger("intellidoc.summarize")

SYSTEM = (
    "You are IntelliDoc, a careful research assistant. You explain document passages to a specific reader. "
    "Use ONLY the passages provided — never outside knowledge, never invent sections, page numbers, figures "
    "or quotations. If a passage doesn't state something, don't claim it. Write plainly for the reader's "
    "expertise level. Return only the requested JSON."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "why": {"type": "string"},
                    "summary": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "takeaways": {"type": "array", "items": {"type": "string"}},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "why", "summary"],
            },
        },
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["theme", "relationship", "contradiction", "repetition", "risk", "gap"]},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "result_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "title", "text", "result_ids"],
            },
        },
    },
    "required": ["results", "insights"],
}

INSTRUCTIONS = """For EACH passage id, write:
- why: 1–2 sentences on why this passage matters for the reader's objective.
- summary: 2–3 sentences summarizing what the passage says.
- findings: up to 3 specific facts or results the passage states.
- takeaways: up to 3 practical takeaways for this reader.
- limitations: caveats or limitations ONLY if the passage states them; otherwise [].
Then write 3–5 insights across the passages (themes, relationships between passages, contradictions,
repeated findings, risks, or information relevant to the objective that the passages do NOT cover).
Each insight must list the passage ids that support it in result_ids.
Do not quote text. Do not mention page numbers. Keep every string short."""


def enrich(svc: GeminiService, results: list[dict], ranked: list[Ranked], q: Query) -> list[dict] | None:
    """Mutate results with grounded AI fields. Returns validated insights, or None if the call failed."""
    from ..retrieval.hybrid import passage

    if not results:
        return None
    by_id: dict[str, tuple[dict, str]] = {}
    blocks = []
    for res, r in zip(results, ranked):
        rid = f"R{res['rank']}"
        text = passage(r, q, 300)
        by_id[rid] = (res, text)
        blocks.append(f"[{rid}] Section: {' > '.join(res['breadcrumb'])}\n{text}")
    prompt = f"{reader_block(q)}\n\nPASSAGES\n" + "\n\n".join(blocks) + "\n\n" + INSTRUCTIONS
    try:
        data = svc.generate_json(SYSTEM, prompt, SCHEMA, max_tokens=4096, timeout_s=60)
    except GeminiUnavailable as exc:
        log.info("Summaries skipped: %s", exc)
        return None
    if not isinstance(data, dict):
        return None

    nums = section_numbers([t for res in results for t in res["breadcrumb"]])
    seen: set[str] = set()
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id", "")).strip().strip("[]")
        if rid not in by_id or rid in seen:
            continue
        seen.add(rid)
        res, text = by_id[rid]
        src = Source([text], set(range(res["page_start"], res["page_end"] + 1)), nums)
        why = clean_text(item.get("why"), src, 400)
        summary = clean_text(item.get("summary"), src, 600)
        if why:
            res["why_relevant"] = why
        res["summary"] = summary
        res["findings"] = clean_list(item.get("findings"), src, 3)
        res["takeaways"] = clean_list(item.get("takeaways"), src, 3)
        res["limitations"] = clean_list(item.get("limitations"), src, 3)
    if seen:
        log.info("Enriched %d/%d results", len(seen), len(results))
    return validate_insights(data.get("insights"), {rid: v for rid, v in by_id.items()}, nums)
