# IntelliDoc — Implementation Plan

Source of truth: `INTELLIDOC_BUILD_SPEC.md`. This file tracks execution.

## Structure

```
backend/   FastAPI · PyMuPDF · scikit-learn  (app/, tests/)
frontend/  React · Vite · TypeScript · Tailwind v4 · lucide-react · pdf.js
start.sh   one-command install + run (backend :8000, frontend :5173)
```

## Key decisions

- **Real progress**: `POST /api/analyze` streams NDJSON stage events, then the result.
- **Structure**: PDF outline (bookmarks) when present → otherwise typography/numbering heuristics.
- **Ranking**: transparent 5-signal weighted score (35/25/20/15/5); non-measurable signals
  (content-type with no type intent) have their weight redistributed, not faked.
- **Traceability**: every excerpt is a verbatim span; its page is computed from character offsets
  and located on the page with PyMuPDF for highlight boxes.
- **Optional, deferred**: local embeddings (torch is heavy), Gemini, OCR (Tesseract not installed).

## Checklist

### M1 Inspect & plan
- [x] Inspect environment (Node 25, uv + Python 3.13, no Tesseract)
- [x] Read spec + master prompt
- [x] Plan + structure

### M2 Backend
- [x] FastAPI app, health, CORS, multipart analyze (streamed stages)
- [x] Validation: type, size (30 MB), malformed, encrypted, no text, scanned
- [x] Extraction w/ header/footer stripping, page mapping, content-type detection
- [x] Section reconstruction (outline + heuristics), chunking w/ overlap
- [x] Ranking, aggregation, dedup, threshold, explanations, excerpts, insights
- [x] Tests: extraction, page mapping, ranking, no-match, errors

### M3–M4 Frontend + wiring
- [x] Design tokens, light/dark (persisted, system default, no flash)
- [x] Workspace: persona, expertise, objective, focus terms, dropzone, file card
- [x] Streaming analysis stages, cancel, errors, backend-offline state
- [x] Results: rail, detail, score breakdown, context, insights, stats
- [x] Source page viewer with excerpt highlight; open original PDF at page
- [x] Export reading list (Markdown)

### M5–M6 Polish & verify
- [x] Both themes, responsive layouts
- [x] Tests + typecheck/build green
- [x] End-to-end with real PDFs, verify pages/excerpts
- [x] README

## Status (2026-11-16)

All P0 items and these P1 items are done: embedded PDF viewer with excerpt highlight, jump to page, Markdown export.

Verified: 25 backend tests pass; `tsc` + lint + production build are clean; the browser end-to-end runs passed
(both real PDFs, theme toggle + persistence + system default, keyboard nav, mobile layout, and errors: not-PDF,
password, scanned, no-match, engine offline). There were zero console errors.

Not done (optional): local embeddings, Gemini adapter, OCR (Tesseract not installed).

---

# IntelliDoc 2.0 — Gemini upgrade (2026-11-17)

Enhancement on top of 1.0; every 1.0 test and behavior is preserved (the no-key path ranks identically).

- [x] **M1 Audit.** Found local-only/provider-revealing UI copy, provider fields in `/api/health` and
      `analysis.method`, and a stateless API. Ask IntelliDoc needs sessions.
- [x] **M2 Config & client.** `.env` / `.env.example`, key never logged or exposed. Models validated via
      `models.list` with substitution. One retry for transient errors only; a 429 opens a circuit breaker honoring
      `retryDelay`; auth errors pause; daily request budget.
- [x] **M3 Embeddings.** Batched (100/request), deduplicated, in-memory TTL cache, 500-passage cap for very long
      docs, configurable dimensions; page mapping untouched.
- [x] **M4 Hybrid retrieval.** `ranking.py` split into `compute_signals`/`combine`/`aggregate`. Embedding
      similarity replaces TF-IDF in hybrid mode (no double counting), normalized against the document baseline.
      Topical gating now includes contextual relevance.
- [x] **M5 Reranking & explanations.** Lean rerank call (~24 candidates, IDs validated, ≥60% coverage required);
      one call for summaries/findings/takeaways/limitations; sentence-level grounding guards.
- [x] **M6 Insights.** 3–5 insights citing real result IDs; pages derived from IntelliDoc data; local
      "terms not found" fact kept.
- [x] **M7 Ask IntelliDoc.** In-memory sessions (≤12, 45-min TTL); per-question hybrid retrieval with
      section-number references and boilerplate down-weighting; validated, renumbered citations; bounded history;
      honest "not found"; extractive local fallback.
- [x] **M8 Frontend.** Removed engine/local-only copy; provider-neutral "How it works" with a privacy note;
      summary, findings, takeaways, limitations; linked insights; Ask drawer with citations and cited-page preview
      (portal-rendered); export updated. Both themes verified.
- [x] **M9 Verification.** 58 backend tests (Gemini mocked). tsc, oxlint and the build are clean. Browser
      end-to-end on 2 real PDFs × 3 server modes (no key, mocked Gemini, quota-exhausted 429): no console
      errors, no provider-revealing text on any screen, and 429 results identical to the no-key results.

## 2.0.1: Gemini generation reliability fix (2026-11-17)

- [x] **Audit.** Empty and `MAX_TOKENS` responses were treated as successes and then surfaced as "malformed
      JSON". Thinking tokens consumed the output budget. Retries were a single fixed retry. Cooldown was
      per capability, not per model. Model substitution guessed from the list (it could pick 404 models).
- [x] **Model probe** (real key, 512 tokens, thinking low, no auto-retries). Primary
      `gemini-3.1-flash-lite` (text + JSON, ~3 s); fallback `gemini-3.6-flash` (text + JSON, ~22–37 s).
      3.8/3.7 returned 503, 3.5 a 504, 2.5 a 404.
- [x] **Client.** Non-thought text extraction; empty/MAX_TOKENS detection with one larger-budget retry;
      thinking only where model metadata supports it, with headroom; bounded exponential backoff + jitter;
      RetryInfo/Retry-After; overall deadline; per-model cooldowns; one fallback model; embeddings independent.
- [x] **Config.** `.env`: `GEMINI_MODEL=gemini-3.1-flash-lite`, `GEMINI_FALLBACK_MODEL=gemini-3.6-flash`
      (key, enabled flag and embedding model unchanged). `.env.example` and README updated.
- [x] **Tests.** 79 pass (21 new generation-reliability tests), Gemini mocked.
- [x] **Live.** Smoke test passes for both models and embeddings. The browser workflow passed on both PDFs
      (`path=full`), including a real 503 recovered by retry; Ask IntelliDoc answered with Gemini.
