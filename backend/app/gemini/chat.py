"""Ask IntelliDoc: grounded answers to follow-up questions, with validated citations."""

from __future__ import annotations

import logging
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from ..ranking import BOILERPLATE_WANTED, build_query
from ..retrieval.semantic import normalize_similarity
from ..sections import Chunk
from ..session import Session
from ..text_utils import analyzer, content_stems, normalize_ws, sentence_spans
from .client import GeminiService, GeminiUnavailable
from .embeddings import embed_texts
from .grounding import Source, clean_text, section_numbers
from .reranker import reader_block

log = logging.getLogger("intellidoc.chat")

MAX_EVIDENCE = 6
EVIDENCE_WORDS = 220
NOT_FOUND = ("I couldn't find anything in this document that answers that. "
             "Try rephrasing with terms the document is likely to use.")

SECTION_REF = re.compile(r"\b(?:sections?|chapters?|§)\s*((?:[A-Z]?\d+(?:\.\d+)*)(?:\s*(?:,|and|&|or)\s*[A-Z]?\d+(?:\.\d+)*)*)", re.I)

SYSTEM = (
    "You are IntelliDoc, a careful research assistant answering questions about ONE document. "
    "Answer ONLY from the evidence passages supplied. Cite every claim with the evidence ids in square brackets, "
    "e.g. [E2]. Never invent facts, sections, page numbers or quotations. If the evidence does not answer the "
    "question, say so plainly and set supported to false. Be concise and write for the reader's expertise level."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supported": {"type": "boolean"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "supported", "citations"],
}


# --------------------------------------------------------------------------- retrieval


def referenced_sections(question: str, sess: Session) -> set[str]:
    refs: set[str] = set()
    for m in SECTION_REF.finditer(question):
        for num in re.findall(r"[A-Z]?\d+(?:\.\d+)*", m.group(1)):
            for s in sess.sections:
                head = re.match(r"\s*(?:appendix\s+)?([A-Z]?\d+(?:\.\d+)*)\.?\s", s.title + " ", re.I)
                if head and (head.group(1) == num or head.group(1).startswith(num + ".")):
                    refs.add(s.id)
    return refs


def retrieve(sess: Session, question: str, svc: GeminiService | None) -> list[tuple[Chunk, float]]:
    chunks = sess.chunks
    if not chunks:
        return []
    qtext = question
    if len(question.split()) < 6 and sess.history:
        qtext = f"{question} {sess.history[-1]['q']}"  # short follow-ups lean on the previous turn

    docs = [f"{c.section.title}\n{c.text}" for c in chunks]
    vec = TfidfVectorizer(analyzer=analyzer, sublinear_tf=True)
    W = vec.fit_transform(docs)
    tf = linear_kernel(vec.transform([qtext]), W).ravel()
    tf_n = np.clip(tf / max(float(tf.max()), 0.25), 0, 1)

    q = build_query(qtext, sess.query.persona, sess.query.expertise, [])
    kw = np.zeros(len(chunks))
    if q.key_terms:
        tot = sum(q.key_terms.values())
        for i, d in enumerate(docs):
            st = set(content_stems(d))
            kw[i] = sum(w for s, w in q.key_terms.items() if s in st) / tot

    emb = None
    if svc and sess.chunk_matrix is not None and svc.available("embed"):
        try:
            qv = embed_texts(svc, [qtext], "RETRIEVAL_QUERY")[0]
            emb = np.zeros(len(chunks))
            emb[sess.embedded_idx] = normalize_similarity(sess.chunk_matrix @ qv)
        except GeminiUnavailable as exc:
            log.info("Question embedding skipped: %s", exc)

    score = 0.5 * emb + 0.3 * tf_n + 0.2 * kw if emb is not None else 0.6 * tf_n + 0.4 * kw

    # Ground generic questions ("what should I read next?") in the reading path.
    top_results = {r["section_id"]: 0.15 * (1 - i / 10) for i, r in enumerate(sess.results[:5])}
    refs = referenced_sections(question, sess)
    wants_boiler = bool(BOILERPLATE_WANTED.search(question))
    for i, c in enumerate(chunks):
        if c.section.boilerplate and not wants_boiler:
            score[i] *= 0.3  # references / contents / acknowledgments rarely answer a question
        score[i] += top_results.get(c.section.id, 0.0)
        if c.section.id in refs:
            score[i] += 1.0

    order = np.argsort(-score)
    picked: list[tuple[Chunk, float]] = []
    per_section: dict[str, int] = {}
    for i in order:
        c = chunks[i]
        cap = 2 if c.section.id in refs else 1
        if per_section.get(c.section.id, 0) >= cap:
            continue
        if score[i] < 0.12 and picked:
            break
        picked.append((c, float(score[i])))
        per_section[c.section.id] = per_section.get(c.section.id, 0) + 1
        if len(picked) >= MAX_EVIDENCE:
            break
    return picked


