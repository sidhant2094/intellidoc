# IntelliDoc — Product & Build Specification

**Version:** 1.0  
**Build target:** A polished, working local demo in one day  
**Product line:** *Find what matters. Skip what doesn't.*

## 1. Product direction

IntelliDoc is a persona-aware PDF intelligence workspace. A user uploads a long PDF, tells IntelliDoc who they are and what they need, and receives a ranked reading list of the most useful sections and subsections—with page references, concise explanations, and enough surrounding context to verify each result.

This is not a generic PDF chatbot. The core promise is:

> Turn a long document into a personalized, evidence-backed reading path.

The original project concept is retained: understand the document, understand the user's persona and objective, then connect the two using multi-factor relevance scoring and preserve document context.

## 2. One-day MVP: what must work

### Primary workflow

1. **Create a reading profile**
   - Persona / role: free-text field plus suggested presets (Student, Researcher, Software Engineer, Product Manager, Business Analyst, Lawyer, Other).
   - Expertise: Beginner, Intermediate, Advanced.
   - Objective: a prominent, multi-line prompt: “What are you trying to find?”
   - Optional focus areas / keywords.
   - Persona and objective are both editable before analysis.

2. **Upload a PDF**
   - Drag-and-drop upload.
   - Show filename, file size, page count when available, and a clear remove/replace action.
   - Accept digital PDFs. Detect low-text/scanned PDFs and explain OCR status rather than silently returning empty results.
   - MVP size guardrail: 30 MB; show a useful message if exceeded.

3. **Analyze**
   - A clear primary CTA: “Find relevant sections”.
   - Show meaningful progress stages: Reading document → Reconstructing sections → Matching your objective → Ranking results.
   - Do not fake progress percentages. Use actual stage updates.

4. **Review ranked results**
   - Return **up to 10** results, not necessarily exactly 10. Return fewer when fewer sections pass a minimum relevance threshold.
   - Each result includes:
     - Rank
     - Section heading / breadcrumb
     - Page range (1-indexed, inclusive)
     - Relevance score (label or percentage, consistently defined)
     - “Why this matters” explanation tied to the user's objective
     - A short, verbatim evidence excerpt from the PDF
     - A concise AI-generated or extractive summary (must not invent facts)
     - Content type tags where detected: prose, table, code, figure/caption
     - Expand/collapse for additional context
     - “Open page” / “View in document” action
   - Provide a “Top insights” strip with 2–3 cross-section themes only if supported by the retrieved passages.
   - Provide a compact analysis summary: pages scanned, sections found, time taken.

5. **Inspect source**
   - Include an embedded PDF viewer if feasible within the day. Otherwise provide a reliable “Open original PDF” action and page references.
   - Never fabricate page numbers or quotations.
   - A result must be traceable to its source page(s).

### Important product behavior

- A persona alone is not enough: the objective must drive retrieval.
- Do not assume the user wants a summary of the whole PDF.
- Do not force exactly 10 results.
- Avoid duplicate or near-duplicate results from adjacent chunks.
- Preserve section hierarchy and surrounding context.
- Be transparent when a PDF is scanned, encrypted, malformed, or has little extractable text.
- If extraction fails, show a helpful error and a next step; never show fake results.

## 3. Visual design direction

### Design language

Use an Apple-inspired visual language: calm, premium, restrained, precise, and spacious. Do not copy Apple's website or use Apple logos.

- Strong typography and hierarchy.
- Generous whitespace and carefully controlled content width.
- Soft neutral surfaces, subtle borders, restrained shadows, rounded corners.
- One restrained accent color (indigo / blue-violet or electric blue).
- Smooth but subtle transitions; no excessive gradients, glassmorphism, or decorative animation.
- Results should feel like a premium research product, not an admin dashboard.
- Desktop-first responsive layout; still usable on tablet and mobile.

### Theme support

- Light and dark modes are both required.
- Put a visible theme toggle in the top navigation.
- Persist the user's theme choice locally in the browser.
- Respect system preference on first visit.
- Check contrast and readability in both themes.
- Theme toggle must work across every screen and component.

### Suggested layout

