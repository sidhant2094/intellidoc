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
cd backend && .venv/bin/python -m scripts.gemini_smoke   # ~4 small requests: validates key + models
```

Restart `./start.sh` after changing `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Your key from Google AI Studio. Empty → built-in engine only. |
| `GEMINI_ENABLED` | `true` | Set `false` to force the built-in engine even with a key. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Reasoning model (reranking, summaries, insights, answers). |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model for semantic retrieval. |
| `GEMINI_EMBEDDING_DIM` | `768` | Embedding size (128–3072). |
| `GEMINI_TIMEOUT_S` | `30` | Default per-request timeout. |
| `GEMINI_DAILY_REQUEST_LIMIT` | `400` | Soft cap on Gemini requests per server process per day (`0` = no cap). |

Model names are **validated against the live API** (`models.list`) rather than assumed. If a configured model isn't
available to your key, IntelliDoc logs a warning and substitutes the newest available stable Flash model (or
`gemini-embedding-001` for embeddings). If none is usable, that feature falls back to the built-in engine.

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
- **Rate limits:** a `429` is **never retried**. Gemini pauses for the server-suggested delay and IntelliDoc
  uses its built-in engine meanwhile. Timeouts and 5xx errors get one retry. Auth errors pause Gemini for
  10 minutes.
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

### Automatic fallback

| Situation | Behavior |
|---|---|
| No key / disabled | Built-in engine: TF-IDF retrieval, local ranking, template explanations, extractive answers |
| Embeddings fail | TF-IDF similarity; reranking and summaries still used if available |
| Rerank fails or is invalid | Semantic retrieval kept; contextual weight redistributed |
| Summaries fail | Template explanations and verbatim key passages |
| Chat generation fails | Extractive answer quoting the best passages, with citations |
| Rate limit / quota | Gemini paused for the suggested delay; built-in engine meanwhile |

Fallback is silent in the UI and logged in the server terminal (e.g. `path=full`, `path=local`).

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
cd backend && .venv/bin/python -m pytest      # 58 tests; Gemini is always mocked, no quota used
cd frontend && npm run build && npx oxlint src  # type-check, production build, lint
```

## Project layout

```
backend/app/
  main.py, pipeline.py, schemas.py, session.py   API, orchestration, contract, in-memory sessions
  pdf_extract.py, sections.py                    extraction, structure, chunking with page mapping
  ranking.py, explain.py                         local signals/scoring, excerpts, highlights, local insights
  retrieval/semantic.py, retrieval/hybrid.py     embedding similarity, hybrid ranking + fallback paths
  gemini/config.py, client.py                    settings, resilient client (model validation, breaker, budget)
  gemini/embeddings.py                           batching + in-memory cache
  gemini/reranker.py, summarizer.py, insights.py reasoning, grounded summaries, validated insights
  gemini/chat.py, grounding.py                   Ask IntelliDoc, sentence-level grounding guards
backend/scripts/gemini_smoke.py                  live configuration check
frontend/src/components/AskPanel.tsx             Ask IntelliDoc drawer with citations
```

## Known limitations

- No OCR: scanned pages are detected and reported, not read.
- Hybrid-mode score calibration (embedding normalization, reranker mapping) was developed against mocked
  responses. Expect to tune `SPREAD_FLOOR` in `retrieval/semantic.py` after trying real documents.
- Grounding guards catch fabricated numbers, pages, sections and quotes, but not every paraphrase error.
- Without Gemini, matching is lexical and follow-up answers are extractive quotes rather than explanations.
- The daily request budget is per server process and resets on restart. Google's own quota is authoritative.
- Sessions are in memory, so a server restart ends them. The UI then asks you to re-run the analysis.
