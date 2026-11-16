"""Resilient wrapper around the official google-genai SDK.

Design goals: never make IntelliDoc unusable, never hammer the API, never mistake an empty
response for a successful one.

Generation
- Models: the configured `GEMINI_MODEL`, then `GEMINI_FALLBACK_MODEL`. Both are validated against
  `models.list()` (listed + supports generateContent). Listing alone isn't trusted: a model that
  returns 404 at call time is benched for an hour.
- Thinking is configured only for models whose metadata says they support it, and the output-token
  budget gets extra headroom for it (thinking tokens count against `max_output_tokens`).
- A response counts only if it has non-empty, non-thought text. Empty / MAX_TOKENS output gets one
  retry with a larger budget; safety blocks are not retried.
- Transient errors (429 with a short delay, 500, 503, 504, timeouts, connection errors) get bounded
  retries with exponential backoff + jitter, honoring RetryInfo / Retry-After, within an overall
  deadline. Then the model is cooled down and the fallback model is tried once.
- Auth errors pause the capability; per-model cooldowns stop repeated calls to a failing model.

Embeddings use the same retry policy but their own health state, so a generation outage never
disables embeddings (and vice versa).

Every unrecoverable failure raises `GeminiUnavailable`; callers fall back to the local engine.
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import numpy as np

from .config import GeminiSettings

log = logging.getLogger("intellidoc.gemini")

EMBED_BATCH = 100  # batchEmbedContents limit
AUTH_COOLDOWN_S = 600
MODEL_COOLDOWN_S = 60  # after a model exhausts its retries
MISSING_MODEL_COOLDOWN_S = 3600  # 404 at call time
MAX_INLINE_WAIT_S = 6.0  # longest server-suggested wait we'll sit through inside a request
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 8.0
THINKING_HEADROOM = 1024
MAX_OUTPUT_CAP = 8192
TRANSIENT_CODES = {500, 502, 503, 504}


class GeminiUnavailable(Exception):
    """Gemini can't serve this request; use the local path."""


class _Failure(Exception):
    """Internal: one model failed for this request. `fallback` says whether another model may help."""

    def __init__(self, reason: str, *, fallback: bool):
        super().__init__(reason)
        self.fallback = fallback


@dataclass
class _ModelInfo:
    actions: list[str]
    thinking: bool


@dataclass
class Generation:
    text: str
    model: str
    finish_reason: str
    latency_s: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


