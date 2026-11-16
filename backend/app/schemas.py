"""Typed response contract for /api/analyze (also rendered in /docs)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Warning_(BaseModel):
    code: str
    message: str


class DocumentInfo(BaseModel):
    filename: str
    title: str | None
    page_count: int
    pages_with_text: int
    scanned_pages: list[int]
    blank_pages: list[int]
    section_count: int
    chunk_count: int
    structure_source: Literal["outline", "headings", "pages"]


class AnalysisInfo(BaseModel):
    persona: str
    expertise: str
    objective: str
    focus_terms: list[str]
    duration_ms: int
    method: str
    weights: dict[str, float]
    content_type_active: bool
    detected_intents: list[str]
    candidates_considered: int


class KeyPoint(BaseModel):
    text: str
    page: int


class Highlight(BaseModel):
    page: int
    rects: list[list[float]]  # [x0, y0, x1, y1] as fractions of page size


class PageMark(BaseModel):
    offset: int
    page: int


class Span(BaseModel):
    start: int
    end: int


class Result(BaseModel):
    id: str
    rank: int
    section_id: str
    title: str
    breadcrumb: list[str]
    level: int
    page_start: int
    page_end: int
    match_score: float
    relevance_label: str
    why_relevant: str
    matched_terms: list[str]
    summary: str
    findings: list[str] = []
    takeaways: list[str] = []
    limitations: list[str] = []
    key_points: list[KeyPoint]
    excerpt: str
    excerpt_page: int
    highlights: list[Highlight]
    content_types: list[str]
    context: str
    context_excerpt: Span
    context_pages: list[PageMark]
    signals: dict[str, float]


class Insight(BaseModel):
    kind: Literal["concentration", "recurring", "gap", "theme", "relationship", "contradiction", "repetition", "risk"]
    title: str
    text: str
    pages: list[int]
    result_ids: list[str] = []


class AnalyzeResponse(BaseModel):
    session_id: str | None = None
    document: DocumentInfo
    analysis: AnalysisInfo
    results: list[Result]
    insights: list[Insight]
    warnings: list[Warning_]


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str = ""


class AskRequest(BaseModel):
    question: str


class Citation(BaseModel):
    n: int
    section_id: str
    title: str
    breadcrumb: list[str]
    page_start: int
    page_end: int
    excerpt: str
    excerpt_page: int
    result_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    supported: bool
    citations: list[Citation]
