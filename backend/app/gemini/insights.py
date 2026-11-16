"""Validation for cross-section insights: every insight must cite real results."""

from __future__ import annotations

from .grounding import Source, clean_text

KINDS = {"theme", "relationship", "contradiction", "repetition", "risk", "gap"}
TITLES = {
    "theme": "A central theme",
    "relationship": "How sections connect",
    "contradiction": "A tension between sections",
    "repetition": "A repeated finding",
    "risk": "A risk to note",
    "gap": "What these sections don't cover",
}


def validate_insights(items: object, by_id: dict[str, tuple[dict, str]], section_nums: set[str]) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = it.get("kind") if it.get("kind") in KINDS else None
        refs = it.get("result_ids")
        if not kind or not isinstance(refs, list):
            continue
        valid = []
        for ref in refs:
            rid = str(ref).strip().strip("[]")
            if rid in by_id and rid not in valid:
                valid.append(rid)
        if not valid:
            continue  # unsupported insight: drop
        results = [by_id[r][0] for r in valid]
        pages = sorted({p for res in results for p in range(res["page_start"], res["page_end"] + 1)})
        src = Source([by_id[r][1] for r in valid], set(pages), section_nums)
        text = clean_text(it.get("text"), src, 360)
        if len(text) < 20:
            continue
        title = clean_text(it.get("title"), src, 70) or TITLES[kind]
        out.append({
            "kind": kind,
            "title": title.rstrip("."),
            "text": text,
            "result_ids": [res["id"] for res in results],
            "pages": pages if len(pages) <= 12 else sorted({res["page_start"] for res in results}),
        })
        if len(out) >= 5:
            break
    return out