class GeminiService:
    def __init__(self, settings: GeminiSettings, transport: Any | None = None):
        self.settings = settings
        self._client = transport
        self._lock = threading.Lock()
        self._cooldown: dict[str, float] = {}  # "embed" | "generate" | "model:<name>" -> monotonic deadline
        self._models: dict[str, _ModelInfo] | None = None
        self._models_at = 0.0
        self._budget_day = date.today()
        self._budget_used = 0
        self._no_thinking: set[str] = set()  # models that rejected thinking config at runtime

    # ------------------------------------------------------------------ plumbing

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.settings.api_key,
                http_options=types.HttpOptions(
                    timeout=self.settings.timeout_s * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),  # retries are handled here, measurably
                ),
            )
        return self._client

    def _cooling(self, key: str) -> bool:
        return time.monotonic() < self._cooldown.get(key, 0.0)

    def _cool(self, key: str, seconds: float, reason: str) -> None:
        self._cooldown[key] = time.monotonic() + seconds
        log.warning("Gemini %s paused for %ds: %s", key, int(seconds), reason)

    def available(self, capability: str) -> bool:
        if not self.settings.active or self._cooling(capability):
            return False
        if capability == "generate":
            names = [m for m in (self.settings.model, self.settings.fallback_model) if m]
            return any(not self._cooling(f"model:{m}") for m in names)
        return True

    def _spend(self) -> None:
        with self._lock:
            today = date.today()
            if today != self._budget_day:
                self._budget_day, self._budget_used = today, 0
            if self.settings.daily_limit and self._budget_used >= self.settings.daily_limit:
                raise GeminiUnavailable("daily request budget reached")
            self._budget_used += 1

    def _attempt(self, capability: str, model_key: str, fn: Callable[[], Any], deadline: float) -> Any:
        """Run `fn` with bounded retries for transient failures. Raises _Failure or GeminiUnavailable."""
        attempts = 1 + max(0, self.settings.max_retries)
        last = "unknown error"
        for attempt in range(attempts):
            self._spend()
            try:
                return fn()
            except (GeminiUnavailable, _Failure):
                raise
            except Exception as exc:  # noqa: BLE001 — the SDK raises several types
                code = getattr(exc, "code", None)
                last = _short(exc)
                if code in (401, 403) or (code == 400 and "api key" in str(exc).lower()):
                    self._cool(capability, AUTH_COOLDOWN_S, "authentication or permission problem — check GEMINI_API_KEY")
                    raise GeminiUnavailable("auth") from exc
                if code == 404:
                    self._cool(model_key, MISSING_MODEL_COOLDOWN_S, "model not available to this key")
                    raise _Failure("model not found", fallback=True) from exc
                if code == 400:
                    raise _Failure(f"bad request: {last}", fallback=False) from exc
                delay = _server_delay(exc)
                if code == 429 and (delay is None or delay > MAX_INLINE_WAIT_S):
                    self._cool(model_key, delay or MODEL_COOLDOWN_S, "rate limited / quota")
                    raise _Failure("rate limited", fallback=True) from exc
                transient = code == 429 or code in TRANSIENT_CODES or code is None
                if not transient:
                    raise _Failure(last, fallback=False) from exc
                wait = delay if delay is not None else min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** attempt)
                wait += random.uniform(0, 0.5)
                if attempt + 1 >= attempts or time.monotonic() + wait >= deadline:
                    break
                log.info("Gemini %s transient failure (%s); retry %d/%d in %.1fs",
                         model_key, last, attempt + 1, attempts - 1, wait)
                time.sleep(wait)
        self._cool(model_key, MODEL_COOLDOWN_S, f"repeated transient failures ({last})")
        raise _Failure(last, fallback=True)

    # ------------------------------------------------------------------ models

    def _model_table(self) -> dict[str, _ModelInfo]:
        if self._models is not None and time.monotonic() - self._models_at < 3600:
            return self._models
        deadline = time.monotonic() + self.settings.timeout_s * 2
        try:
            listed = self._attempt("models", "models", lambda: list(self.client.models.list()), deadline)
        except _Failure as exc:
            raise GeminiUnavailable(f"model discovery failed: {exc}") from exc
        table = {}
        for m in listed:
            name = (getattr(m, "name", "") or "").removeprefix("models/")
            if name:
                table[name] = _ModelInfo(list(getattr(m, "supported_actions", None) or []),
                                         bool(getattr(m, "thinking", False)))
        self._models, self._models_at = table, time.monotonic()
        return table

    def generation_models(self) -> list[str]:
        """Configured primary + fallback that are listed and support generateContent (not yet call-verified)."""
        table = self._model_table()
        out = []
        for name in (self.settings.model, self.settings.fallback_model):
            info = table.get(name) if name else None
            if info and (not info.actions or "generateContent" in info.actions) and name not in out:
                out.append(name)
            elif name:
                log.warning("Gemini generation model %r is not available to this key", name)
        return out

    def resolve_model(self, kind: str) -> str:
        if kind == "generate":
            models = [m for m in self.generation_models() if not self._cooling(f"model:{m}")]
            if not models:
                raise GeminiUnavailable("no usable generation model")
            return models[0]
        table = self._model_table()
        wanted = self.settings.embedding_model
        info = table.get(wanted)
        if info and (not info.actions or "embedContent" in info.actions):
            return wanted
        for alt in ("gemini-embedding-001", "text-embedding-004"):
            if alt in table:
                log.warning("Embedding model %r is not available; using %r", wanted, alt)
                return alt
        raise GeminiUnavailable("no usable embedding model")

    # ------------------------------------------------------------------ embeddings

    def embed(self, texts: list[str], task: str, titles: list[str] | None = None) -> np.ndarray:
        """Embed texts in batches; returns an L2-normalized float32 matrix (n, dim)."""
        from google.genai import types

        if not self.available("embed"):
            raise GeminiUnavailable("embeddings paused")
        model = self.resolve_model("embed")
        deadline = time.monotonic() + self.settings.timeout_s * 3
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start:start + EMBED_BATCH]
            if titles and task == "RETRIEVAL_DOCUMENT":
                batch = [f"{t}\n{x}" if t else x for t, x in zip(titles[start:start + EMBED_BATCH], batch)]
            cfg = types.EmbedContentConfig(task_type=task, output_dimensionality=self.settings.embedding_dim)
            try:
                resp = self._attempt("embed", "embed", lambda b=batch, c=cfg: self.client.models.embed_content(
                    model=model, contents=b, config=c), deadline)
            except _Failure as exc:
                raise GeminiUnavailable(f"embedding failed: {exc}") from exc
            vecs = [e.values for e in (resp.embeddings or []) if e.values]
            if len(vecs) != len(batch):
                raise GeminiUnavailable("embedding count mismatch")
            out.extend(vecs)
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    # ------------------------------------------------------------------ generation

    def generate(self, system: str, prompt: str, max_tokens: int, *, schema: dict | None = None,
                 timeout_s: int | None = None) -> Generation:
        """Generate non-empty text, trying the fallback model once if the primary fails."""
        if not self.available("generate"):
            raise GeminiUnavailable("generation paused")
        timeout_s = timeout_s or self.settings.timeout_s
        deadline = time.monotonic() + timeout_s * 2.5  # overall wall-clock budget incl. retries
        models = [m for m in self.generation_models() if not self._cooling(f"model:{m}")]
        if not models:
            raise GeminiUnavailable("no usable generation model")
        errors: list[str] = []
        for i, model in enumerate(models):
            if time.monotonic() >= deadline:
                errors.append("deadline reached")
                break
            try:
                gen = self._generate_once(model, system, prompt, max_tokens, schema, timeout_s, deadline)
                if i:
                    log.info("Gemini fallback model %s succeeded", model)
                return gen
            except _Failure as exc:
                errors.append(f"{model}: {exc}")
                if not exc.fallback:
                    break
        raise GeminiUnavailable("; ".join(errors) or "generation failed")

    def _generate_once(self, model: str, system: str, prompt: str, max_tokens: int, schema: dict | None,
                       timeout_s: int, deadline: float) -> Generation:
        from google.genai import types

        info = (self._models or {}).get(model)
        thinking = bool(info and info.thinking) and model not in self._no_thinking
        budget = min(MAX_OUTPUT_CAP, max_tokens + (THINKING_HEADROOM if thinking else 0))

        def config(budget: int, thinking: bool):
            kw: dict[str, Any] = dict(
                system_instruction=system,
                temperature=0.2,
                max_output_tokens=budget,
                http_options=types.HttpOptions(timeout=timeout_s * 1000,
                                               retry_options=types.HttpRetryOptions(attempts=1)),
            )
            if schema is not None:
                kw.update(response_mime_type="application/json", response_json_schema=schema)
            if thinking:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
            return types.GenerateContentConfig(**kw)

        key = f"model:{model}"
        for round_ in range(2):  # second round only after an empty / truncated response
            t0 = time.perf_counter()

            def call(b=budget, th=thinking):
                return self.client.models.generate_content(model=model, contents=prompt, config=config(b, th))

            try:
                resp = self._attempt("generate", key, call, deadline)
            except _Failure as exc:
                if thinking and "think" in str(exc).lower():
                    self._no_thinking.add(model)  # model rejected thinking config: retry plainly
                    thinking = False
                    budget = min(MAX_OUTPUT_CAP, max_tokens)
                    continue
                raise
            gen = _read(resp, model, time.perf_counter() - t0)
            if gen.finish_reason in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION", "BLOCKED"}:
                raise _Failure(f"response blocked ({gen.finish_reason})", fallback=False)
            truncated = gen.finish_reason == "MAX_TOKENS"
            if gen.text and not truncated:
                log.info("Gemini %s ok in %.1fs (out=%s, thinking=%s)", model, gen.latency_s,
                         gen.output_tokens, gen.thinking_tokens)
                return gen
            if truncated and round_ == 0 and budget < MAX_OUTPUT_CAP and time.monotonic() < deadline:
                budget = min(MAX_OUTPUT_CAP, budget * 2)
                log.info("Gemini %s hit MAX_TOKENS; retrying once with %d tokens", model, budget)
                continue
            raise _Failure("truncated response (MAX_TOKENS)" if truncated else
                           f"empty response (finish={gen.finish_reason})", fallback=True)
        raise _Failure("no usable response", fallback=True)

    def generate_json(self, system: str, prompt: str, schema: dict, max_tokens: int, timeout_s: int | None = None) -> Any:
        """Structured generation. Returns parsed JSON or raises GeminiUnavailable."""
        gen = self.generate(system, prompt, max_tokens, schema=schema, timeout_s=timeout_s)
        return parse_json(gen.text)


