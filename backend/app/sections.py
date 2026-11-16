"""Best-effort section reconstruction and overlapping chunking with exact page mapping."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from .config import CHUNK_OVERLAP, CHUNK_WORDS, SPLIT_THRESHOLD_WORDS
from .pdf_extract import Extracted, Line

NUMBERED_RE = re.compile(
    r"^\s*(?:(?P<chap>chapter|part|section)\s+(?P<cn>[0-9ivxlc]+)\b"
    r"|(?P<app>appendix|annex)\s+(?P<an>[a-z0-9]+)\b"
    r"|(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})\.?(?=\s+\S)"
    r"|(?P<alpha>[A-Z](?:\.\d{1,2}){1,3})\.?(?=\s+\S)"
    r"|(?P<roman>[IVX]{1,5})\.(?=\s+\S))",
    re.I,
)
BOILERPLATE_RE = re.compile(
    r"^\s*(table of contents|contents|references|bibliography|works cited|index|"
    r"acknowledg(e)?ments?|copyright|about the authors?|list of (figures|tables)|"
    r"notes|endnotes|disclaimer)\s*$",
    re.I,
)
DOT_LEADER_RE = re.compile(r"(\.\s*){4,}\s*\d+\s*$|\s\d{1,4}\s*$")


@dataclass
class Section:
    id: str
    title: str
    level: int
    path: list[str]
    text: str
    page_offsets: list[int]  # sorted char offsets where a page segment starts
    page_numbers: list[int]  # page number of each segment
    kind_marks: list[tuple[int, str]]  # (offset, kind) for tables/code/figures
    heading_page: int
    boilerplate: bool = False

    def page_at(self, offset: int) -> int:
        i = bisect.bisect_right(self.page_offsets, offset) - 1
        return self.page_numbers[max(0, i)]

    @property
    def page_start(self) -> int:
        return self.page_numbers[0] if self.page_numbers else self.heading_page

    @property
    def page_end(self) -> int:
        return self.page_numbers[-1] if self.page_numbers else self.heading_page

    def kinds_between(self, start: int, end: int) -> set[str]:
        return {k for off, k in self.kind_marks if start <= off <= end}

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class Chunk:
    id: int
    section: Section
    start: int
    end: int
    text: str = field(repr=False)
    content_types: set[str] = field(default_factory=set)

    @property
    def page_start(self) -> int:
        return self.section.page_at(self.start)

    @property
    def page_end(self) -> int:
        return self.section.page_at(max(self.start, self.end - 1))


@dataclass
class Structure:
    sections: list[Section]
    source: str  # outline | headings | pages
    notes: list[str]


# --------------------------------------------------------------------------- headings


def _norm_title(text: str) -> str:
    t = text.lower()
    t = NUMBERED_RE.sub("", t, count=1)
    return re.sub(r"[^a-z0-9]", "", t)


def _cap_ratio(text: str) -> float:
    ws = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']*", text) if len(w) > 3]
    if not ws:
        return 1.0
    return sum(1 for w in ws if w[0].isupper()) / len(ws)


def _numbered_level(text: str) -> int | None:
    m = NUMBERED_RE.match(text)
    if not m:
        return None
    if m.group("chap") or m.group("app"):
        return 1
    if m.group("num"):
        return min(3, m.group("num").count(".") + 1)
    if m.group("alpha"):
        return min(3, m.group("alpha").count(".") + 1)
    if m.group("roman"):
        return 1
    return None


def detect_headings(lines: list[Line], body_size: float) -> list[tuple[int, int, int, str]]:
    """Return (line_index, n_lines_consumed, level, title) for likely headings."""
    found: list[tuple[int, int, int, str, float]] = []
    i = 0
    n = len(lines)
    while i < n:
        l = lines[i]
        t = l.text.strip()
        if l.kind is not None or not _heading_shape(t):
            i += 1
            continue
        ratio = l.size / body_size if body_size else 1
        numbered = _numbered_level(t)
        bigger = ratio >= 1.12
        prev = lines[i - 1] if i > 0 else None
        nxt = lines[i + 1] if i + 1 < n else None
        wc = len(t.split())

        # Bold/large phrase that wraps into a regular paragraph line is emphasis, not a heading.
        continues_para = (
            nxt is not None and nxt.page == l.page and nxt.block == l.block
            and not nxt.bold and abs(nxt.size - l.size) < 0.6
            and nxt.text.strip()[:1].islower()
        )
        if continues_para:
            i += 1
            continue

        is_heading = False
        if bigger and (l.bold or wc <= 12) and ratio < 4:
            is_heading = True
        elif l.bold and numbered is not None:
            is_heading = True
        elif l.bold and wc <= 10 and _cap_ratio(t) >= 0.5:
            starts_block = prev is None or prev.block != l.block or prev.page != l.page
            is_heading = starts_block or (prev is not None and prev.text.rstrip().endswith((".", ":")))

        if not is_heading:
            i += 1
            continue

        # Merge a wrapped multi-line heading with identical styling.
        consumed, title = 1, t
        while (
            i + consumed < n and consumed < 3
            and lines[i + consumed].page == l.page
            and lines[i + consumed].kind is None
            and abs(lines[i + consumed].size - l.size) < 0.3
            and lines[i + consumed].bold == l.bold
            and (l.bold or bigger)
            and lines[i + consumed].bbox[1] - lines[i + consumed - 1].bbox[3] < l.size * 0.9
            and len((title + " " + lines[i + consumed].text).split()) <= 18
            and _numbered_level(lines[i + consumed].text.strip()) is None
        ):
            title += " " + lines[i + consumed].text.strip()
            consumed += 1

        found.append((i, consumed, numbered or 0, title, ratio))
        i += consumed

    if not found:
        return []

    # Levels for un-numbered headings come from size tiers.
    ratios = sorted({round(r, 1) for *_, r in found}, reverse=True)
    out = []
    for idx, consumed, num_level, title, r in found:
        if num_level:
            level = num_level
        else:
            tier = ratios.index(round(r, 1))
            level = min(3, tier + 1)
        out.append((idx, consumed, level, title))

    # Guard: heuristics went wild (e.g. slide decks, forms). Keep only the strongest signals.
    body_lines = max(1, sum(1 for l in lines if l.kind is None) - len(out))
    if len(out) > 0.3 * body_lines:
        strong = [h for h in out if _numbered_level(h[3]) or lines[h[0]].size / body_size >= 1.25]
        out = strong if len(strong) <= 0.3 * body_lines else []
    return out


def _heading_shape(t: str) -> bool:
    if not t or len(t) > 120 or len(t.split()) > 16:
        return False
    if t.endswith((":", ",", ";")):
        return False
    if t.endswith(".") and len(t.split()) > 3 and not NUMBERED_RE.match(t):
        return False
    letters = sum(c.isalpha() for c in t)
    if letters < 2 or letters / max(1, len(t.replace(" ", ""))) < 0.5:
        return False
    first_alpha = next((c for c in t if c.isalpha()), "")
    if first_alpha.islower() and not NUMBERED_RE.match(t):
        return False
    if DOT_LEADER_RE.search(t) and re.search(r"(\.\s*){4,}", t):
        return False  # table-of-contents entry
    return True


# --------------------------------------------------------------------------- outline


def match_outline(lines: list[Line], outline: list[tuple[int, str, int]]) -> list[tuple[int, int, int, str]]:
    """Map PDF bookmarks to the lines where those headings appear."""
    by_page: dict[int, list[int]] = {}
    for i, l in enumerate(lines):
        by_page.setdefault(l.page, []).append(i)

    out: list[tuple[int, int, int, str]] = []
    last_idx = -1
    min_level = min((lvl for lvl, *_ in outline), default=1)
    for lvl, title, page in outline:
        if page < 1 or not title:
            continue
        target = _norm_title(title)
        if not target:
            continue
        level = min(3, lvl - min_level + 1)
        hit = None
        for p in (page, page + 1, page - 1):
            cands: list[tuple[tuple, int, int]] = []
            for i in by_page.get(p, []):
                if i <= last_idx or lines[i].kind is not None:
                    continue
                cand = _norm_title(lines[i].text)
                if not cand:
                    continue
                consumed = 0
                if cand == target:
                    consumed = 1
                elif target.startswith(cand) and len(cand) >= 4 and i + 1 < len(lines):
                    if _norm_title(lines[i].text + " " + lines[i + 1].text) == target:
                        consumed = 2
                if consumed:
                    l = lines[i]
                    # Prefer the most heading-like occurrence (figure labels can repeat a title).
                    rank = (_numbered_level(l.text.strip()) is not None, l.bold, l.size, -i)
                    cands.append((rank, i, consumed))
            if cands:
                _, i, consumed = max(cands)
                hit = (i, consumed)
                break
        if hit is None:
            # Fall back to the top of the bookmarked page.
            first = [i for i in by_page.get(page, []) if i > last_idx]
            if not first:
                continue
            hit = (first[0], 0)
        out.append((hit[0], hit[1], level, title.strip()))
        last_idx = hit[0] + max(0, hit[1] - 1)
    return out


# --------------------------------------------------------------------------- assembly


def build_structure(ex: Extracted) -> Structure:
    lines = ex.lines
    notes: list[str] = []
    source = "headings"
    headings: list[tuple[int, int, int, str]] = []

    if len(ex.outline) >= 3:
        headings = match_outline(lines, ex.outline)
        if len(headings) >= 3:
            source = "outline"
            # Headings in the front matter before the first bookmark (e.g. title, Abstract).
            first = headings[0][0]
            if first > 0:
                front = detect_headings(lines[:first], ex.body_size)
                headings = [(i, c, 1, t) for i, c, _, t in front] + headings
            # Bookmarks often omit References/Acknowledgments; add them so they can be down-weighted.
            known = {h[0] for h in headings}
            extra = [
                (i, c, 1, t) for i, c, _, t in detect_headings(lines, ex.body_size)
                if BOILERPLATE_RE.match(NUMBERED_RE.sub("", t, count=1)) and i not in known
            ]
            headings = sorted(headings + extra)
        else:
            headings = []

    if not headings:
        headings = detect_headings(lines, ex.body_size)
        source = "headings"

    if len(headings) < 2:
        notes.append("No clear headings were detected, so the document was grouped by page.")
        return Structure(_page_sections(lines), "pages", notes)

    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    bounds = headings + [(len(lines), 0, 0, "")]

    if headings[0][0] > 0:
        sec = _make_section("s0", "Opening pages", 1, ["Opening pages"], lines[: headings[0][0]], lines[0].page)
        if sec:
            sections.append(sec)

    for k, (idx, consumed, level, title) in enumerate(headings):
        nxt = bounds[k + 1][0]
        if BOILERPLATE_RE.match(NUMBERED_RE.sub("", title, count=1)):
            level = 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = [t for _, t in stack]
        body = lines[idx + consumed : nxt]
        heading_page = lines[idx].page if idx < len(lines) else lines[-1].page
        sec = _make_section(f"s{k + 1}", title, level, path, body, heading_page)
        if sec:
            sections.append(sec)

    if not sections:
        return Structure(_page_sections(lines), "pages", ["Section text could not be reconstructed; grouped by page."])
    if source == "headings":
        notes.append("Sections were reconstructed from typography (font size, weight, numbering) and are approximate.")
    return Structure(sections, source, notes)


def _page_sections(lines: list[Line]) -> list[Section]:
    out = []
    pages: dict[int, list[Line]] = {}
    for l in lines:
        pages.setdefault(l.page, []).append(l)
    for p, ls in sorted(pages.items()):
        sec = _make_section(f"p{p}", f"Page {p}", 1, [f"Page {p}"], ls, p)
        if sec:
            out.append(sec)
    return out


def _make_section(sid: str, title: str, level: int, path: list[str], body: list[Line], heading_page: int) -> Section | None:
    parts: list[str] = []
    offsets: list[int] = []
    pages: list[int] = []
    kinds: list[tuple[int, str]] = []
    pos = 0
    prev: Line | None = None

    for l in body:
        if l.kind in ("image", "figure_label"):
            if not kinds or kinds[-1] != (pos, "figure"):
                kinds.append((pos, "figure"))
            continue
        text = l.text.strip()
        if not text:
            continue
        if prev is None:
            sep = ""
        elif l.page != prev.page:
            sep = " " if not prev.text.rstrip().endswith((".", "!", "?", ":")) else "\n\n"
        elif l.block != prev.block:
            sep = "\n\n"
        elif l.kind in ("table", "code") or prev.kind in ("table", "code"):
            sep = "\n"
        elif prev.text.rstrip().endswith("-") and text[:1].isalpha():
            sep = ""
        else:
            sep = " "
        parts.append(sep)
        pos += len(sep)
        if not pages or pages[-1] != l.page:
            offsets.append(pos)
            pages.append(l.page)
        if l.kind:
            kinds.append((pos, {"table": "table", "caption_table": "table", "code": "code",
                                "caption_figure": "figure"}[l.kind]))
        parts.append(text)
        pos += len(text)
        prev = l

    text = "".join(parts)
    if not text.strip() and not kinds:
        return None
    if not offsets:
        offsets, pages = [0], [heading_page]
    boiler = bool(BOILERPLATE_RE.match(title)) or _looks_like_toc(text)
    return Section(sid, title, level, path, text, offsets, pages, kinds, heading_page, boiler)


def _looks_like_toc(text: str) -> bool:
    rows = [r for r in text.split("\n") if r.strip()]
    if len(rows) < 6:
        rows = re.split(r"(?<=\d)\s+(?=[A-Z0-9])", text)
    if len(rows) < 6:
        return False
    leaders = sum(1 for r in rows if re.search(r"(\.\s*){4,}\s*\d+\s*$", r))
    return leaders / len(rows) >= 0.3


# --------------------------------------------------------------------------- chunking


def chunk_sections(sections: list[Section]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for sec in sections:
        word_spans = [m.span() for m in re.finditer(r"\S+", sec.text)]
        if len(word_spans) < 12:
            continue  # container heading / author line with almost no body text
        if len(word_spans) <= SPLIT_THRESHOLD_WORDS:
            windows = [(0, len(word_spans))]
        else:
            step = CHUNK_WORDS - CHUNK_OVERLAP
            windows = []
            for s in range(0, len(word_spans), step):
                e = min(len(word_spans), s + CHUNK_WORDS)
                windows.append((s, e))
                if e == len(word_spans):
                    break
            # Fold a tiny tail into the previous window.
            if len(windows) > 1 and windows[-1][1] - windows[-1][0] < CHUNK_OVERLAP * 1.5:
                windows[-2] = (windows[-2][0], windows[-1][1])
                windows.pop()
        for ws, we in windows:
            if not word_spans:
                start, end = 0, 0
            else:
                start, end = word_spans[ws][0], word_spans[we - 1][1]
            c = Chunk(len(chunks), sec, start, end, sec.text[start:end])
            c.content_types = sec.kinds_between(start, end)
            if len(c.text.split()) >= 40 and _prose_like(c.text):
                c.content_types.add("prose")
            chunks.append(c)
    return chunks


def _prose_like(text: str) -> bool:
    sentences = re.findall(r"[a-z][^.!?]{20,}[.!?]", text)
    return len(sentences) >= 2
