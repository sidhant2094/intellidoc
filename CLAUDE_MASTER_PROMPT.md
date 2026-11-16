# IntelliDoc — Claude Code Master Build Prompt

> **How to use:** Put this file and `INTELLIDOC_BUILD_SPEC.md` in the root of your empty IntelliDoc project folder. Open that folder in Claude Code and paste the entire contents of this file as your first message. Then let Claude work through the project, approving tool permissions as needed.

---

You are the **principal product engineer, senior frontend designer, and pragmatic technical lead** for IntelliDoc. Your job is to turn an empty folder into a polished, genuinely working, local-first product demo that can be shown tomorrow.

Do not merely advise me, generate snippets, or create a plan and stop. **Build the application in the current working directory, run it, test it, fix it, and leave it ready for me to use.**

## 0. First: understand the project

1. Inspect the current working directory and available runtime/tool versions.
2. Read `INTELLIDOC_BUILD_SPEC.md` completely before making architectural decisions.
3. Treat that specification as the product source of truth. This prompt adds execution priorities and working behavior; it does not replace the specification.
4. If the specification is missing, stop and ask me to add it. Do not invent a substitute.
5. If the directory contains existing work, inspect and preserve it. Never overwrite files blindly.
6. Create `IMPLEMENTATION_PLAN.md` with a short, practical checklist and update it as work is completed.

The original IntelliDoc concept is a **Persona-Aware Document Intelligence System**. Its central promise is to understand the document, understand the user's persona and objective, and connect the two to surface ranked, context-preserving sections.

## 1. Product outcome

Build a product-quality experience around this workflow:

1. User describes their **persona / role**.
2. User selects their **expertise level**.
3. User describes their **specific objective** — what they need to find in the document.
4. User uploads a PDF.
5. IntelliDoc extracts and structures the PDF.
6. IntelliDoc ranks the sections and subsections most useful to that persona and objective.
7. User receives **up to 10** useful results, with fewer results when fewer genuinely relevant sections exist.

This is not intended to be a generic PDF chatbot. The product is a personalized document discovery and reading-path tool.

## 2. Hard constraints

- The app must work locally.
- The core experience must cost **$0** to run.
- No sign-in, authentication, payments, user accounts, database, or cloud deployment.
- No paid API and no API key may be required for the core workflow.
- Do not make Gemini, OpenAI, or any other external LLM a hard dependency.
- Do not fake AI, results, citations, page numbers, source excerpts, progress, or model usage.
- Use a real uploaded PDF for the core workflow. Never silently substitute mock data.
- Both light and dark themes are mandatory.
- Prioritize a complete end-to-end workflow over optional sophistication.
- Keep dependencies and setup simple.
- Do not stop after scaffolding. Run and test the product.

## 3. Technical direction

Use the stack in `INTELLIDOC_BUILD_SPEC.md`. The intended baseline is:

### Frontend
- React + Vite + TypeScript.
- Tailwind CSS.
- shadcn/ui or similarly accessible components if setup is quick and stable.
- lucide-react icons.
- Responsive desktop-first layout.

### Backend
- Python + FastAPI.
- PyMuPDF for PDF extraction.
- scikit-learn TF-IDF and cosine similarity for a free local retrieval baseline.
- Lightweight keyword overlap and transparent structural/persona signals.
- No database; process in memory and use temporary files safely.

### Optional upgrades
Only consider local embeddings, Tesseract OCR, or Gemini after the basic end-to-end flow works and has been tested. Optional features must never break the baseline.

If a dependency is unavailable or slow to install, choose the simplest reliable alternative and document the tradeoff. Do not spend the day wrestling with an optional dependency.

## 4. Design direction — this matters

The frontend is a major part of the product. It should feel like a premium, carefully designed Apple-inspired application: quiet confidence, excellent typography, clarity, whitespace, and precise interactions.

Do:
- Establish a strong typographic hierarchy.
- Use a restrained neutral palette with one confident accent color.
- Use generous but disciplined spacing.
- Use subtle borders, soft surfaces, restrained shadows, and consistent radii.
- Make buttons, chips, upload states, cards, navigation, and empty states feel cohesive.
- Use smooth, restrained transitions where they improve feedback.
- Make loading, error, success, hover, focus, and disabled states intentional.
- Ensure both themes are genuinely designed, not just background-inverted.
- Use semantic HTML, keyboard navigation, visible focus indicators, and accessible labels.

Avoid:
- Generic admin-dashboard aesthetics.
- Excessive gradients, glassmorphism, neon, giant decorative illustrations, or gratuitous animation.
- Overcrowded cards and tiny text.
- Emoji as a substitute for a considered icon system.
- Fake charts or decorative metrics.
- Copying Apple's website, logos, or proprietary assets.