**Landing / workspace**
- Top navigation: IntelliDoc wordmark, “How it works” / small status, theme toggle.
- Left/main column: persona and objective setup.
- Right column or lower panel: PDF upload dropzone.
- Before upload: polished empty state with a short product promise and sample persona chips.
- After upload: compact file card with status and Analyze CTA.

**Results**
- Header: document name, persona chip, objective summary, “New analysis”.
- Left rail: result list / ranked navigation.
- Main area: selected result detail with breadcrumb, pages, relevance, explanation, excerpt, and context.
- Optional right rail: top insights / document stats.
- On smaller screens, collapse rails into stacked sections.

## 4. Recommended implementation stack

### Use this stack for the one-day build

- **Frontend:** React + Vite + TypeScript.
- **Styling:** Tailwind CSS; use shadcn/ui or similarly restrained accessible primitives.
- **Icons:** lucide-react.
- **Backend:** Python + FastAPI.
- **PDF extraction:** PyMuPDF (`fitz`).
- **Ranking baseline:** scikit-learn TF-IDF cosine similarity + keyword overlap + structural importance.
- **Optional semantic upgrade:** `sentence-transformers` with `all-MiniLM-L6-v2`, loaded locally. Treat this as optional because first-time model download and CPU inference may take time.
- **OCR:** optional Tesseract integration if installed. Do not make OCR a hard dependency for the MVP.
- **Storage:** in-memory processing and temporary files; no database required.
- **Run locally:** frontend and backend on localhost.

### Why not Streamlit as the main UI?

Streamlit is excellent for a fast prototype, but this product's differentiator is a premium, interactive frontend with a custom workspace, result navigation, and persistent theme switching. React gives much more control and still fits a one-day local MVP. If time collapses, a Streamlit fallback is acceptable—but do not build both.

### Free-first AI strategy

The app must work without a paid API and without an API key.

**Default path (must work):**
- Extract text and page metadata with PyMuPDF.
- Reconstruct sections using heading heuristics and page/typography signals where possible.
- Split oversized sections into overlapping chunks while retaining section title, page range, and source text.
- Rank locally using TF-IDF cosine similarity, keyword overlap, and structural importance.
- Generate concise “why relevant” explanations from deterministic templates and the user's objective. Do not pretend this is an LLM explanation.
- Produce extractive summaries / excerpts from source text.

**Optional enhancement (only if time permits):**
- Add an LLM provider adapter for Gemini.
- Gemini must be opt-in, not required for the app to work. The user supplies their own API key through a local `.env` file.
- Keep prompts grounded: model receives only retrieved passages and must cite the supplied page numbers.
- If the API key is missing, rate-limited, or the request fails, gracefully fall back to local results.
- Never hard-code API keys or commit `.env`.
- Before using any provider, verify its current free-tier availability and limits; do not advertise “unlimited free AI”.

## 5. Retrieval and ranking design

### Document processing

1. Validate PDF and enforce file-size/page guardrails.
2. Extract text page-by-page using PyMuPDF.
3. Record page number, text blocks, and basic layout metadata.
4. Detect scanned/low-text pages. For MVP, report them and optionally OCR if Tesseract is available.
5. Detect likely headings using font size/boldness, numbering patterns, short-line heuristics, and whitespace.
6. Build a section tree with parent heading, child heading, page start, page end, and text.
7. Split long sections into chunks (target roughly 700–1,000 tokens/words depending on implementation; overlap 100–150 words). Keep source mapping for every chunk.

### Ranking

Use a transparent weighted score. Start with the original IntelliDoc weights:

| Signal | Weight | Implementation |
|---|---:|---|
| Semantic similarity | 35% | TF-IDF cosine baseline; optional local embeddings |
| Keyword overlap | 25% | normalized overlap between objective terms and section terms |
| Content-type match | 20% | boost detected tables/code/figures only when relevant to the request |
| Expertise alignment | 15% | match persona expertise and role to section complexity/domain cues |
| Structural importance | 5% | heading hierarchy, section depth, and document structure |

**Important:** If a signal cannot be reliably measured in the MVP, use a clearly documented proxy and do not imply the score is scientifically calibrated. Normalize each signal to 0–1 before combining. Expose a readable relevance label; if displaying a percentage, label it “match score” and explain that it is a relative ranking signal, not probability or factual confidence.

