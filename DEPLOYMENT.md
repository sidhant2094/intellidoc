# Deploying IntelliDoc (Render + Vercel)

- **Backend** (FastAPI): a Render **Web Service** rooted at `backend/`.
- **Frontend** (React/Vite static build): a Vercel project rooted at `frontend/`.

The browser calls the Render API directly, with CORS restricted to your Vercel domain. The Gemini key lives only
in Render's environment.

Deploy in this order: **Render first** (to get its URL), **then Vercel**, **then** set Render's `FRONTEND_URL`
to the Vercel URL.

---

## 1. Backend on Render

**New → Web Service → Connect `sidhant2094/intellidoc`.**

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Branch | `main` |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |
| Instance type | **Starter or higher recommended** (see notes) |
| Instances | **1**; do not scale horizontally (see notes) |
| Auto-Deploy | On commit (your choice) |

Python version: `backend/.python-version` pins **3.13**, which Render reads automatically. To pin a patch
release, also set `PYTHON_VERSION=3.13.5`.

### Environment variables (Render → Environment)

| Key | Value | Notes |
|---|---|---|
| `APP_ENV` | `production` | Removes the localhost CORS origins |
| `FRONTEND_URL` | `https://<your-project>.vercel.app` | Exact origin: scheme + host, no path, no trailing slash |
| `ALLOWED_ORIGINS` | *(optional)* `https://intellidoc.example.com` | Extra exact origins, comma-separated (e.g. a custom domain) |
| `CORS_ORIGIN_REGEX` | *(optional)* `^https://intellidoc-[a-z0-9-]+-sidhant2094s-projects\.vercel\.app$` | Only if Vercel **preview** deployments should reach the API; adjust to your preview URL pattern |
| `GEMINI_API_KEY` | *(your key)* | **Secret.** Set it here only, never in Vercel or the repo |
| `GEMINI_ENABLED` | `true` | `false` forces the built-in engine |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Same as local `.env` |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.6-flash` | Same as local `.env` |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | |
| `GEMINI_EMBEDDING_DIM` | `768` | optional (default) |
| `GEMINI_TIMEOUT_S` | `30` | optional (default) |
| `GEMINI_MAX_RETRIES` | `2` | optional (default) |
| `GEMINI_DAILY_REQUEST_LIMIT` | `400` | optional (default); caps Gemini calls per server process per day |

Wildcards (`*`, `.*`) are ignored for CORS by design, and credentials are never allowed.

### Check the backend

```bash
curl https://<service>.onrender.com/api/health
# {"status":"ok","version":"2.0.0","max_file_mb":30}
```

The Render logs should show `CORS origins: ['https://<your-project>.vercel.app']` and
`Gemini configured (model=gemini-3.1-flash-lite, …)`.

---

## 2. Frontend on Vercel

**Add New → Project → Import `sidhant2094/intellidoc`.**

| Setting | Value |
|---|---|
| Framework Preset | Vite |
| Root Directory | `frontend` |
| Install Command | `npm install` (default; uses `package-lock.json`) |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| Node.js Version | 22.x (`package.json` requires ≥ 22.12) |

### Environment variables (Vercel → Settings → Environment Variables)

| Key | Value | Environments |
|---|---|---|
| `VITE_API_BASE_URL` | `https://<service>.onrender.com` | Production (and Preview, if you set `CORS_ORIGIN_REGEX`) |

That's the only frontend variable, and it's public: Vite embeds `VITE_*` values in the JavaScript bundle. **Never
add `GEMINI_API_KEY` or any secret to Vercel.** Builds on Vercel fail with a clear message if
`VITE_API_BASE_URL` is missing or isn't an origin like `https://host`.

The app is a single page with no client-side routes, so no rewrites are needed.

---

## 3. Connect them

1. Copy the Vercel production URL (e.g. `https://intellidoc.vercel.app`).
2. In Render, set `FRONTEND_URL` to it (exact, no trailing slash). Render redeploys automatically.
3. Open the Vercel URL, run an analysis, and ask a question.

If the browser console shows a CORS error, the origin it reports must match `FRONTEND_URL` exactly, including
`https` and with no trailing slash.

---

## Production notes

- **Single instance and worker.** Analyses and Ask IntelliDoc sessions live in process memory (≤ 12 sessions,
  45-minute idle TTL). Multiple instances or workers would send follow-up questions to a process that doesn't
  hold the session (the UI then shows "This analysis is no longer active"). Keep 1 instance, and leave
  uvicorn's default of 1 worker.
- **Free tier.** Render's free web services spin down after ~15 minutes idle. The next visit waits about a
  minute for a cold start, and in-memory sessions are lost. The UI shows "Can't reach IntelliDoc yet — it may be
  starting up" and retries automatically. Free instances also have 512 MB RAM, which can be tight for large
  PDFs (PyMuPDF + scikit-learn + up to 30 MB uploads). Starter or above is recommended for real use.
- **Files.** IntelliDoc never writes PDFs, extracted text, embeddings or conversations to disk. PDFs are opened
  from memory. The multipart parser may spool large uploads to a temporary file during the request; it's
  closed and removed when the request ends. No persistent disk is needed or used.
- **Upload limit.** 30 MB per PDF (`backend/app/config.py`). Larger requests are rejected from their
  `Content-Length` before the body is read.
- **Streaming.** `/api/analyze` streams NDJSON progress events, and Render passes streamed responses through.
- **Privacy.** With `GEMINI_API_KEY` set, extracted passages, objectives and questions are sent to Google's
  Gemini API. See the README's privacy section and tell your users.
- **Cost exposure.** The API is public, so anyone who finds the Render URL can use it and spend your Gemini
  quota. CORS only restrains browsers. `GEMINI_DAILY_REQUEST_LIMIT` caps the damage. For a public launch,
  consider rate limiting (e.g. at a proxy) or authentication.
- **API docs.** FastAPI's `/docs` and `/openapi.json` are publicly reachable. They expose no secrets.

## Local development (unchanged)

```bash
./start.sh   # backend on 127.0.0.1:8000, frontend on http://localhost:5173 (Vite proxies /api)
```

With no `VITE_API_BASE_URL` and `APP_ENV` unset, localhost origins are allowed and the proxy is used.
