"""IntelliDoc API."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import errors
from .config import MAX_FILE_BYTES, MAX_FILE_MB
from .errors import AnalysisError
from .pdf_extract import open_pdf
from .gemini.chat import answer as answer_question
from .gemini.client import get_service
from .pipeline import analyze
from .schemas import AskResponse
from .session import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("intellidoc")

app = FastAPI(title="IntelliDoc API", version="2.0.0",
              description="Persona-aware PDF section ranking. Runs fully locally.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

EXPERTISE = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}


def error_response(err: AnalysisError) -> JSONResponse:
    return JSONResponse({"error": err.to_dict()}, status_code=err.status)


@app.get("/api/health")
def health() -> dict:
    # Provider-neutral by design: no engine, model or credential details are exposed.
    return {"status": "ok", "version": app.version, "max_file_mb": MAX_FILE_MB}


@app.post("/api/analyze", responses={200: {"content": {"application/x-ndjson": {}}}})
async def analyze_endpoint(
    file: UploadFile | None = File(None),
    persona: str = Form(""),
    expertise: str = Form("Intermediate"),
    objective: str = Form(""),
    focus_terms: str = Form(""),
):
    """Validate synchronously (HTTP errors), then stream NDJSON progress events and the final result.

    Event lines: {"type":"stage","stage":...,"detail":...} · {"type":"result","data":AnalyzeResponse}
    · {"type":"error","error":{code,message,hint}}
    """
    persona = persona.strip()[:120]
    objective = objective.strip()[:2000]
    expertise = EXPERTISE.get(expertise.strip().lower(), "Intermediate")
    terms = [t.strip()[:60] for t in focus_terms.replace("\n", ",").split(",") if t.strip()][:12]

    if file is None or not file.filename:
        return error_response(AnalysisError("no_file", "No PDF was selected.", "Add a PDF to analyze.", 400))
    if len(objective) < 3:
        return error_response(AnalysisError(
            "missing_objective", "Tell IntelliDoc what you're trying to find.",
            "Describe your objective in a sentence, e.g. “deployment constraints and API limits”.", 400))
    if not persona:
        return error_response(AnalysisError("missing_persona", "Choose or describe your role.",
                                            "Pick a preset like Student or type your own.", 400))

    name = file.filename
    if file.content_type not in (None, "", "application/pdf", "application/x-pdf", "application/octet-stream") \
            and not name.lower().endswith(".pdf"):
        return error_response(errors.not_pdf())

    data = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    if len(data) > MAX_FILE_BYTES:
        return error_response(errors.too_large(MAX_FILE_MB))
    if not data:
        return error_response(AnalysisError("empty_file", "That file is empty.", "Choose a different PDF.", 400))

    try:
        doc = open_pdf(data)  # in-memory: nothing is written to disk
    except AnalysisError as err:
        log.info("Rejected %s: %s", name, err.code)
        return error_response(err)

    def stream():
        try:
            for event in analyze(doc, name, persona, expertise, objective, terms):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except AnalysisError as err:
            log.info("Analysis of %s stopped: %s", name, err.code)
            yield json.dumps({"type": "error", "error": err.to_dict()}) + "\n"
        except Exception:  # noqa: BLE001
            log.exception("Unexpected failure analyzing %s", name)
            yield json.dumps({"type": "error", "error": {
                "code": "analysis_failed",
                "message": "Something went wrong while analyzing this PDF.",
                "hint": "Try again. If it keeps happening, the PDF may use an unusual structure — try re-exporting it.",
            }}) + "\n"
        finally:
            doc.close()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/session/{session_id}/ask", response_model=AskResponse)
def ask(session_id: str, payload: dict = Body(...)):
    """Answer a follow-up question about an analyzed document, with citations."""
    question = str(payload.get("question", "")).strip()[:500]
    if len(question) < 2:
        return error_response(AnalysisError("missing_question", "Ask a question about the document.", "", 400))
    sess = store.get(session_id)
    if sess is None:
        return error_response(AnalysisError(
            "session_expired", "This analysis is no longer active.",
            "Run the analysis again to ask more questions.", 404))
    try:
        return answer_question(sess, question, get_service())
    except Exception:  # noqa: BLE001
        log.exception("Ask failed")
        return error_response(AnalysisError(
            "ask_failed", "Something went wrong while answering.", "Please try asking again.", 500))