def _window(c: Chunk, question: str) -> tuple[int, int]:
    """Character span (in section text) of the most question-relevant window of a chunk."""
    keys = set(content_stems(question))
    spans = sentence_spans(c.section.text, c.start, c.end) or [(c.start, c.end)]
    hits = [len(set(content_stems(c.section.text[a:b])) & keys) for a, b in spans]
    best_i = int(np.argmax(hits)) if hits else 0
    lo = hi = best_i
    words = len(c.section.text[spans[lo][0]:spans[hi][1]].split())
    while words < EVIDENCE_WORDS and (lo > 0 or hi < len(spans) - 1):
        if hi < len(spans) - 1:
            hi += 1
        if lo > 0 and words < EVIDENCE_WORDS:
            lo -= 1
        words = len(c.section.text[spans[lo][0]:spans[hi][1]].split())
    return spans[lo][0], spans[hi][1]


def _best_sentence(c: Chunk, a: int, b: int, question: str) -> tuple[str, int]:
    keys = set(content_stems(question))
    best, best_v = (a, b), -1.0
    for s, e in sentence_spans(c.section.text, a, b):
        t = c.section.text[s:e]
        wc = len(t.split())
        if wc < 6:
            continue
        v = len(set(content_stems(t)) & keys) + (0.3 if wc <= 45 else 0)
        if t.lstrip("•o–- ")[:1].isupper():
            v += 0.5  # prefer complete sentences over mid-list fragments
        if v > best_v:
            best, best_v = (s, e), v
    s, e = best
    text = normalize_ws(c.section.text[s:e])
    ws = text.split()
    if len(ws) > 60:
        text = " ".join(ws[:60]) + " …"
    return text, c.section.page_at(s)


# --------------------------------------------------------------------------- answering


def answer(sess: Session, question: str, svc: GeminiService | None) -> dict:
    evidence = retrieve(sess, question, svc)
    items = []
    for i, (c, score) in enumerate(evidence, start=1):
        a, b = _window(c, question)
        excerpt, ex_page = _best_sentence(c, a, b, question)
        items.append({
            "eid": f"E{i}", "chunk": c, "score": score, "start": a, "end": b,
            "text": normalize_ws(c.section.text[a:b]), "excerpt": excerpt, "excerpt_page": ex_page,
        })

    out = None
    if svc and items and svc.available("generate"):
        out = _answer_gemini(sess, question, items, svc)
    if out is None:
        out = _answer_local(question, items, sess)

    with sess.lock:
        plain = re.sub(r"\s*\[\d+\]", "", out["answer"])
        sess.history.append({"q": question[:300], "a": plain[:500]})
    return out


def _citation(item: dict, n: int, sess: Session) -> dict:
    c: Chunk = item["chunk"]
    sec = c.section
    result_id = next((r["id"] for r in sess.results if r["section_id"] == sec.id), None)
    return {
        "n": n,
        "section_id": sec.id,
        "title": sec.title,
        "breadcrumb": sec.path,
        "page_start": sec.page_at(item["start"]),
        "page_end": sec.page_at(max(item["start"], item["end"] - 1)),
        "excerpt": item["excerpt"],
        "excerpt_page": item["excerpt_page"],
        "result_id": result_id,
    }


