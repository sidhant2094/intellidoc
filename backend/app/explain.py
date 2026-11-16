"""Turn ranked passages into user-facing, source-grounded result payloads.

Everything here is deterministic and extractive: excerpts and key points are verbatim
sentences from the PDF; explanations are templates filled with measured facts.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np
import pymupdf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .ranking import Query, Ranked, relevance_label
from .pdf_extract import FIGURE_CAPTION_RE, TABLE_CAPTION_RE
from .sections import Section
from .text_utils import STOP_WORDS, analyzer, content_stems, normalize_ws, sentence_spans, stem, words

CONTEXT_CHARS = 5000
BULLET_RE = re.compile(r"^(?:[•▪◦●·\-–*]|o(?=\s))\s*")
TYPE_LABEL = {"table": "a table", "code": "code", "figure": "a figure"}
INTENT_REASON = {
    "table": "you're looking for data or comparisons",
    "code": "you're looking for implementation detail",
    "figure": "you asked about diagrams or visuals",
}


def build_results(ranked: list[Ranked], q: Query, doc: pymupdf.Document, vectorizer_docs: list[str]) -> list[dict]:
    # A small vectorizer over the result passages scores sentences against the query.
    passages = [r.section.text[r.start:r.end] for r in ranked]
    vec = TfidfVectorizer(analyzer=analyzer, sublinear_tf=True)
    vec.fit(passages + vectorizer_docs[:400])
    qv = vec.transform([q.objective + " " + " ".join(q.focus_terms * 2)])

    results = []
    for rank_i, r in enumerate(ranked, start=1):
        sec = r.section
        start, end = _expand_to_sentences(sec.text, r.start, r.end)
        spans = [s for s in sentence_spans(sec.text, start, end) if len(sec.text[s[0]:s[1]].split()) >= 3]
        if not spans:
            spans = [(start, end)]
        sent_texts = [normalize_ws(sec.text[a:b]) for a, b in spans]
        S = vec.transform(sent_texts)
        q_sim = linear_kernel(qv, S).ravel()
        kw_sim = np.array([_key_hits(t, q) for t in sent_texts])
        sent_score = 0.55 * q_sim + 0.45 * kw_sim
        # Captions read poorly as evidence unless the user asked for figures/tables.
        blocked = set()
        for k, t in enumerate(sent_texts):
            cap = "figure" if FIGURE_CAPTION_RE.match(t) else "table" if TABLE_CAPTION_RE.match(t) else None
            if cap and cap not in q.intents:
                blocked.add(k)

        ex_lo, ex_hi = _best_window(spans, sent_texts, sent_score, blocked)
        ex_start, ex_end = spans[ex_lo][0], spans[ex_hi][1]
        excerpt = normalize_ws(sec.text[ex_start:ex_end])
        if len(excerpt) > 650:
            excerpt = _clip_words(excerpt, 95)
            ex_end = ex_start + _raw_len_for(sec.text, ex_start, excerpt)

        key_points = _key_points(spans, sent_texts, sent_score, S, set(range(ex_lo, ex_hi + 1)), sec)
        best = r.chunks[0]
        page_start = sec.page_at(start)
        page_end = sec.page_at(max(start, end - 1))
        if start == 0:
            page_start = min(page_start, sec.heading_page)

        content_types = sorted(set().union(*(c.chunk.content_types for c in r.chunks)) or {"prose"},
                               key=["prose", "table", "code", "figure"].index)

        context, ctx_ex, ctx_pages = _context(sec, ex_start, ex_end)
        excerpt_page = sec.page_at(ex_start)
        results.append({
            "id": f"result-{rank_i}",
            "rank": rank_i,
            "section_id": sec.id,
            "title": sec.title,
            "breadcrumb": sec.path,
            "level": sec.level,
            "page_start": page_start,
            "page_end": page_end,
            "match_score": round(r.score, 3),
            "relevance_label": relevance_label(r.score),
            "why_relevant": _why(r, q, rank_i, content_types),
            "matched_terms": [q.surface.get(s, s) for s in best.matched],
            "summary": "",  # written only when a grounded summary is generated
            "findings": [],
            "takeaways": [],
            "limitations": [],
            "key_points": key_points,
            "excerpt": excerpt,
            "excerpt_page": excerpt_page,
            "highlights": _highlights(doc, sec, ex_start, ex_end),
            "content_types": content_types,
            "context": context,
            "context_excerpt": ctx_ex,
            "context_pages": ctx_pages,
            "signals": {k: round(best.signals.get(k, 0.0), 3) for k in
                        ("semantic", "keyword", "content_type", "expertise", "structure", "contextual")},
        })
    return results


# --------------------------------------------------------------------------- excerpt & summary


def _expand_to_sentences(text: str, start: int, end: int) -> tuple[int, int]:
    s = start
    while s > 0 and s > start - 300 and not re.match(r"[.!?\n]", text[s - 1]):
        s -= 1
    e = end
    while e < len(text) and e < end + 300 and text[e - 1] not in ".!?":
        e += 1
    return s, e


def _key_hits(sentence: str, q: Query) -> float:
    if not q.key_terms:
        return 0.0
    st = set(content_stems(sentence))
    total = sum(q.key_terms.values())
    return sum(w for s, w in q.key_terms.items() if s in st) / total


def _best_window(spans, texts, scores, blocked: set[int] = frozenset()) -> tuple[int, int]:
    best, best_val = (0, 0), -1.0
    if len(blocked) >= len(spans):
        blocked = set()
    for i in range(len(spans)):
        for j in range(i, min(len(spans), i + 3)):
            if blocked & set(range(i, j + 1)):
                break
            wc = sum(len(texts[k].split()) for k in range(i, j + 1))
            if wc > 90 and j > i:
                break
            val = float(sum(scores[i:j + 1]))
            # Prefer windows that read as a coherent passage (roughly 20–70 words).
            if wc < 15:
                val *= 0.7
            val /= 1 + 0.15 * (j - i)
            if val > best_val:
                best, best_val = (i, j), val
    return best


def _key_points(spans, texts, scores, S, exclude: set[int], sec: Section) -> list[dict]:
    centroid = np.asarray(S.mean(axis=0))
    central = linear_kernel(centroid, S).ravel() if S.shape[0] else np.zeros(0)
    cand = []
    for i, t in enumerate(texts):
        wc = len(t.split())
        if i in exclude or wc < 8 or wc > 55:
            continue
        if _is_noise(t):
            continue
        cand.append((0.6 * scores[i] + 0.4 * central[i], i))
    picked = sorted(i for _, i in sorted(cand, reverse=True)[:3])
    return [{"text": BULLET_RE.sub("", texts[i]), "page": sec.page_at(spans[i][0])} for i in picked]


def _is_noise(t: str) -> bool:
    letters = sum(c.isalpha() for c in t)
    return letters / max(1, len(t)) < 0.6


def _clip_words(text: str, n: int) -> str:
    ws = text.split()
    return text if len(ws) <= n else " ".join(ws[:n]) + " …"


def _raw_len_for(raw: str, start: int, clipped: str) -> int:
    target = len(clipped.rstrip(" …").split())
    count, i, n = 0, start, len(raw)
    in_word = False
    while i < n:
        if raw[i].isspace():
            if in_word:
                count += 1
                if count == target:
                    return i - start
            in_word = False
        else:
            in_word = True
        i += 1
    return n - start


# --------------------------------------------------------------------------- explanation


def _why(r: Ranked, q: Query, rank_i: int, content_types: list[str]) -> str:
    best = r.chunks[0]
    parts: list[str] = []
    matched = [q.surface.get(s, s) for s in best.matched]
    title_stems = set(content_stems(r.section.title))
    title_hits = [q.surface.get(s, s) for s in best.matched if s in title_stems]

    if title_hits:
        parts.append(f"The heading itself addresses {_join(title_hits[:3])}")
        rest = [m for m in matched if m not in title_hits]
        if rest:
            parts[-1] += f", and the text also covers {_join(rest[:3])}"
        parts[-1] += "."
    elif matched:
        n_total = len(q.key_terms)
        lead = "Covers" if len(matched) >= max(2, n_total // 2) else "Mentions"
        parts.append(f"{lead} {_join(matched[:4])} from your objective.")
    else:
        parts.append("Uses closely related wording to your objective, though not your exact terms.")

    hits = [t for t in content_types if t in q.intents]
    if hits:
        parts.append(f"Includes {_join([TYPE_LABEL[t] for t in hits])} — useful since {INTENT_REASON[hits[0]]}.")

    level = q.expertise
    c = best.complexity
    if level == "beginner" and c <= 0.4:
        parts.append("Written at a relatively accessible level for this document, a good starting point.")
    elif level == "beginner" and c >= 0.75:
        parts.append("Among the denser passages in this document — you may want to read the surrounding context first.")
    elif level == "advanced" and c >= 0.6:
        parts.append("One of the more technical passages in the document, suited to an advanced reader.")
    elif level == "advanced" and c <= 0.25:
        parts.append("Fairly introductory in tone; skim it for the specifics.")

    lens_only = [s for s in best.lens_hits if s not in q.key_terms]
    if lens_only and q.persona:
        role_terms = sorted({_surface_for_stem(s, r.section.text) for s in lens_only[:3]})
        role_terms = [t for t in role_terms if t]
        if role_terms:
            parts.append(f"Touches on {_join(role_terms)} — relevant from a {q.persona} perspective.")

    if rank_i == 1 and len(parts) < 4:
        parts.append("Strongest overall match in the document.")
    return " ".join(parts)


def _surface_for_stem(s: str, text: str) -> str:
    for w in words(text):
        if stem(w.lower()) == s:
            return w.lower()
    return ""


def _join(items: list[str]) -> str:
    items = [f"“{i}”" if not i.startswith(("a ", "code")) else i for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# --------------------------------------------------------------------------- context & highlights


def _context(sec: Section, ex_start: int, ex_end: int) -> tuple[str, dict, list[dict]]:
    text = sec.text
    if len(text) <= CONTEXT_CHARS:
        lo, hi = 0, len(text)
    else:
        mid = (ex_start + ex_end) // 2
        lo = max(0, mid - CONTEXT_CHARS // 2)
        hi = min(len(text), lo + CONTEXT_CHARS)
        lo = max(0, hi - CONTEXT_CHARS)
        para = text.rfind("\n\n", lo, ex_start)
        if para != -1 and ex_start - para < CONTEXT_CHARS // 2:
            lo = para + 2
        nxt = text.find("\n\n", ex_end, hi)
        if nxt != -1 and nxt > ex_end:
            hi = max(nxt, min(hi, ex_end + 400))
    ctx = text[lo:hi]
    pages: list[dict] = [{"offset": 0, "page": sec.page_at(lo)}]
    for off, p in zip(sec.page_offsets, sec.page_numbers):
        if lo < off < hi and p != pages[-1]["page"]:
            pages.append({"offset": off - lo, "page": p})
    return ctx, {"start": ex_start - lo, "end": ex_end - lo}, pages


def _highlights(doc: pymupdf.Document, sec: Section, start: int, end: int) -> list[dict]:
    """Locate the excerpt on its PDF page(s) and return normalized rectangles."""
    out: dict[int, list[list[float]]] = defaultdict(list)
    for a, b in sentence_spans(sec.text, start, end) or [(start, end)]:
        text = normalize_ws(sec.text[a:b])
        page_no = sec.page_at(a)
        rects = _search(doc, page_no, text)
        if not rects and sec.page_at(b - 1) != page_no:
            rects = _search(doc, sec.page_at(b - 1), text)
            page_no = sec.page_at(b - 1)
        page = doc[page_no - 1]
        w, h = page.rect.width, page.rect.height
        for rc in rects:
            out[page_no].append([round(rc.x0 / w, 4), round(rc.y0 / h, 4), round(rc.x1 / w, 4), round(rc.y1 / h, 4)])
    return [{"page": p, "rects": r} for p, r in sorted(out.items())]


def _search(doc: pymupdf.Document, page_no: int, text: str) -> list:
    if page_no < 1 or page_no > doc.page_count:
        return []
    page = doc[page_no - 1]
    ws = text.split()
    attempts = [text] if len(ws) <= 40 else []
    if len(ws) > 6:
        # Search in pieces so line breaks, hyphenation, or ligatures don't defeat the match.
        step = 8
        attempts.append([" ".join(ws[i:i + step]) for i in range(0, len(ws), step)])
    elif not attempts:
        attempts = [text]
    for att in attempts:
        if isinstance(att, str):
            try:
                rects = page.search_for(att)
            except Exception:  # noqa: BLE001
                rects = []
            if rects:
                return rects
        else:
            found = []
            for piece in att:
                if len(piece) < 12:
                    continue
                try:
                    hits = page.search_for(piece)
                except Exception:  # noqa: BLE001
                    hits = []
                if len(hits) <= 2:  # ambiguous pieces (very common phrases) are skipped
                    found.extend(hits)
            if found:
                return found
    return []


# --------------------------------------------------------------------------- insights


def build_insights(results: list[dict], ranked: list[Ranked], q: Query, doc_stems: set[str]) -> list[dict]:
    insights: list[dict] = []
    if len(results) >= 3:
        tops = Counter(r["breadcrumb"][0] for r in results if r["breadcrumb"])
        name, n = tops.most_common(1)[0]
        if n >= 3 and n / len(results) >= 0.4 and name != "Opening pages":
            members = [r for r in results if r["breadcrumb"] and r["breadcrumb"][0] == name]
            pages = [r["page_start"] for r in members]
            insights.append({
                "result_ids": [r["id"] for r in members],
                "kind": "concentration",
                "title": "Where the answers cluster",
                "text": f"{n} of {len(results)} results sit under “{name}” (pp. {min(pages)}–{max(pages)}). "
                        f"Reading that part in full may be efficient.",
                "pages": sorted(set(pages)),
            })

    # Recurring concepts beyond the user's own words, shared by several results.
    if len(results) >= 3:
        df: Counter[str] = Counter()
        surface: dict[str, str] = {}
        where: dict[str, list[int]] = defaultdict(list)
        which: dict[str, list[str]] = defaultdict(list)
        query_stems = set(q.key_terms)
        for r, rk in zip(results, ranked):
            text = rk.section.text[rk.start:rk.end]
            seen = set()
            pairs = []
            # Only words that are truly adjacent (no punctuation between) form a concept.
            for frag in re.split(r"[^\w\s\-']+", text):
                toks = words(frag)
                for a, b in zip(toks, toks[1:]):
                    if a.lower() in STOP_WORDS or b.lower() in STOP_WORDS or len(a) <= 3 or len(b) <= 3:
                        continue
                    pairs.append(((a, stem(a.lower())), (b, stem(b.lower()))))
            for (w1, s1), (w2, s2) in pairs:
                key = f"{s1} {s2}"
                if s1 in query_stems or s2 in query_stems or s1 == s2:
                    continue
                if key not in seen:
                    seen.add(key)
                    df[key] += 1
                    where[key].append(r["page_start"])
                    which[key].append(r["id"])
                    surface.setdefault(key, f"{w1} {w2}".lower())
        common = [(k, n) for k, n in df.most_common(20) if n >= 3 and n / len(results) >= 0.3]
        if common:
            k, n = common[0]
            insights.append({
                "result_ids": which[k],
                "kind": "recurring",
                "title": "A recurring concept",
                "text": f"“{surface[k]}” appears in {n} of your results — likely central to this topic in this document.",
                "pages": sorted(set(where[k])),
            })

    missing = [q.surface.get(s, s) for s, w in q.key_terms.items() if s not in doc_stems and len(s) > 2]
    if missing:
        verb = "does" if len(missing) == 1 else "do"
        tail = ", so results are based on your other terms." if results else "."
        insights.append({
            "result_ids": [],
            "kind": "gap",
            "title": "Not found in this document",
            "text": f"{_join(missing[:4])} {verb} not appear anywhere in this PDF{tail}",
            "pages": [],
        })
    return insights[:3]
