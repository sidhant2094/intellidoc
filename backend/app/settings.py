"""Deployment settings read from the environment (and backend/.env for local development)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:  # optional locally; hosts provide real environment variables
    pass

log = logging.getLogger("intellidoc.settings")

LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def _origin(value: str) -> str | None:
    v = value.strip().rstrip("/")
    if not v:
        return None
    if v == "*" or "*" in v:
        log.warning("Ignoring wildcard CORS origin %r; list exact origins or use CORS_ORIGIN_REGEX", v)
        return None
    if not re.match(r"^https?://[^/\s]+$", v):
        log.warning("Ignoring invalid CORS origin %r (expected scheme://host[:port])", v)
        return None
    return v


def cors_origins() -> list[str]:
    """FRONTEND_URL + ALLOWED_ORIGINS (comma-separated), plus localhost unless APP_ENV=production."""
    raw = [os.getenv("FRONTEND_URL", "")] + os.getenv("ALLOWED_ORIGINS", "").split(",")
    origins = [o for o in (_origin(r) for r in raw) if o]
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        origins += LOCAL_ORIGINS
    return list(dict.fromkeys(origins))


def cors_origin_regex() -> str | None:
    """Optional regex for Vercel preview deployments, e.g. ^https://intellidoc-[a-z0-9-]+\\.vercel\\.app$"""
    rx = (os.getenv("CORS_ORIGIN_REGEX") or "").strip()
    if not rx:
        return None
    if rx in {".*", "^.*$", ".+"}:
        log.warning("Ignoring unrestricted CORS_ORIGIN_REGEX")
        return None
    try:
        re.compile(rx)
    except re.error:
        log.warning("Ignoring invalid CORS_ORIGIN_REGEX")
        return None
    return rx