### Theme behavior
- Visible light/dark toggle in the top navigation.
- On first visit, respect the operating system preference.
- Once the user selects a theme, persist the preference in localStorage.
- Apply theme consistently to every screen, control, dropdown, upload state, result card, and modal.
- Avoid a flash of the wrong theme on page load if practical.

## 5. Required user experience

### A. Workspace / setup screen

Create a polished first screen with:
- IntelliDoc identity and a concise product tagline.
- Top navigation with a working light/dark toggle.
- A clear setup flow, not a wall of generic form fields.
- Persona / role input, with useful presets such as Student, Researcher, Software Engineer, Product Manager, Business Analyst, and Other. The user must be able to edit the role.
- Expertise selector: Beginner, Intermediate, Advanced.
- A prominent objective textarea with a concrete example placeholder.
- Optional focus terms / keywords.
- Elegant PDF drag-and-drop zone and browse action.
- After upload, show filename, file size, page count if known, and remove/replace action.
- A clear primary action such as **Find relevant sections**.
- Disable analysis until required inputs and a valid PDF are present.
- Keep the interface focused and premium.

### B. Analysis experience

Show real, meaningful analysis stages:
1. Reading your document.
2. Reconstructing document sections.
3. Matching your objective.
4. Ranking relevant sections.

Use actual backend progress or stage responses if practical. If true progress reporting is not implemented, show honest stage/status feedback without fabricated percentages or timers.

Handle errors with clear, actionable messages. Do not leave the user staring at a spinner.

### C. Results experience

After successful analysis, display:
- Document name and document statistics.
- Active persona, expertise, and objective in a compact context summary.
- Up to 10 ranked results.
- A clear action to start a new analysis.

Each result should include:
- Rank.
- Section title and breadcrumb / hierarchy where available.
- Exact 1-indexed source page or page range.
- Relative match score with a clear label.
- A short **Why this is relevant** explanation tied to the user's objective.
- A verbatim source excerpt.
- A concise source-grounded summary.
- Content-type tags only when actually detected.
- Expand/collapse for additional context.
- A clear way to navigate between results.

Include a small “Document overview” or “Analysis details” area with useful facts such as pages processed, sections found, and extraction warnings. Do not invent metrics.

If practical within the schedule, embed the PDF viewer and jump to the relevant page. If not, provide accurate page references and a dependable way to open the original PDF. Do not let an embedded viewer delay the core workflow.

If no useful results pass the threshold:
- Say no sufficiently relevant sections were found.
- Suggest improving or narrowing the objective.
- Do not pad the list with irrelevant content.

## 6. Backend and retrieval requirements

Implement the real pipeline:

1. Validate the uploaded file as a PDF.
2. Enforce a reasonable file-size limit (30 MB is the suggested MVP limit).
3. Open and extract text page-by-page with PyMuPDF.
4. Preserve exact 1-indexed page mapping throughout the pipeline.
5. Detect pages with little or no extractable text.
6. Return clear warnings for likely scanned pages and OCR limitations.
7. Detect likely headings using typography, font size/boldness where available, numbering patterns, and simple line heuristics.
8. Reconstruct a best-effort section hierarchy. Be honest that heuristic reconstruction is approximate.
9. Split very long sections into overlapping chunks.
10. Preserve source section, heading hierarchy, and page range for every chunk.
11. Rank chunks against the user's objective and persona.
12. Aggregate adjacent chunks into coherent section-level results.
13. Deduplicate overlapping or near-identical results.
14. Return up to 10 results, using a sensible minimum relevance threshold.
15. Ensure every result's page references and excerpts are traceable to extracted source text.
16. Delete temporary files after processing, including on errors.

Use the original specification's weighted ranking approach as the starting point:

- Semantic similarity: 35%.
- Keyword overlap: 25%.
- Content-type match: 20%.
- Expertise alignment: 15%.
- Structural importance: 5%.

Normalize signals before combining them. If a signal is only approximated, document the proxy. Do not claim the resulting score is a probability, factual confidence, or calibrated AI score. Label it as a relative match score.

For the baseline, TF-IDF cosine similarity is an acceptable local semantic-similarity proxy. Keyword overlap should be implemented as a distinct signal without blindly double-counting the same signal. Content-type boosts should only apply when the objective makes those types relevant. Expertise alignment must be explainable and conservative.

Prefer coherent sections and passages over isolated sentences. Avoid returning ten results simply to fill space.

### API

At minimum:
- `GET /api/health`
- `POST /api/analyze` using multipart form data.

