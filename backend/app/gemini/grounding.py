"""Guards that keep model-written text tied to the passages it was given.

These are conservative, deterministic checks — not a guarantee of truth — that remove sentences
containing evidence the model could not have seen:
  * numbers that don't occur in the source passages,
  * page references outside the allowed pages,
  * "Section N.M" references to sections not supplied,
  * quotations (4+ words) that aren't verbatim in the source.
"""

from __future__ import annotations

import re

from ..text_utils import normalize_ws

NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
PAGE_RE = re.compile(r"\b(?:pages?|pp?\.)\s*(\d+)(?:\s*[–-]\s*(\d+))?", re.I)
SECTION_RE = re.compile(r"\bsections?\s+(\d+(?:\.\d+)*)", re.I)
QUOTE_RE = re.compile(r"[“\"]([^”\"]{12,})[”\"]")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(\[])")
MD_RE = re.compile(r"(\*\*|__|`|^#+\s*)", re.M)

# Small numbers are used in ordinary prose ("two approaches", "3 sections"); don't police them.
TRIVIAL_NUMBERS = {str(i) for i in range(0, 11)}


class Source:
    def __init__(self, texts: list[str], pages: set[int], section_numbers: set[str] | None = None):
        joined = normalize_ws(" ".join(texts))
        self.text = joined.lower()
        self.numbers = {_norm_num(n) for n in NUM_RE.findall(joined)}
        self.pages = pages
        self.section_numbers = section_numbers or set()


def _norm_num(n: str) -> str:
    return n.replace(",", "").rstrip("%").rstrip(".")


def sentence_ok(sentence: str, src: Source) -> bool:
    for n in NUM_RE.findall(sentence):
        v = _norm_num(n)
        if v in TRIVIAL_NUMBERS:
            continue
        if v not in src.numbers:
            return False
    for m in PAGE_RE.finditer(sentence):
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if not all(p in src.pages for p in range(a, b + 1) if b - a < 50):
            return False
    for m in SECTION_RE.finditer(sentence):
        if m.group(1) not in src.section_numbers:
            return False
    for m in QUOTE_RE.finditer(sentence):
        q = normalize_ws(m.group(1)).lower()
        if len(q.split()) >= 4 and q not in src.text:
            return False
    return True


def clean_text(text: object, src: Source, max_chars: int = 600) -> str:
    """Drop unsupported sentences; strip markdown; cap length."""
    if not isinstance(text, str):
        return ""
    text = MD_RE.sub("", normalize_ws(text))
    kept = [s for s in SENT_SPLIT.split(text) if s.strip() and sentence_ok(s, src)]
    out = " ".join(kept).strip()
    if len(out) > max_chars:
        cut = out[:max_chars]
        out = cut[: cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "…"
    return out


def clean_list(items: object, src: Source, max_items: int = 4, max_chars: int = 260) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        t = clean_text(it, src, max_chars)
        t = t.lstrip("•-–* ").strip()
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
        if len(out) >= max_items:
            break
    return out


def section_numbers(titles: list[str]) -> set[str]:
    nums = set()
    for t in titles:
        m = re.match(r"\s*(?:appendix\s+)?([A-Z]?\d+(?:\.\d+)*|[A-Z])\b", t, re.I)
        if m:
            nums.add(m.group(1).rstrip("."))
    return nums
