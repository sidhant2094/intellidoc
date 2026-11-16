"""HTTP contract: validation errors, streamed stages, and final result."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def post(data: bytes | None, objective="deployment rollout constraints", persona="Software Engineer", name="doc.pdf", **extra):
    files = {"file": (name, data, "application/pdf")} if data is not None else None
    form = {"persona": persona, "expertise": "Intermediate", "objective": objective, **extra}
    return client.post("/api/analyze", data=form, files=files)


def events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    body = r.json()
    # Provider-neutral: no engine/model/credential details are exposed.
    assert set(body) == {"status", "version", "max_file_mb"}


def test_streams_stages_then_result(handbook_pdf):
    r = post(handbook_pdf, focus_terms="migrations, blue green")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    evs = events(r)
    assert [e["stage"] for e in evs if e["type"] == "stage"][0] == "reading"
    assert evs[-1]["type"] == "result"
    data = evs[-1]["data"]
    assert data["document"]["page_count"] == 4
    assert data["analysis"]["focus_terms"] == ["migrations", "blue green"]
    assert data["results"][0]["page_start"] == 2


def test_missing_file():
    r = post(None)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "no_file"


def test_missing_objective(handbook_pdf):
    r = post(handbook_pdf, objective=" ")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "missing_objective"


def test_missing_persona(handbook_pdf):
    r = post(handbook_pdf, persona="")
    assert r.json()["error"]["code"] == "missing_persona"


def test_not_pdf():
    r = client.post("/api/analyze", data={"persona": "x", "objective": "abc def"},
                    files={"file": ("notes.txt", b"plain text", "text/plain")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "invalid_file_type"


def test_too_large(handbook_pdf, monkeypatch):
    monkeypatch.setattr(main, "MAX_FILE_BYTES", 100)
    r = post(handbook_pdf)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "file_too_large"


def test_password_protected(encrypted_pdf):
    r = post(encrypted_pdf)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "password_protected"


def test_scanned_streams_error(scanned_pdf):
    r = post(scanned_pdf)
    evs = events(r)
    assert evs[-1]["type"] == "error"
    assert evs[-1]["error"]["code"] == "scanned_pdf"
    assert "OCR" in evs[-1]["error"]["hint"]
