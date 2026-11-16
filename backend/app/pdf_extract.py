"""PDF validation and page-aware line extraction with PyMuPDF."""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf

from . import errors
from .config import MAX_PAGES, TABLE_DETECTION_BUDGET_S

log = logging.getLogger("intellidoc.extract")

MONO_RE = re.compile(r"mono|courier|consol|menlo|code|inconsolata|fira ?code|lucida ?console", re.I)
BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi|medi(?:um)?\b|-medi|\.b$|,bold", re.I)
TABLE_CAPTION_RE = re.compile(r"^\s*(table|tab\.)\s*[0-9ivx]+[a-z]?\s*[:.\-–—]?", re.I)
FIGURE_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|exhibit|chart|diagram)\s*[0-9ivx]+[a-z]?\s*[:.\-–—]?", re.I)

TEXT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE
    | pymupdf.TEXT_PRESERVE_LIGATURES
    | pymupdf.TEXT_MEDIABOX_CLIP
)


@dataclass
class Line:
    page: int  # 1-indexed
    text: str
    size: float
    bold_frac: float
    mono_frac: float
    bbox: tuple[float, float, float, float]
    block: int
    kind: str | None = None  # table | code | caption_table | caption_figure | figure_label | image

    @property
    def bold(self) -> bool:
        return self.bold_frac >= 0.85


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    char_count: int
    image_coverage: float
    status: str  # text | scanned | blank


@dataclass
class Extracted:
    page_count: int
    pages: list[PageInfo]
    lines: list[Line]
    body_size: float
    outline: list[tuple[int, str, int]]
    title: str | None
    warnings: list[dict] = field(default_factory=list)

    @property
    def scanned_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.status == "scanned"]

    @property
    def pages_with_text(self) -> int:
        return sum(1 for p in self.pages if p.status == "text")


def open_pdf(data: bytes) -> pymupdf.Document:
    """Validate bytes and open the document, raising friendly AnalysisErrors."""
    head = data[:1024]
    if b"%PDF-" not in head:
        raise errors.not_pdf()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — MuPDF raises several types
        log.warning("Failed to open PDF: %s", exc)
        raise errors.malformed() from exc
    if doc.needs_pass:
        doc.close()
        raise errors.encrypted()
    if doc.page_count == 0:
        doc.close()
        raise errors.malformed()
    if doc.page_count > MAX_PAGES:
        count = doc.page_count
        doc.close()
        raise errors.too_many_pages(MAX_PAGES, count)
    return doc


