"""Live check of the Gemini setup. Never prints the API key.

Tests each configured generation model directly (plain text + structured JSON), then embeddings.
Uses about 6 small requests. Usage (from backend/):  .venv/bin/python -m scripts.gemini_smoke
"""

from __future__ import annotations

import logging
import sys
import time

from app.gemini.client import GeminiUnavailable, get_service, parse_json

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def check_model(svc, model: str) -> bool:
    """Exercise one model in isolation (fallback disabled) so failures are attributable."""
    svc._models = None
    s = svc.settings
    original = (s.model, s.fallback_model)
    object.__setattr__(s, "model", model)
    object.__setattr__(s, "fallback_model", "")
    try:
        gen = svc.generate("Answer briefly.", "In one short sentence, what is a PDF file?", 256)
        print(f"  ✓ text   {gen.latency_s:5.1f}s  finish={gen.finish_reason}  served_by={gen.model}  "
              f"tokens out={gen.output_tokens} thinking={gen.thinking_tokens}\n           {gen.text[:110]!r}")
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        t = time.perf_counter()
        data = parse_json(svc.generate("Return only JSON.", 'Return {"ok": true}.', 128, schema=schema).text)
        good = isinstance(data, dict) and data.get("ok") is True
        print(f"  {'✓' if good else '✗'} json   {time.perf_counter() - t:5.1f}s  {data}")
        return good
    except GeminiUnavailable as exc:
        print(f"  ✗ {exc}")
        return False
    finally:
        object.__setattr__(s, "model", original[0])
        object.__setattr__(s, "fallback_model", original[1])


def main() -> int:
    svc = get_service()
    if svc is None:
        print("Gemini is not active: set GEMINI_API_KEY (and GEMINI_ENABLED=true) in backend/.env.")
        return 1
    s = svc.settings
    print(f"Configured: model={s.model}  fallback={s.fallback_model or '—'}  embeddings={s.embedding_model} "
          f"(dim {s.embedding_dim})  retries={s.max_retries}  timeout={s.timeout_s}s\n")
    results = {}
    for model in [m for m in (s.model, s.fallback_model) if m]:
        print(f"{model}")
        results[model] = check_model(svc, model)
    print("\nEmbeddings")
    try:
        t = time.perf_counter()
        v = svc.embed(["Deployments roll out gradually using blue green releases.",
                       "Customers are billed monthly for storage."], "RETRIEVAL_DOCUMENT")
        q = svc.embed(["How do we ship new versions safely?"], "RETRIEVAL_QUERY")[0]
        sims = v @ q
        print(f"  ✓ {time.perf_counter() - t:4.1f}s  shape={v.shape}  sim(deploy)={sims[0]:.3f}  sim(billing)={sims[1]:.3f}"
              f"  → {'ranks correctly' if sims[0] > sims[1] else 'unexpected order'}")
        embed_ok = True
    except GeminiUnavailable as exc:
        print(f"  ✗ {exc}")
        embed_ok = False
    usable = [m for m, ok in results.items() if ok]
    print(f"\nGeneration: {'usable via ' + ', '.join(usable) if usable else 'UNAVAILABLE (IntelliDoc will use its built-in engine)'}"
          f" | Embeddings: {'ok' if embed_ok else 'UNAVAILABLE'}")
    return 0 if usable and embed_ok else 2


if __name__ == "__main__":
    sys.exit(main())
