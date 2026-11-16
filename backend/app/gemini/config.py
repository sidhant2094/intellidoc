"""Gemini settings from environment / backend/.env. The key is never logged or returned."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:  # python-dotenv is optional; real env vars still work
    pass


def _bool(v: str | None, default: bool) -> bool:
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(v: str | None, default: int) -> int:
    try:
        return int(v) if v else default
    except ValueError:
        return default


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(repr=False)
    enabled: bool
    model: str
    embedding_model: str
    embedding_dim: int
    timeout_s: int
    daily_limit: int
    fallback_model: str = ""
    max_retries: int = 2

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.api_key)

    @classmethod
    def from_env(cls) -> "GeminiSettings":
        return cls(
            api_key=(os.getenv("GEMINI_API_KEY") or "").strip(),
            enabled=_bool(os.getenv("GEMINI_ENABLED"), True),
            model=(os.getenv("GEMINI_MODEL") or "gemini-3.1-flash-lite").strip(),
            embedding_model=(os.getenv("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-001").strip(),
            embedding_dim=max(128, min(3072, _int(os.getenv("GEMINI_EMBEDDING_DIM"), 768))),
            timeout_s=max(5, _int(os.getenv("GEMINI_TIMEOUT_S"), 30)),
            daily_limit=max(0, _int(os.getenv("GEMINI_DAILY_REQUEST_LIMIT"), 400)),
            fallback_model=(os.getenv("GEMINI_FALLBACK_MODEL") or "").strip(),
            max_retries=max(0, min(4, _int(os.getenv("GEMINI_MAX_RETRIES"), 2))),
        )
