"""Extraction, page mapping, ranking and no-match behaviour on synthetic PDFs."""

from __future__ import annotations

import pymupdf
import pytest

from app import errors
from app.pdf_extract import extract, open_pdf
from app.pipeline import analyze
from app.sections import build_structure, chunk_sections
from app.text_utils import normalize_ws, sentence_spans, stem


def run(data: bytes, objective: str, persona="Software Engineer", expertise="Intermediate", focus=()):
    doc = open_pdf(data)
    events = list(analyze(doc, "test.pdf", persona, expertise, objective, list(focus)))
    stages = [e["stage"] for e in events if e["type"] == "stage"]
    result = next(e["data"] for e in events if e["type"] == "result")
    return stages, result, doc


def test_extraction_preserves_pages_and_strips_nothing_important(handbook_pdf):
    ex = extract(open_pdf(handbook_pdf))
    assert ex.page_count == 4
    assert ex.pages_with_text == 4
    pages_for = {l.text.strip(): l.page for l in ex.lines}
    assert pages_for["2 Deployment Architecture"] == 2
    assert pages_for["4 Security Practices"] == 4


def test_detects_code_and_table_content(handbook_pdf):
    ex = extract(open_pdf(handbook_pdf))
    kinds = {l.kind for l in ex.lines if l.kind}
    assert "code" in kinds
    assert "table" in kinds or "caption_table" in kinds


@pytest.mark.parametrize("fixture,source", [("handbook_pdf", "headings"), ("handbook_outline_pdf", "outline")])
def test_section_reconstruction(fixture, source, request):
    ex = extract(open_pdf(request.getfixturevalue(fixture)))
    st = build_structure(ex)
    assert st.source == source
    titles = [s.title for s in st.sections]
    assert any("Deployment Architecture" in t for t in titles)
    sub = next(s for s in st.sections if "Audience" in s.title)
    assert sub.level == 2 and "Introduction" in sub.path[0]
    dep = next(s for s in st.sections if "Deployment" in s.title)
    assert dep.page_start == dep.page_end == 2


def test_chunks_keep_page_mapping(handbook_pdf):
    st = build_structure(extract(open_pdf(handbook_pdf)))
    for c in chunk_sections(st.sections):
        assert 1 <= c.page_start <= c.page_end <= 4
        assert c.text == c.section.text[c.start:c.end]


def test_ranking_finds_deployment_section_with_correct_page_and_verbatim_excerpt(handbook_pdf):
    stages, res, doc = run(handbook_pdf, "deployment rollout strategy and database migration constraints")
    assert stages[:4] == ["reading", "sections", "sections", "matching"] and stages[-1] == "ranking"
    top = res["results"][0]
    assert "Deployment" in top["title"]
    assert top["page_start"] == top["page_end"] == 2
    assert top["excerpt_page"] == 2
    page_text = normalize_ws(doc[1].get_text())
    # Excerpt is verbatim source text from the cited page.
    assert normalize_ws(top["excerpt"].rstrip(" …")) in page_text
    assert top["highlights"] and top["highlights"][0]["page"] == 2
    assert "rollout" in " ".join(top["matched_terms"]) or "deployment" in " ".join(top["matched_terms"])
    assert 0 < top["match_score"] <= 1
    # Results are ordered and unique per section
    scores = [r["match_score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True)
    assert len({r["section_id"] for r in res["results"]}) == len(res["results"])


def test_key_points_are_verbatim(handbook_pdf):
    _, res, doc = run(handbook_pdf, "how are customers billed and refunded")
    top = res["results"][0]
    assert "Pricing" in top["title"]
    full = normalize_ws(" ".join(p.get_text() for p in doc))
    for kp in top["key_points"]:
        assert normalize_ws(kp["text"]) in full


def test_content_type_boost_when_asking_for_table(handbook_pdf):
    _, res, _ = run(handbook_pdf, "price comparison table for plans and storage", persona="Business Analyst")
    top = res["results"][0]
    assert "Pricing" in top["title"]
    assert "table" in top["content_types"]
    assert res["analysis"]["content_type_active"] is True
    assert top["signals"]["content_type"] == 1.0


def test_no_match_returns_empty_results(handbook_pdf):
    _, res, _ = run(handbook_pdf, "medieval falconry techniques and bird diets", persona="Student")
    assert res["results"] == []


def test_never_more_than_ten_and_fewer_when_weak(handbook_pdf):
    _, res, _ = run(handbook_pdf, "security keys and encrypted traffic")
    assert 1 <= len(res["results"]) <= 10
    assert "Security" in res["results"][0]["title"]
    assert len(res["results"]) < 5  # unrelated sections are not padded in


def test_encrypted_pdf_is_rejected(encrypted_pdf):
    with pytest.raises(errors.AnalysisError) as e:
        open_pdf(encrypted_pdf)
    assert e.value.code == "password_protected"


def test_not_a_pdf_is_rejected():
    with pytest.raises(errors.AnalysisError) as e:
        open_pdf(b"hello, this is plain text")
    assert e.value.code == "invalid_file_type"


def test_malformed_pdf_is_rejected():
    with pytest.raises(errors.AnalysisError) as e:
        open_pdf(b"%PDF-1.7\n garbage garbage")
    assert e.value.code in {"malformed_pdf"}


def test_scanned_pdf_reports_scanned(scanned_pdf):
    doc = open_pdf(scanned_pdf)
    with pytest.raises(errors.AnalysisError) as e:
        list(analyze(doc, "s.pdf", "Student", "Beginner", "anything useful", []))
    assert e.value.code == "scanned_pdf"


def test_blank_pdf_reports_no_text(blank_pdf):
    doc = open_pdf(blank_pdf)
    with pytest.raises(errors.AnalysisError) as e:
        list(analyze(doc, "b.pdf", "Student", "Beginner", "anything useful", []))
    assert e.value.code == "no_text"


def test_sentence_spans_and_stemmer():
    text = "Use e.g. caching here. Then deploy! Finally verify the rollout."
    spans = [text[a:b] for a, b in sentence_spans(text)]
    assert spans == ["Use e.g. caching here.", "Then deploy!", "Finally verify the rollout."]
    assert stem("deployments") == stem("deployment") == stem("deploy") or stem("deployments") == stem("deployment")
    assert stem("policies") == stem("policy")
