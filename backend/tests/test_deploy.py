"""Deployment readiness: CORS from environment, early upload rejection."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import settings

VERCEL = "https://intellidoc.vercel.app"


@pytest.fixture
def env(monkeypatch):
    for k in ("FRONTEND_URL", "ALLOWED_ORIGINS", "APP_ENV", "CORS_ORIGIN_REGEX"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def fresh_app():
    import app.main as main
    return importlib.reload(main).app


def test_origins_from_env_with_localhost_in_development(env):
    env.setenv("FRONTEND_URL", VERCEL + "/")
    env.setenv("ALLOWED_ORIGINS", "https://docs.example.com, *, not-a-url,")
    assert settings.cors_origins() == [VERCEL, "https://docs.example.com", *settings.LOCAL_ORIGINS]


def test_production_excludes_localhost_and_wildcards(env):
    env.setenv("APP_ENV", "production")
    env.setenv("FRONTEND_URL", VERCEL)
    env.setenv("CORS_ORIGIN_REGEX", ".*")
    assert settings.cors_origins() == [VERCEL]
    assert settings.cors_origin_regex() is None


def preflight(client, origin):
    return client.options("/api/analyze", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})


def test_cors_allows_configured_frontend_only(env):
    env.setenv("APP_ENV", "production")
    env.setenv("FRONTEND_URL", VERCEL)
    env.setenv("CORS_ORIGIN_REGEX", r"^https://intellidoc-[a-z0-9-]+\.vercel\.app$")
    client = TestClient(fresh_app())
    assert preflight(client, VERCEL).headers.get("access-control-allow-origin") == VERCEL
    preview = "https://intellidoc-git-main-abc123.vercel.app"
    assert preflight(client, preview).headers.get("access-control-allow-origin") == preview
    assert "access-control-allow-origin" not in preflight(client, "https://evil.example.com").headers
    assert "access-control-allow-origin" not in preflight(client, "http://localhost:5173").headers
    r = client.get("/api/health", headers={"Origin": VERCEL})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == VERCEL


def test_local_development_origin_still_allowed(env):
    client = TestClient(fresh_app())
    assert preflight(client, "http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_oversized_upload_rejected_early_with_cors_headers(env, handbook_pdf, monkeypatch):
    env.setenv("FRONTEND_URL", VERCEL)
    main_app = fresh_app()
    import app.main as main
    monkeypatch.setattr(main, "MAX_FILE_BYTES", 1000)
    monkeypatch.setattr(main, "UPLOAD_OVERHEAD_BYTES", 0)
    client = TestClient(main_app)
    r = client.post("/api/analyze", headers={"Origin": VERCEL},
                    data={"persona": "Student", "objective": "deployment"},
                    files={"file": ("big.pdf", handbook_pdf, "application/pdf")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "file_too_large"
    assert r.headers["access-control-allow-origin"] == VERCEL
