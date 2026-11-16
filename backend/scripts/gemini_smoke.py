"""Check the Gemini setup with ~4 small requests. Never prints the API key.

Usage (from backend/):  .venv/bin/python -m scripts.gemini_smoke
"""

from __future__ import annotations

import logging
import sys
import time

import numpy as np

from app.gemini.client import GeminiUnavailable, get_service

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    svc = get_service()
    if svc is None:
        print("Gemini is not active: set GEMINI_API_KEY (and GEMINI_ENABLED=true) in backend/.env.")
        print("IntelliDoc will use its built-in engine.")
        return 1
    s = svc.settings
    print(f"Configured: model={s.model}  embeddings={s.embedding_model}  dim={s.embedding_dim}")
    try:
        t = time.perf_counter()
        gen, emb = svc.resolve_model("generate"), svc.resolve_model("embed")
        print(f"✓ Models available: generate={gen}{'' if gen == s.model else '  (substituted)'}  "
              f"embed={emb}{'' if emb == s.embedding_model else '  (substituted)'}")
        v = svc.embed(["Deployments roll out gradually using blue green releases.",
                       "Customers are billed monthly for storage."], "RETRIEVAL_DOCUMENT")
        q = svc.embed(["How do we ship new versions safely?"], "RETRIEVAL_QUERY")[0]
        sims = v @ q
        print(f"✓ Embeddings: shape={v.shape}  similarity(deploy)={sims[0]:.3f}  similarity(billing)={sims[1]:.3f}"
              f"  → {'ranks correctly' if np.argmax(sims) == 0 else 'unexpected order'}")
        out = svc.generate_json("Return only JSON.", 'Reply with {"ok": true}.',
                                {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}, 64)
        print(f"✓ Structured generation: {out}")
        print(f"All checks passed in {time.perf_counter() - t:.1f}s.")
        return 0
    except GeminiUnavailable as exc:
        print(f"✗ Gemini unavailable: {exc}. IntelliDoc will fall back to its built-in engine.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