def _answer_gemini(sess: Session, question: str, items: list[dict], svc: GeminiService) -> dict | None:
    history = "\n".join(f"Q: {h['q']}\nA: {h['a']}" for h in list(sess.history)[-4:])
    blocks = []
    for it in items:
        c: Chunk = it["chunk"]
        pages = f"{c.section.page_at(it['start'])}–{c.section.page_at(max(it['start'], it['end'] - 1))}"
        blocks.append(f"[{it['eid']}] Section: {' > '.join(c.section.path)} | Pages: {pages}\n{it['text']}")
    prompt = (
        f"{reader_block(sess.query)}\n\n"
        + (f"EARLIER IN THIS CONVERSATION\n{history}\n\n" if history else "")
        + "EVIDENCE\n" + "\n\n".join(blocks)
        + f"\n\nQUESTION: {question}\n\n"
        "Answer in at most ~150 words, citing evidence ids like [E1] after the claims they support. "
        "If the evidence doesn't answer the question, say what the document does and doesn't cover."
    )
    try:
        data = svc.generate_json(SYSTEM, prompt, SCHEMA, max_tokens=900, timeout_s=35)
    except GeminiUnavailable as exc:
        log.info("Answer fell back to local: %s", exc)
        return None
    return validate_answer(data, items, sess)


def validate_answer(data: object, items: list[dict], sess: Session) -> dict | None:
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
        return None
    by_eid = {it["eid"]: it for it in items}
    raw = data["answer"]
    supported = bool(data.get("supported"))

    pages = set()
    for it in items:
        sec = it["chunk"].section
        pages |= set(range(sec.page_at(it["start"]), sec.page_at(max(it["start"], it["end"] - 1)) + 1))
    src = Source([it["text"] for it in items], pages, section_numbers([s.title for s in sess.sections]))

    # Keep markers on their own so sentence cleaning doesn't treat "[E2]" as a number.
    marked = re.sub(r"\[(E\d+)(?:\s*,\s*(E\d+))*\]", lambda m: " ".join(f"⟦{x}⟧" for x in re.findall(r"E\d+", m.group(0))), raw)
    marked = re.sub(r"\[[^\]]*\]", "", marked)  # anything else bracketed is not a valid citation
    cleaned = clean_text(marked.replace("⟦", "{").replace("⟧", "}"), src, 1400)

    order: list[str] = []

    def renumber(m: re.Match) -> str:
        eid = m.group(1)
        if eid not in by_eid:
            return ""
        if eid not in order:
            order.append(eid)
        return f"[{order.index(eid) + 1}]"

    text = re.sub(r"\s*\{(E\d+)\}", renumber, cleaned)
    text = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"(\])(?=\w)", r"\1 ", text)).strip()

    if supported and not order:
        supported = False  # claims without evidence are not shown as supported
    if not text or (not supported and not order and len(text) < 20):
        text = NOT_FOUND
    if not supported and not order:
        return {"answer": text, "supported": False, "citations": []}
    return {
        "answer": text,
        "supported": supported,
        "citations": [_citation(by_eid[e], i + 1, sess) for i, e in enumerate(order)],
    }


GENERIC_RE = re.compile(
    r"\b(most important|key (?:findings?|points?|ideas?|takeaways?)|main (?:findings?|points?|ideas?)|"
    r"summar\w*|overview|read (?:next|first)|start with|tl;?dr|highlights?|top results?)\b", re.I)


def _answer_local(question: str, items: list[dict], sess: Session) -> dict:
    keys = set(build_query(question, "", "", []).key_terms)
    useful = [it for it in items if keys & set(content_stems(it["text"])) or it["score"] >= 0.5]
    if GENERIC_RE.search(question):
        # Generic questions are answered from the reading path, in rank order.
        rank = {r["section_id"]: i for i, r in enumerate(sess.results)}
        path = sorted((it for it in items if it["chunk"].section.id in rank), key=lambda it: rank[it["chunk"].section.id])
        useful = path or useful
    if not useful:
        return {"answer": NOT_FOUND, "supported": False, "citations": []}
    useful = useful[:3]
    parts = [f"“{it['excerpt']}” [{n}]" for n, it in enumerate(useful, start=1)]
    titles = sorted({it["chunk"].section.title for it in useful}, key=lambda t: [it["chunk"].section.title for it in useful].index(t))
    lead = f"The most relevant passages are in {_join(titles)}:"
    return {
        "answer": lead + " " + " ".join(parts),
        "supported": True,
        "citations": [_citation(it, n, sess) for n, it in enumerate(useful, start=1)],
    }


def _join(items: list[str]) -> str:
    items = [f"“{i}”" for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
