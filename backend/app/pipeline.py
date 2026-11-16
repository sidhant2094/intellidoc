"""End-to-end analysis as a generator of real progress events."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import pymupdf

from . import errors
from .explain import build_insights, build_results
from .pdf_extract import extract
from .gemini.client import get_service
from .gemini.summarizer import enrich
from .ranking import build_query
from .retrieval.hybrid import rank_hybrid
from .session import store
from .schemas import AnalyzeResponse
from .sections import build_structure, chunk_sections
from .text_utils import content_stems

log = logging.getLogger("intellidoc.pipeline")

# Deliberately provider-neutral: the UI must not reveal which processing path ran.
METHOD = "Hybrid relevance ranking across meaning, keywords, content type, expertise and structure."


def stage(name: str, detail: str = "") -> dict:
    return {"type": "stage", "stage": name, "detail": detail}


def analyze(
    doc: pymupdf.Document,
    filename: str,
    persona: str,
    expertise: str,
    objective: str,
    focus_terms: list[str],
) -> Iterator[dict]:
    t0 = time.perf_counter()
    warnings: list[dict] = []

    yield stage("reading", f"Extracting text from {doc.page_count} page{'s' if doc.page_count != 1 else ''}")
    ex = extract(doc)
    warnings += ex.warnings
    scanned = ex.scanned_pages
    if ex.pages_with_text == 0:
        raise errors.no_text(scanned=bool(scanned))
    if scanned:
        share = len(scanned) / ex.page_count
        pages = _page_list(scanned)
        warnings.append({
            "code": "scanned_pages",
            "message": f"{len(scanned)} page{'s' if len(scanned) > 1 else ''} ({pages}) look scanned and have no "
                       f"extractable text. OCR isn't available locally, so {'they were' if len(scanned) > 1 else 'it was'} skipped"
                       + (" — results cover only a small part of this document." if share > 0.5 else "."),
        })

    yield stage("sections", "Detecting headings and page boundaries")
    structure = build_structure(ex)
    for note in structure.notes:
        warnings.append({"code": f"structure_{structure.source}", "message": note})
    chunks = chunk_sections(structure.sections)
    if not chunks:
        raise errors.no_text(scanned=bool(scanned))
    real_sections = [s for s in structure.sections if s.word_count >= 12]
    yield stage("sections", f"{len(real_sections)} sections, {len(chunks)} passages "
                            f"({'from PDF bookmarks' if structure.source == 'outline' else 'reconstructed from layout' if structure.source == 'headings' else 'grouped by page'})")

    yield stage("matching", "Scoring passages against your objective")
    q = build_query(objective, persona, expertise, focus_terms)
    if not q.key_terms:
        warnings.append({
            "code": "vague_objective",
            "message": "Your objective is very general, so ranking relies on overall wording. Naming specific topics gives better results.",
        })
    svc = get_service()
    outcome = rank_hybrid(chunks, q, svc)
    ranked, meta = outcome.ranked, outcome.meta

    yield stage("ranking", "Selecting the strongest sections and explaining why they matter")
    docs = [c.text for c in chunks]
    results = build_results(ranked, q, doc, docs)
    doc_stems = set()
    for c in chunks:
        doc_stems.update(content_stems(c.section.title + " " + c.text))
    insights = build_insights(results, ranked, q, doc_stems)
    if svc and results and svc.available("generate"):
        ai_insights = enrich(svc, results, ranked, q)  # grounded; on failure results keep local text
        if ai_insights:
            gap = [i for i in insights if i["kind"] == "gap"]  # measured fact: keep it
            insights = (ai_insights + gap)[:5]

    session = store.create(
        filename=filename, sections=structure.sections, chunks=chunks, query=q,
        results=[{"id": r["id"], "section_id": r["section_id"]} for r in results],
        chunk_matrix=outcome.chunk_matrix, embedded_idx=outcome.embedded_idx,
    )

    duration = int((time.perf_counter() - t0) * 1000)
    payload = {
        "session_id": session.id,
        "document": {
            "filename": filename,
            "title": ex.title,
            "page_count": ex.page_count,
            "pages_with_text": ex.pages_with_text,
            "scanned_pages": scanned,
            "blank_pages": [p.number for p in ex.pages if p.status == "blank"],
            "section_count": len(real_sections),
            "chunk_count": len(chunks),
            "structure_source": structure.source,
        },
        "analysis": {
            "persona": persona,
            "expertise": expertise,
            "objective": objective,
            "focus_terms": focus_terms,
            "duration_ms": duration,
            "method": METHOD,
            "weights": meta.get("weights", {}),
            "content_type_active": meta.get("content_type_active", False),
            "detected_intents": meta.get("intents", []),
            "candidates_considered": meta.get("candidates", 0),
        },
        "results": results,
        "insights": insights,
        "warnings": warnings,
    }
    validated = AnalyzeResponse.model_validate(payload).model_dump()
    log.info("Analyzed %s: %d pages, %d chunks, %d results in %d ms (path=%s)",
             filename, ex.page_count, len(chunks), len(results), duration, outcome.path)
    yield {"type": "result", "data": validated}


def _page_list(pages: list[int]) -> str:
    """Compact page list: 1–3, 7, 9–10."""
    out, start, prev = [], None, None
    for p in pages + [None]:
        if start is None:
            start = prev = p
        elif p is not None and p == prev + 1:
            prev = p
        else:
            out.append(f"{start}–{prev}" if prev != start else f"{start}")
            start = prev = p
    text = ", ".join(out[:6])
    return f"p. {text}" + (" …" if len(out) > 6 else "")