def _read(resp: Any, model: str, latency: float) -> Generation:
    """Extract visible (non-thought) text and diagnostics from a GenerateContentResponse."""
    feedback = getattr(resp, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return Generation("", model, "BLOCKED", latency)
    cands = getattr(resp, "candidates", None) or []
    text_parts: list[str] = []
    finish = "NO_CANDIDATES"
    if cands:
        c = cands[0]
        finish = _enum_name(getattr(c, "finish_reason", None)) or "UNSPECIFIED"
        content = getattr(c, "content", None)
        for p in (getattr(content, "parts", None) or []):
            t = getattr(p, "text", None)
            if t and not getattr(p, "thought", False):
                text_parts.append(t)
    elif getattr(resp, "text", None):  # minimal transports (tests) expose only .text
        text_parts.append(resp.text)
        finish = "STOP"
    u = getattr(resp, "usage_metadata", None)
    return Generation("".join(text_parts).strip(), getattr(resp, "model_version", None) or model, finish, latency,
                      getattr(u, "prompt_token_count", None), getattr(u, "candidates_token_count", None),
                      getattr(u, "thoughts_token_count", None))


def _enum_name(v: Any) -> str:
    if v is None:
        return ""
    return str(getattr(v, "name", v)).split(".")[-1].upper()


def parse_json(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GeminiUnavailable("malformed JSON from model") from exc


def _server_delay(exc: Exception) -> float | None:
    """Server-suggested wait from google.rpc.RetryInfo or a Retry-After header."""
    details = getattr(exc, "details", None)
    try:
        for d in (details or {}).get("error", {}).get("details", []) or []:
            m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
            if m:
                return min(900.0, float(m.group(1)))
    except AttributeError:
        pass
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        try:
            ra = headers.get("retry-after") or headers.get("Retry-After")
            if ra is not None:
                return min(900.0, float(ra))
        except (TypeError, ValueError):
            pass
    return None


def _short(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    head = f"{code} {status}" if code else type(exc).__name__
    return f"{head}: {str(getattr(exc, 'message', None) or exc)[:140]}"


# ---------------------------------------------------------------------- singleton

_service: GeminiService | None = None
_service_lock = threading.Lock()


def get_service() -> GeminiService | None:
    """Return the shared service, or None when Gemini isn't configured."""
    global _service
    with _service_lock:
        if _service is None:
            settings = GeminiSettings.from_env()
            _service = GeminiService(settings)
            if settings.active:
                log.info("Gemini configured (model=%s, fallback=%s, embeddings=%s)", settings.model,
                         settings.fallback_model or "none", settings.embedding_model)
            else:
                log.info("Gemini not configured; using the local engine only")
        return _service if _service.settings.active else None


def set_service(service: GeminiService | None) -> None:
    """Testing hook."""
    global _service
    with _service_lock:
        _service = service