Keep the request/response schema typed and predictable. Return document metadata, analysis metadata, results, and warnings. Configure CORS for the local frontend origin.

A single analysis endpoint returning the complete result set is fine for this MVP. Do not build session persistence unless it is genuinely needed.

## 7. Error states to handle

At minimum:
- No file selected.
- Invalid file type.
- Malformed PDF.
- Password-protected PDF.
- File too large.
- PDF with no extractable text.
- Likely scanned PDF / OCR unavailable.
- Backend offline.
- Analysis error.
- No relevant sections found.
- Partial extraction with warnings.

Make errors understandable to a non-technical user. Log useful diagnostic details in the terminal without exposing stack traces in the UI.

## 8. Build sequence — work in this order

### Milestone 1: Inspect and plan
- Inspect folder and installed tools.
- Read the spec.
- Create `IMPLEMENTATION_PLAN.md`.
- Decide a simple folder structure.
- Tell me the chosen structure and then continue.

### Milestone 2: Backend baseline
- Set up FastAPI and dependencies.
- Implement PDF validation and extraction.
- Implement page-aware section/chunk representation.
- Implement ranking and result aggregation.
- Add tests for extraction, page mapping, ranking, and no-match behavior.
- Test with a real PDF if one is available in the project folder. If none is present, create a clear manual test instruction and ask me to supply a PDF only when necessary.

### Milestone 3: Frontend foundation
- Set up React/Vite/TypeScript and Tailwind.
- Implement the design system and responsive shell.
- Implement the workspace form and file upload.
- Implement the light/dark theme properly.

### Milestone 4: Connect the workflow
- Connect the UI to the real API.
- Implement validation, loading, errors, and results.
- Confirm that actual results from a real PDF render correctly.

### Milestone 5: Product polish
- Improve typography, spacing, alignment, hierarchy, and interactions.
- Test both themes and responsive layouts.
- Add PDF navigation if time permits.
- Add useful empty states and warnings.

### Milestone 6: Final verification
- Run backend tests.
- Run frontend build/type checks.
- Start both services and exercise the complete user journey.
- Fix all blocking errors.
- Verify no API key is needed.
- Verify light/dark mode persistence.
- Verify page numbers and excerpts against the PDF.
- Write a concise `README.md` with exact setup and run commands.
- Update `IMPLEMENTATION_PLAN.md` and report what is complete and what remains.

## 9. Engineering discipline

- Keep modules small and responsibilities clear.
- Avoid premature abstractions and unnecessary architecture.
- Use environment variables only where useful; include `.env.example` if needed.
- Add `.gitignore` for virtual environments, node_modules, caches, temporary uploads, and secrets.
- Never put secrets in source control.
- Keep frontend and backend commands simple.
- Prefer a root-level README with exact commands.
- Do not add Docker unless it materially simplifies this local build.
- Do not add a database.
- Do not create a fake demo result to make the UI look populated.
- Do not claim OCR is supported unless it actually runs.
- Do not claim Gemini or another LLM was used unless it actually was.

## 10. Time management and decision-making

We have a very short deadline. Make pragmatic decisions.

Priority order:
1. Real PDF upload and extraction.
2. Useful persona-aware ranking.
3. Accurate page references and source excerpts.
4. Beautiful, responsive frontend.
5. Working light/dark mode.
6. Robust errors and tests.
7. Optional semantic embeddings, OCR, Gemini, and PDF viewer.

If time becomes tight, cut optional features, not the working core workflow.

Do not ask me to approve routine decisions. Choose sensible defaults and keep moving. Ask only when blocked by a genuinely necessary choice, missing credential that is truly required, or missing source file.

When you finish a milestone, give me a short update with:
- What you built.
- What you tested.
- Any issue that blocks the next milestone.

Then continue automatically unless you need my input.

## 11. Definition of done

The project is ready when I can:

- Run the documented local commands.
- Open IntelliDoc in my browser.
- Switch between light and dark mode and see the choice persist.
- Enter persona, expertise, and objective.
- Upload a real PDF.
- Run analysis without signing in, paying, or entering an API key.
- Receive up to 10 useful, ranked sections.
- See accurate page references and exact source excerpts.
- Understand why each result is relevant.
- Expand additional context and navigate results.
- Get clear warnings or errors when a PDF cannot be processed.

## 12. Start now

Read `INTELLIDOC_BUILD_SPEC.md` first. Inspect the folder. Create the implementation plan. Then start building the actual product.

**Do not stop at a plan. Do not stop at scaffolding. Do not give me a tutorial instead of implementing. Ship the working IntelliDoc MVP.**