def _norm_margin(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def extract(doc: pymupdf.Document) -> Extracted:
    raw: list[Line] = []
    pages: list[PageInfo] = []
    size_chars: Counter[float] = Counter()
    table_time = 0.0
    table_budget_hit = False

    for pno in range(doc.page_count):
        page = doc[pno]
        number = pno + 1
        rect = page.rect
        width, height = rect.width or 1, rect.height or 1

        try:
            d = page.get_text("dict", flags=TEXT_FLAGS)
        except Exception as exc:  # noqa: BLE001
            log.warning("Text extraction failed on page %s: %s", number, exc)
            d = {"blocks": []}

        page_lines: list[Line] = []
        for bi, block in enumerate(d.get("blocks", [])):
            if block.get("type", 0) != 0:
                continue
            for ln in block.get("lines", []):
                dx, dy = ln.get("dir", (1, 0))
                if abs(dy) > 0.1 or dx < 0:  # rotated / vertical text (e.g. arXiv side stamp)
                    continue
                spans = [s for s in ln.get("spans", []) if s.get("text")]
                text = "".join(s["text"] for s in spans)
                if not text.strip():
                    continue
                total = sum(len(s["text"].strip()) for s in spans) or 1
                bold = sum(
                    len(s["text"].strip())
                    for s in spans
                    if (s.get("flags", 0) & 16) or BOLD_RE.search(s.get("font", ""))
                )
                mono = sum(
                    len(s["text"].strip())
                    for s in spans
                    if (s.get("flags", 0) & 8) or MONO_RE.search(s.get("font", ""))
                )
                # Dominant size by characters
                sz: Counter[float] = Counter()
                for s in spans:
                    sz[round(s.get("size", 0) * 2) / 2] += len(s["text"].strip())
                size = sz.most_common(1)[0][0] if sz else 0
                page_lines.append(
                    Line(number, text, size, bold / total, mono / total, tuple(ln["bbox"]), bi)
                )

        page_lines = _merge_same_baseline(page_lines)

        # Images (no pixel data loaded)
        img_area = 0.0
        images: list[tuple[float, float, float, float]] = []
        try:
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                a = max(0.0, (x1 - x0)) * max(0.0, (y1 - y0))
                if a / (width * height) >= 0.02:
                    images.append((x0, y0, x1, y1))
                img_area += a
        except Exception:  # noqa: BLE001
            pass
        coverage = min(1.0, img_area / (width * height))

        chars = sum(len(l.text.strip()) for l in page_lines)
        if chars < 25:
            status = "scanned" if coverage >= 0.4 else "blank"
        else:
            status = "text"

        # Tables (best effort, time-boxed)
        table_boxes: list[tuple[float, float, float, float]] = []
        if status == "text" and not table_budget_hit:
            t0 = time.perf_counter()
            try:
                for t in page.find_tables().tables:
                    if t.row_count >= 2 and t.col_count >= 2:
                        table_boxes.append(tuple(t.bbox))
            except Exception:  # noqa: BLE001
                pass
            table_time += time.perf_counter() - t0
            if table_time > TABLE_DETECTION_BUDGET_S:
                table_budget_hit = True

        # Figure regions: raster images plus large clusters of vector drawings.
        figure_boxes = list(images)
        if status == "text":
            try:
                for r in page.cluster_drawings():
                    if r.width * r.height / (width * height) >= 0.03:
                        figure_boxes.append((r.x0, r.y0, r.x1, r.y1))
            except Exception:  # noqa: BLE001
                pass

        def inside(cx: float, cy: float, boxes, m: float = 1) -> bool:
            return any(b[0] - m <= cx <= b[2] + m and b[1] - m <= cy <= b[3] + m for b in boxes)

        block_max_words: dict[int, int] = defaultdict(int)
        for l in page_lines:
            block_max_words[l.block] = max(block_max_words[l.block], len(l.text.split()))

        for l in page_lines:
            cx, cy = (l.bbox[0] + l.bbox[2]) / 2, (l.bbox[1] + l.bbox[3]) / 2
            if inside(cx, cy, table_boxes):
                l.kind = "table"
            elif (inside(cx, cy, figure_boxes, m=16) and block_max_words[l.block] <= 8
                  and not TABLE_CAPTION_RE.match(l.text) and not FIGURE_CAPTION_RE.match(l.text)):
                l.kind = "figure_label"  # text drawn inside a diagram, not prose
            elif TABLE_CAPTION_RE.match(l.text):
                l.kind = "caption_table"
            elif FIGURE_CAPTION_RE.match(l.text):
                l.kind = "caption_figure"
            elif l.mono_frac >= 0.6:
                l.kind = "code"
            size_chars[l.size] += len(l.text.strip())

        # Image placeholders keep figures inside the reading order.
        if images:
            page_lines = _place_images(
                page_lines + [Line(number, "", 0, 0, 0, box, -1, kind="image") for box in images]
            )

        raw.extend(page_lines)
        pages.append(PageInfo(number, width, height, chars, coverage, status))

    lines = _strip_headers_footers(raw, pages)
    body_size = size_chars.most_common(1)[0][0] if size_chars else 10.0

    try:
        outline = [(int(l), str(t).strip(), int(p)) for l, t, p, *_ in doc.get_toc(simple=True)]
    except Exception:  # noqa: BLE001
        outline = []
    title = (doc.metadata or {}).get("title") or None

    ex = Extracted(doc.page_count, pages, lines, body_size, outline, title)
    if table_budget_hit:
        ex.warnings.append({
            "code": "table_detection_partial",
            "message": "Table detection was time-limited on this long document; some tables may not be tagged.",
        })
    return ex


def _merge_same_baseline(lines: list[Line]) -> list[Line]:
    """Join fragments that sit on the same baseline (e.g. '3.1' + 'Encoder and Decoder Stacks')."""
    out: list[Line] = []
    for l in lines:
        if out:
            p = out[-1]
            same_row = abs((p.bbox[1] + p.bbox[3]) / 2 - (l.bbox[1] + l.bbox[3]) / 2) < 2.0
            if same_row and 0 <= l.bbox[0] - p.bbox[2] < 40:
                n_p, n_l = len(p.text.strip()) or 1, len(l.text.strip()) or 1
                tot = n_p + n_l
                sep = "" if p.text.endswith(" ") or l.text.startswith(" ") else " "
                out[-1] = Line(
                    p.page,
                    p.text + sep + l.text,
                    p.size if n_p >= n_l else l.size,
                    (p.bold_frac * n_p + l.bold_frac * n_l) / tot,
                    (p.mono_frac * n_p + l.mono_frac * n_l) / tot,
                    (p.bbox[0], min(p.bbox[1], l.bbox[1]), l.bbox[2], max(p.bbox[3], l.bbox[3])),
                    p.block,
                )
                continue
        out.append(l)
    return out


def _place_images(lines: list[Line]) -> list[Line]:
    """Insert image placeholders before the first text line below them."""
    text = [l for l in lines if l.kind != "image"]
    imgs = sorted((l for l in lines if l.kind == "image"), key=lambda l: l.bbox[1])
    out: list[Line] = []
    for l in text:
        while imgs and imgs[0].bbox[3] <= l.bbox[1] + 1:
            out.append(imgs.pop(0))
        out.append(l)
    out.extend(imgs)
    return out


def _strip_headers_footers(lines: list[Line], pages: list[PageInfo]) -> list[Line]:
    """Drop running headers/footers and bare page numbers in the page margins."""
    heights = {p.number: p.height for p in pages}
    text_pages = max(1, sum(1 for p in pages if p.status == "text"))
    margin_hits: dict[str, set[int]] = defaultdict(set)

    def in_margin(l: Line) -> bool:
        h = heights[l.page]
        return l.bbox[3] <= h * 0.09 or l.bbox[1] >= h * 0.91

    for l in lines:
        if l.kind != "image" and in_margin(l):
            margin_hits[_norm_margin(l.text)].add(l.page)

    threshold = max(2, int(text_pages * 0.3))
    repeated = {k for k, v in margin_hits.items() if len(v) >= threshold}
    page_num_re = re.compile(r"^\s*(page\s*)?[\divxlc#]+(\s*(of|/)\s*\d+)?\s*$", re.I)

    out = []
    for l in lines:
        if l.kind != "image" and in_margin(l):
            if _norm_margin(l.text) in repeated or page_num_re.match(l.text):
                continue
        out.append(l)
    return out
