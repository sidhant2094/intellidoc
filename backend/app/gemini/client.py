"""Resilient wrapper around the official google-genai SDK.

Design goals: never make IntelliDoc unusable, never hammer the API.
- Models are validated against `models.list()` (cached); a missing model is substituted or the
  capability is disabled.
- At most one retry, only for transient failures (timeouts, 5xx). 429 never retries: it opens a
  circuit breaker for the server-suggested delay so later requests skip Gemini instantly.
- Auth/permission errors disable the capability for a while (bad keys don't cause call storms).
- A soft daily request budget protects free-tier quota.
Every failure raises `GeminiUnavailable`; callers fall back to the local engine.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import date
from typing import Any

import numpy as np

from .config import GeminiSettings

log = logging.getLogger("intellidoc.gemini")

EMBED_BATCH = 100  # batchEmbedContents limit
AUTH_COOLDOWN_S = 600
RATE_COOLDOWN_S = 60
TRANSIENT_COOLDOWN_S = 30


class GeminiUnavailable(Exception):
    """Gemini can't serve this request; use the local path."""


class GeminiService:
    def __init__(self, settings: GeminiSettings, transport: Any | None = None):
        self.settings = settings
        self._client = transport
        self._lock = threading.Lock()
        self._cooldown: dict[str, float] = {}  # capability -> monotonic time until usable
        self._resolved: dict[str, str | None] = {}
        self._resolved_at = 0.0
        self._budget_day = date.today()
        self._budget_used = 0
        self._thinking_ok = True

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
                    retry_options=types.HttpRetryOptions(attempts=1),  # we handle retries ourselves
                ),
            )
        return self._client

    def available(self, capability: str) -> bool:
        if not self.settings.active:
            return False
        return time.monotonic() >= self._cooldown.get(capability, 0.0)

    def _spend(self, n: int = 1) -> None:
        with self._lock:
            today = date.today()
            if today != self._budget_day:
                self._budget_day, self._budget_used = today, 0
            if self.settings.daily_limit and self._budget_used + n > self.settings.daily_limit:
                raise GeminiUnavailable("daily request budget reached")
            self._budget_used += n

    def _cool(self, capability: str, seconds: float, reason: str) -> None:
        self._cooldown[capability] = time.monotonic() + seconds
        log.warning("Gemini %s paused for %ds: %s", capability, int(seconds), reason)

    def _call(self, capability: str, fn, *, retry: bool = True):
        if not self.available(capability):
            raise GeminiUnavailable(f"{capability} unavailable")
        self._spend()
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                return fn()
            except GeminiUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 — SDK raises many types
                code = getattr(exc, "code", None)
                if code == 429:
                    self._cool(capability, _retry_delay(exc) or RATE_COOLDOWN_S, "rate limited / quota")
                    raise GeminiUnavailable("rate limited") from exc
                if code in (401, 403) or (code == 400 and "api key" in str(exc).lower()):
                    self._cool(capability, AUTH_COOLDOWN_S, "authentication or permission problem — check GEMINI_API_KEY")
                    raise GeminiUnavailable("auth") from exc
                if code == 404:
                    self._resolved.clear()  # model vanished: re-resolve next time
                    raise GeminiUnavailable("model not found") from exc
                if code == 400:
                    raise GeminiUnavailable(f"bad request: {_short(exc)}") from exc
                transient = code is None or (isinstance(code, int) and code >= 500)
                if transient and attempt + 1 < attempts:
                    time.sleep(1.2)
                    continue
                if transient:
                    self._cool(capability, TRANSIENT_COOLDOWN_S, f"transient failure: {_short(exc)}")
                raise GeminiUnavailable(_short(exc)) from exc
        raise GeminiUnavailable("unreachable")

    # ------------------------------------------------------------------ models

    def resolve_model(self, kind: str) -> str:
        """Validate the configured model name against the live API (cached for an hour)."""
        if time.monotonic() - self._resolved_at > 3600:
            self._resolved.clear()
        if kind in self._resolved:
            name = self._resolved[kind]
            if not name:
                raise GeminiUnavailable(f"no usable {kind} model")
            return name
        wanted = self.settings.model if kind == "generate" else self.settings.embedding_model
        action = "generateContent" if kind == "generate" else "embedContent"
        models = self._call(kind, lambda: list(self.client.models.list()), retry=False)
        usable = {}
        for m in models:
            name = (getattr(m, "name", "") or "").removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if name and (not actions or action in actions):
                usable[name] = m
        chosen = wanted if wanted in usable else _substitute(kind, usable)
        if chosen != wanted:
            log.warning("Configured Gemini %s model %r is not available; using %r", kind, wanted, chosen)
        self._resolved[kind] = chosen
        self._resolved_at = time.monotonic()
        if not chosen:
            raise GeminiUnavailable(f"no usable {kind} model")
        return chosen

    # ------------------------------------------------------------------ capabilities

    def embed(self, texts: list[str], task: str, titles: list[str] | None = None) -> np.ndarray:
        """Embed texts in batches; returns L2-normalized float32 matrix (n, dim)."""
        from google.genai import types

        model = self.resolve_model("embed")
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start:start + EMBED_BATCH]
            if titles and task == "RETRIEVAL_DOCUMENT":
                # Titles help document embeddings; the SDK takes one title per request,
                # so we fold the section path into the text instead.
                batch = [f"{t}\n{x}" if t else x for t, x in zip(titles[start:start + EMBED_BATCH], batch)]
            cfg = types.EmbedContentConfig(task_type=task, output_dimensionality=self.settings.embedding_dim)
            resp = self._call("embed", lambda b=batch, c=cfg: self.client.models.embed_content(model=model, contents=b, config=c))
            vecs = [e.values for e in (resp.embeddings or [])]
            if len(vecs) != len(batch):
                raise GeminiUnavailable("embedding count mismatch")
            out.extend(vecs)
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    def generate_json(self, system: str, prompt: str, schema: dict, max_tokens: int, timeout_s: int | None = None) -> Any:
        """Structured generation. Returns parsed JSON or raises GeminiUnavailable."""
        from google.genai import types

        model = self.resolve_model("generate")

        def build(thinking: bool):
            kwargs: dict[str, Any] = dict(
                system_instruction=system,
                temperature=0.2,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                response_json_schema=schema,
            )
            if timeout_s:
                kwargs["http_options"] = types.HttpOptions(timeout=timeout_s * 1000,
                                                           retry_options=types.HttpRetryOptions(attempts=1))
            if thinking:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
            return types.GenerateContentConfig(**kwargs)

        def run():
            try:
                return self.client.models.generate_content(model=model, contents=prompt, config=build(self._thinking_ok))
            except Exception as exc:  # noqa: BLE001
                # Some models reject thinking settings: retry once without, and remember.
                if self._thinking_ok and getattr(exc, "code", None) == 400 and "think" in str(exc).lower():
                    self._thinking_ok = False
                    return self.client.models.generate_content(model=model, contents=prompt, config=build(False))
                raise

        resp = self._call("generate", run)
        text = getattr(resp, "text", None) or ""
        return parse_json(text)


def parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GeminiUnavailable("malformed JSON from model") from exc


def _retry_delay(exc: Exception) -> float | None:
    details = getattr(exc, "details", None)
    try:
        for d in (details or {}).get("error", {}).get("details", []):
            m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
            if m:
                return min(900.0, float(m.group(1)) + 1)
    except AttributeError:
        pass
    return None


def _substitute(kind: str, usable: dict) -> str | None:
    names = list(usable)
    if kind == "embed":
        for pref in ("gemini-embedding-001", "text-embedding-004"):
            if pref in names:
                return pref
        return next((n for n in names if "embedding" in n), None)
    flash = []
    for n in names:
        m = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", n)
        if m:
            flash.append((float(m.group(1)), n))
    if flash:
        return max(flash)[1]
    return next((n for n in names if "flash" in n and not re.search(r"image|tts|live|audio|lite", n)), None)


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


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
                log.info("Gemini configured (model=%s, embeddings=%s)", settings.model, settings.embedding_model)
            else:
                log.info("Gemini not configured; using the local engine only")
        return _service if _service.settings.active else None


def set_service(service: GeminiService | None) -> None:
    """Testing hook."""
    global _service
    with _service_lock:
        _service = service
