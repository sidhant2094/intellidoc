#!/usr/bin/env bash
# IntelliDoc — install (first run only) and start backend (:8000) + frontend (:5173).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY_BIN=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY_BIN="$c"; break
  fi
done

if [ ! -x backend/.venv/bin/python ]; then
  echo "→ Creating Python environment"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "${PY_BIN:-3.12}" backend/.venv -q
  else
    [ -n "$PY_BIN" ] || { echo "Python 3.10+ is required (or install uv: https://docs.astral.sh/uv/)"; exit 1; }
    "$PY_BIN" -m venv backend/.venv
    backend/.venv/bin/pip install -q --upgrade pip
  fi
fi

# (Re)install Python packages whenever the requirements change.
REQ_HASH="$(cat backend/requirements.txt backend/requirements-dev.txt | shasum | cut -d' ' -f1)"
if [ "$(cat backend/.venv/.req-hash 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "→ Installing Python packages"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python backend/.venv/bin/python -q -r backend/requirements-dev.txt
  else
    backend/.venv/bin/pip install -q -r backend/requirements-dev.txt
  fi
  echo "$REQ_HASH" > backend/.venv/.req-hash
fi

if [ ! -d frontend/node_modules ]; then
  echo "→ Installing frontend packages"
  (cd frontend && npm install --silent)
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "→ Starting engine on http://127.0.0.1:8000"
(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning) &

echo "→ Starting app on http://localhost:5173"
(cd frontend && npx vite --port 5173 --strictPort --clearScreen false) &

sleep 2
echo ""
echo "  IntelliDoc is running → http://localhost:5173   (Ctrl+C to stop)"
echo ""
wait
