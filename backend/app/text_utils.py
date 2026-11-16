"""Small, dependency-free text helpers: tokenizing, light stemming, sentence spans."""

from __future__ import annotations

import re
from functools import lru_cache

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# Words that describe the *request* rather than the content being sought.
INTENT_WORDS = {
    "find", "finding", "look", "looking", "want", "need", "needs", "understand",
    "understanding", "learn", "learning", "know", "information", "info", "details",
    "detail", "section", "sections", "part", "parts", "document", "doc", "pdf", "page",
    "pages", "read", "reading", "tell", "explain", "explained", "explanation", "show",
    "help", "relevant", "related", "regarding", "about", "related", "anything", "everything",
    "thing", "things", "stuff", "way", "ways", "use", "using", "used", "get", "make", "like",
    "just", "also", "really", "specifically", "especially", "particular", "particularly",
    "trying", "try", "able", "good", "best", "important", "key", "main", "overall",
    "summary", "summarize", "summarise", "quick", "quickly", "i", "im", "id", "ive",
    "did", "does", "do", "doing", "done", "can", "could", "would", "should", "will", "may",
    "might", "take", "took", "takes", "much", "many", "kind", "sort", "give", "gives", "provide",
    "provides", "describe", "described", "describes", "discuss", "discussed", "discusses",
    "mention", "mentioned", "mentions", "list", "whats", "hows", "whys", "explains", "covers",
    "cover", "talk", "talks", "say", "says", "said", "doc's",
}

STOP_WORDS = frozenset(ENGLISH_STOP_WORDS)
QUERY_STOP_WORDS = frozenset(ENGLISH_STOP_WORDS | INTENT_WORDS)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-']*[A-Za-z0-9]|[A-Za-z]")
WS_RE = re.compile(r"\s+")

_SUFFIXES = (
    ("izations", "ize"), ("ization", "ize"), ("isations", "ize"), ("isation", "ize"),
    ("ational", "ate"), ("ations", "ate"), ("ation", "ate"), ("ments", ""), ("ment", ""),
    ("nesses", ""), ("ness", ""), ("ities", ""), ("ity", ""), ("ings", ""), ("ing", ""),
    ("ies", "y"), ("ied", "y"), ("ives", "ive"), ("ers", ""), ("er", ""), ("ed", ""),
    ("ally", "al"), ("ly", ""), ("es", ""), ("s", ""),
)


@lru_cache(maxsize=50_000)
def stem(word: str) -> str:
    """A deliberately light stemmer: merges common inflections, never below 3 chars."""
    w = word.lower().strip("'-")
    if w.endswith("'s"):
        w = w[:-2]
    if len(w) <= 3:
        return w
    for suffix, repl in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) + len(repl) >= 3:
            if suffix == "s" and (w.endswith("ss") or w.endswith("us") or w.endswith("is")):
                continue
            if suffix == "es" and not re.search(r"(ch|sh|x|ss|zz)es$", w):
                continue
            w = w[: len(w) - len(suffix)] + repl
            break
    if w.endswith("y") and len(w) > 3:
        w = w[:-1] + "i"
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def words(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def content_stems(text: str, stop: frozenset[str] = STOP_WORDS) -> list[str]:
    """Lower-cased, stop-word filtered, stemmed tokens."""
    out = []
    for tok in words(text):
        low = tok.lower()
        if low in stop or len(low) < 2:
            continue
        out.append(stem(low))
    return out


def analyzer(text: str) -> list[str]:
    """TF-IDF analyzer: stems + adjacent-stem bigrams."""
    toks = content_stems(text)
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


def normalize_ws(text: str) -> str:
    # U+FFFD marks glyphs the PDF couldn't map to text (often math symbols); drop it.
    return WS_RE.sub(" ", text.replace("\ufffd", "")).strip()


_SENT_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9\"'(\[•\-–])|\n\n+")
_ABBREV = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|Fig|Figs|Eq|Eqs|No|Sec|Ref|al|approx|cf|Dr|Mr|Ms|Mrs|St|Inc|Ltd|Co)\.)$", re.I)


def sentence_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Return (start, end) character spans of sentences inside text[start:end]."""
    end = len(text) if end is None else end
    spans: list[tuple[int, int]] = []
    cursor = start
    for m in _SENT_END.finditer(text, start, end):
        candidate = text[cursor:m.start()].rstrip()
        if _ABBREV.search(candidate) and "\n\n" not in m.group(0):
            continue  # "e.g. Foo" — not a sentence boundary
        s, e = _trim(text, cursor, m.start())
        if e > s:
            spans.append((s, e))
        cursor = m.end()
    s, e = _trim(text, cursor, end)
    if e > s:
        spans.append((s, e))
    return spans


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e
