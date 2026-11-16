# IntelliDoc 2.0

**Find what matters. Skip what doesn't.**

IntelliDoc is a persona-aware document research assistant. Tell it who you are and what you're trying to find,
upload a long PDF, and get a ranked reading path of up to 10 sections. Each one comes with exact page numbers, a
verbatim excerpt highlighted on the source page, an explanation of why it matters to *you*, and grounded summaries.
You can then ask follow-up questions and get answers with verifiable citations.

IntelliDoc works with or without an AI service configured. The interface is the same either way.

## Quick start

Requirements: **Node 18+** and **Python 3.10+** (or [`uv`](https://docs.astral.sh/uv/), used automatically if present).

```bash
./start.sh
```

Open **http://localhost:5173**. The first run installs dependencies, and later runs re-install Python packages
whenever `requirements*.txt` change. Press `Ctrl+C` to stop.

### Optional: enable Gemini

```bash
cp backend/.env.example backend/.env
# edit backend/.env and set GEMINI_API_KEY=...   (never commit this file; it is gitignored)
cd backend && .venv/bin/python -m scripts.gemini_smoke   # ~7 small requests: tests each model + embeddings
```

Restart `./start.sh` after changing `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Your key from Google AI Studio. Empty → built-in engine only. |
| `GEMINI_ENABLED` | `true` | Set `false` to force the built-in engine even with a key. |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Primary reasoning model (reranking, summaries, insights, answers). |
| `GEMINI_FALLBACK_MODEL` | *(empty; `.env.example`: `gemini-3.6-flash`)* | Tried once if the primary is overloaded, rate-limited or unavailable. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model for semantic retrieval. |
| `GEMINI_EMBEDDING_DIM` | `768` | Embedding size (128–3072). |
| `GEMINI_TIMEOUT_S` | `30` | Per-request timeout (each call also has an overall deadline of 2.5× this). |
| `GEMINI_MAX_RETRIES` | `2` | Retries per model for transient errors (0–4). |
| `GEMINI_DAILY_REQUEST_LIMIT` | `400` | Soft cap on Gemini requests per server process per day (`0` = no cap). |

Generation models are taken **only** from `GEMINI_MODEL` and `GEMINI_FALLBACK_MODEL`, never guessed from the
model list. A model being listed doesn't prove your key can use it: `gemini-2.5-flash` is listed but returns
404 "no longer available to new users". A model that returns 404 at call time is benched for an hour.

### Configured models (verified 2026-11-17 with a real key)

Each listed Flash model got a minimal request: 512-token budget, `thinking_level="low"` where supported, no
automatic retries. A model only counted if it returned **non-empty text** with `finish_reason=STOP`, plus
valid structured JSON.

| Model | Result | Latency |
|---|---|---|
| **gemini-3.1-flash-lite** (primary) | ✓ text + ✓ JSON | ~3–8 s |
| **gemini-3.6-flash** (fallback) | ✓ text + ✓ JSON | ~22–37 s |
| gemini-3.8-flash, gemini-3.7-flash | 503 high demand | — |
| gemini-3.5-flash | 504 deadline exceeded | — |
| gemini-3.5-flash-lite | text ✓, JSON 503 (flaky) | — |
| gemini-2.5-flash | 404 not available to new users | — |

Availability changes often. Re-run `python -m scripts.gemini_smoke` before switching models.
Thinking tokens count against the output budget (gemini-3.6-flash used ~300 for a one-sentence answer), so
IntelliDoc adds headroom whenever thinking is enabled.

## Privacy & cloud processing — please read

- **Without a Gemini key**, all processing happens on the machine running the backend. Nothing is sent anywhere.
- **With a Gemini key**, IntelliDoc sends data to **Google's Gemini API**:
  - extracted text passages from your PDF (chunks for embedding; short candidate passages for reranking and
    summaries; up to six evidence passages per follow-up question),
  - your role, expertise level, objective, focus terms and follow-up questions,
  - a short recent conversation history (up to 4 turns) with each follow-up question.

  The PDF file itself is never uploaded, but **its content is**. Google's handling of that data is governed by
  Google's terms. On the **free tier, Google may use submitted content to improve its products**. Don't use
  cloud-enabled mode for confidential documents unless your agreement with Google permits it.
- The interface deliberately doesn't show which engine processed a request. The "How it works" dialog says
  passages *may* be sent to an external AI service, depending on configuration. If you deploy IntelliDoc for
  others, tell your users whether Gemini is enabled.
- IntelliDoc itself never writes PDFs, text, embeddings or conversations to disk. Analyses live in memory in a
  bounded session store (≤12 sessions, expired after 45 minutes idle), and embeddings in a bounded in-memory cache
  (≤6,000 vectors, 1 hour). Restarting the server clears everything.
- The API key is read only from `backend/.env` or the environment. It is never sent to the browser, never
  included in API responses, and never logged.

## Free tier & cost

- IntelliDoc never enables billing. If your Google project has billing enabled, requests may be charged.
  That is controlled in your Google account, not by IntelliDoc.
- **Per analysis:** 1–6 embedding requests (≤100 passages per batch; very long documents embed at most 500
  passages, chosen by local relevance) and **at most 2 generation requests**: one lean rerank of ~24 candidates
  and one call that writes all summaries and insights together.
- **Per follow-up question:** 1 embedding request plus 1 generation request.
- **Caching:** passage embeddings are cached in memory, so refining your objective or asking follow-ups doesn't
  re-embed the document.
- **Errors:** see *What happens during an API outage* below. Retries are bounded, and a failing model
  is paused, so an outage never turns into a burst of calls.
- Free-tier quotas, available models and data-use terms are set by Google and **change over time**. Check
  Google AI Studio for your current limits.

## How it works

1. **Read.** PyMuPDF extracts text page by page. Headers, footers, page numbers and diagram labels are separated
   from prose, and scanned pages are flagged.
2. **Structure.** Sections come from PDF bookmarks, or from typography when there are none. Long sections become
   overlapping ~600-word passages, and every character keeps its page number.
3. **Retrieve (hybrid).** Every passage gets local signals: keyword coverage, content type, expertise fit,
   structure, and a TF-IDF similarity. With Gemini, **meaning similarity** comes from embeddings of the passage
   versus your objective, persona and focus terms. In that mode TF-IDF is used only for recall, so similarity
   isn't counted twice.
4. **Rerank.** The ~24 strongest section candidates are judged by the reasoning model for genuine usefulness
   (0–3). This becomes the **contextual relevance** signal. Sections judged "not relevant" are dropped.
5. **Explain.** For the final ≤10 results, the model writes why each matters, a summary, findings, takeaways and
   limitations, plus 3–5 cross-section insights, using **only the supplied passages**.
6. **Ask.** Follow-up questions retrieve fresh evidence (embeddings + TF-IDF + keywords, plus "section 4.2"
   references), and the answer must cite it.

### Scoring

| Signal | Hybrid weight | Built-in weight |
|---|---:|---:|
| Meaning similarity (embeddings / TF-IDF) | 35% | 35% |
| Keyword coverage | 20% | 25% |
| Content type (only when you ask for tables/code/figures) | 15% | 20% |
| Expertise fit | 10% | 15% |
| Structure | 5% | 5% |
| Contextual relevance (reranker) | 15% | — |

Signals are normalized to 0–1. Inactive signals have their weight redistributed. Topical signals (meaning,
keywords, contextual relevance) gate the others, so structure, expertise or content type can re-order relevant
sections but never promote an off-topic one. Embedding similarity is normalized against the document's own
baseline, so a query that matches nothing still returns nothing. The **match score is a relative ranking signal**,
not a probability or a measure of factual confidence.

### Grounding safeguards

- **Verbatim excerpts.** Quoted excerpts always come from PDF extraction, never from a model, and are located and
  highlighted on the page with PyMuPDF.
- **Validated IDs.** Every model response is JSON-schema constrained. Candidate, result and evidence IDs are
  validated, and anything unknown is discarded.
- **Sentence-level checks.** A sentence is removed if it cites numbers that aren't in the supplied passages,
  pages outside them, unseen section numbers, or a "quotation" that isn't verbatim.
- **Citations.** Insights must cite real results, and their page numbers come from IntelliDoc's data, not the
  model. An answer that claims support but cites nothing is replaced with "I couldn't find anything in this
  document that answers that."

These checks are conservative filters, not proof of correctness. Always verify against the cited source.

### What happens during an API outage

A response counts as a success only if it contains **non-empty visible text** (thinking parts are ignored) and
wasn't cut off. An empty or `MAX_TOKENS` response gets one retry with a doubled budget. If it still fails, it's
treated as a failure: never shown, never "fixed up".

| Error | Behavior |
|---|---|
| `500` / `503` / `504`, timeouts, connection errors | Up to `GEMINI_MAX_RETRIES` retries with exponential backoff (1 s, 2 s, … ≤ 8 s) plus jitter, within an overall deadline. Then that model is paused for 60 s and the fallback model is tried once. |
| `429` with a short server-suggested wait (≤ 6 s, via `RetryInfo` or `Retry-After`) | Waits as instructed, then retries. |
| `429` with a longer wait | No retry. The model is paused for the suggested time (default 60 s); the fallback model is tried. |
| `404` model unavailable | The model is benched for 1 hour; the fallback is used. |
| `401` / `403` auth | Generation (or embeddings) paused for 10 minutes; check `GEMINI_API_KEY`. |
| `400` bad request, safety block | Not retried, no fallback model; the built-in path answers. |
| Both models unavailable | Requests skip Gemini instantly (no calls) until a cooldown expires; the built-in engine answers. |

**Embeddings and generation have separate health.** In the live test, generation hit a 503 while embeddings
kept working, so semantic retrieval stays on even when text generation is down.

### Automatic fallback

| Situation | Behavior |
|---|---|
| No key / disabled | Built-in engine: TF-IDF retrieval, local ranking, template explanations, extractive answers |
| Embeddings fail | TF-IDF similarity; reranking and summaries still used if available |
| Primary generation model fails | Fallback model (if configured), then the rows below |
| Rerank fails or is invalid | Semantic retrieval kept; contextual weight redistributed |
| Summaries fail | Template explanations and verbatim key passages |
| Chat generation fails | Extractive answer quoting the best passages, with citations |

Fallback is silent in the UI and logged in the server terminal (e.g. `path=full`, `path=local`,
`transient failure … retry 1/2`, `fallback model … succeeded`).

**Typical timings with Gemini (live test):** full analysis ~20 s for 15–32-page PDFs (embeddings ~1 s, rerank
~5–8 s, summaries ~7–11 s), and a follow-up answer ~4–6 s. The built-in engine alone takes ~2–3 s.

## API

- `GET /api/health`: `{status, version, max_file_mb}` (deliberately provider-neutral).
- `POST /api/analyze`: multipart `file`, `persona`, `expertise`, `objective`, `focus_terms`. Returns NDJSON
  `stage` events, then `result`. The result includes a `session_id`, and per result adds `summary`, `findings`,
  `takeaways` and `limitations`. Insights include `result_ids`. All fields from 1.0 are preserved.
- `POST /api/session/{session_id}/ask`: `{"question": "..."}` → `{answer, supported, citations[]}`. Answers
  contain `[n]` markers matching citations (`title`, `breadcrumb`, `page_start`, `page_end`, verbatim
  `excerpt`, `excerpt_page`, `result_id`). Returns `404 session_expired` after expiry.

Schemas: `backend/app/schemas.py` and http://127.0.0.1:8000/docs.

## Tests & checks

```bash
cd backend && .venv/bin/python -m pytest      # 79 tests; Gemini is always mocked, no quota used
cd frontend && npm run build && npx oxlint src  # type-check, production build, lint
```

## Project layout

```
backend/app/
  main.py, pipeline.py, schemas.py, session.py   API, orchestration, contract, in-memory sessions
  pdf_extract.py, sections.py                    extraction, structure, chunking with page mapping
  ranking.py, explain.py                         local signals/scoring, excerpts, highlights, local insights
  retrieval/semantic.py, retrieval/hybrid.py     embedding similarity, hybrid ranking + fallback paths
  gemini/config.py, client.py                    settings; resilient client (text extraction, retries/backoff,
                                                 per-model cooldown, fallback model, budget)
  gemini/embeddings.py                           batching + in-memory cache
  gemini/reranker.py, summarizer.py, insights.py reasoning, grounded summaries, validated insights
  gemini/chat.py, grounding.py                   Ask IntelliDoc, sentence-level grounding guards
backend/scripts/gemini_smoke.py                  live configuration check
frontend/src/components/AskPanel.tsx             Ask IntelliDoc drawer with citations
```

## Known limitations

- No OCR: scanned pages are detected and reported, not read.
- Hybrid scoring was checked live on two PDFs. Real embeddings separate relevant from unrelated text by about
  0.2 cosine, consistent with `SPREAD_FLOOR=0.10`, but broader tuning across document types is still to do.
- Gemini models are frequently overloaded on the free tier. If both configured models are down, results are
  still produced, but without AI summaries.
- Grounding guards catch fabricated numbers, pages, sections and quotes, but not every paraphrase error.
- Without Gemini, matching is lexical and follow-up answers are extractive quotes rather than explanations.
- The daily request budget is per server process and resets on restart. Google's own quota is authoritative.
- Sessions are in memory, so a server restart ends them. The UI then asks you to re-run the analysis.