### Result selection

- Rank chunks, then aggregate adjacent/highly overlapping chunks into section-level results.
- Deduplicate results from the same section.
- Prefer coherent passages over isolated sentence fragments.
- Return up to 10 results.
- Use a minimum threshold so weak matches are omitted.
- Preserve exact page references and source excerpts.
- Store a stable result ID and source mapping for frontend navigation.

## 6. API contract

Suggested endpoints:

- `GET /api/health` — service health.
- `POST /api/analyze` — multipart PDF + persona + expertise + objective + optional focus terms.
- `GET /api/session/{session_id}/document` — document metadata if session persistence is implemented.
- `GET /api/session/{session_id}/result/{result_id}` — optional result detail.

For the one-day MVP, a single `POST /api/analyze` returning all results is acceptable. Keep response schema typed and documented.

Suggested response shape:

```json
{
  "document": {
    "filename": "example.pdf",
    "page_count": 120,
    "pages_with_text": 118,
    "scanned_pages": [12, 13],
    "section_count": 34
  },
  "analysis": {
    "persona": "Software Engineer",
    "expertise": "Intermediate",
    "objective": "Find API design and deployment constraints",
    "duration_ms": 1840
  },
  "results": [
    {
      "id": "result-1",
      "rank": 1,
      "title": "Deployment Architecture",
      "breadcrumb": ["System Design", "Deployment Architecture"],
      "page_start": 42,
      "page_end": 46,
      "match_score": 0.87,
      "relevance_label": "Very relevant",
      "why_relevant": "This section discusses deployment choices and operational constraints related to your objective.",
      "summary": "A concise source-grounded summary.",
      "excerpt": "Exact text copied from the source...",
      "content_types": ["prose", "code"],
      "context": "Additional surrounding source text..."
    }
  ],
  "warnings": []
}
```

This is a contract example, not a claim that every field must be implemented on day one.

## 7. Error and edge states

Design and implement:
- No PDF selected.
- Unsupported file / malformed PDF.
- Password-protected PDF.
- Oversized file.
- Scanned PDF with no OCR installed.
- PDF with no extractable text.
- Analysis still running.
- Backend unavailable.
- No relevant sections found.
- Partial OCR / extraction warning.
- Optional Gemini unavailable; local fallback used.

## 8. Scope and priorities

### P0 — Must ship tomorrow
- Premium responsive React interface.
- Light/dark theme toggle.
- Persona, expertise, and objective inputs.
- PDF upload and file status.
- Real PDF text extraction.
- Section/chunk creation with page mapping.
- Local relevance ranking.
- Up to 10 ranked, deduplicated results.
- Excerpts, page references, and “why relevant”.
- Clear errors and loading states.
- One-command documented local startup.

### P1 — Add if P0 is stable
- Embedded PDF viewer / jump to page.
- Local semantic embeddings.
- OCR via optional Tesseract.
- Export reading list as Markdown.
- Gemini enhancement behind opt-in configuration.

### Explicitly out of scope for tomorrow
- Login, accounts, payments, teams, database, cloud deployment.
- Multi-document search.
- Enterprise permissions.
- Guaranteed OCR for every scanned PDF.
- Fine-tuned models or custom training.
- Claims of production-grade security or accuracy.

## 9. Acceptance checklist

A first-time user must be able to:

- [ ] Start the app locally using documented commands.
- [ ] Switch between light and dark themes.
- [ ] Enter a persona, expertise level, and objective.
- [ ] Upload a real PDF.
- [ ] See document metadata and extraction warnings.
- [ ] Run analysis without any API key or paid service.
- [ ] Receive up to 10 meaningful, ranked sections.
- [ ] See correct page numbers and exact source excerpts.
- [ ] Understand why each result matched their objective.
- [ ] Expand context and navigate results.
- [ ] Receive a useful empty state if nothing relevant is found.
- [ ] Recover gracefully from invalid/scanned/unsupported PDFs.

## 10. Product truth

Do not call a TF-IDF score “AI confidence”. Do not fabricate summaries, citations, page numbers, OCR success, or model usage. The strongest demo is one that works reliably, explains its results, and makes the source verifiable.
