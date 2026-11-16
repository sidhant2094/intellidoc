"""A fake google-genai transport: deterministic, offline, and inspectable."""

from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace

import numpy as np

from app.gemini.client import GeminiService
from app.gemini.config import GeminiSettings

CONCEPTS = {
    "deploy": "ship shipping shipped release releases released rollout rollouts deploy deployed deployment "
              "deployments launch production versions version upgrade upgrades downtime",
    "money": "billing billed invoice invoices charges charge charged pay paid refunded payment refund refunds money cost costs price "
             "prices pricing plan plans spend",
    "security": "security secure encrypted encryption tls keys secrets vault protect protected attack safe",
    "data": "database migrations migration schema storage",
}
WORD2CONCEPT = {w: c for c, ws in CONCEPTS.items() for w in ws.split()}
DIM = 64


def concept_vector(text: str) -> list[float]:
    v = np.zeros(DIM)
    for w in re.findall(r"[a-z]+", text.lower()):
        key = WORD2CONCEPT.get(w)
        if key:
            idx, weight = int(hashlib.md5(key.encode()).hexdigest(), 16) % DIM, 3.0
        else:
            idx, weight = int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM, 0.15
        v[idx] += weight
    return v.tolist()


class ApiErr(Exception):
    def __init__(self, code: int, msg: str = "error", retry: str | None = None, retry_after: str | None = None):
        super().__init__(msg)
        self.code = code
        self.message = msg
        self.details = {"error": {"details": [{"retryDelay": retry}] if retry else []}}
        self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})


def response(text: str | None, finish: str = "STOP", thought: str | None = None, blocked: bool = False):
    """A GenerateContentResponse-shaped object."""
    parts = []
    if thought:
        parts.append(SimpleNamespace(text=thought, thought=True))
    if text is not None:
        parts.append(SimpleNamespace(text=text, thought=None))
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=SimpleNamespace(name=finish))],
        prompt_feedback=SimpleNamespace(block_reason="SAFETY") if blocked else None,
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=50),
        model_version=None, text=text,
    )


class FakeModels:
    def __init__(self, gen=None, embed_error=None, gen_error=None,
                 available=("gemini-3.8-flash", "gemini-embedding-001"), per_model=None, thinking=()):
        self.gen = gen or default_generate
        self.embed_error = embed_error
        self.gen_error = gen_error
        self.available = available
        self.per_model = per_model or {}  # model -> callable(prompt, config) returning response / raising
        self.thinking = set(thinking)
        self.embed_calls: list[int] = []
        self.gen_prompts: list[str] = []
        self.gen_calls: list[tuple[str, object]] = []  # (model, config)
        self.list_calls = 0

    def list(self, config=None):
        self.list_calls += 1
        for n in self.available:
            action = "embedContent" if "embedding" in n else "generateContent"
            yield SimpleNamespace(name=f"models/{n}", supported_actions=[action], thinking=n in self.thinking)

    def embed_content(self, model, contents, config=None):
        if self.embed_error:
            raise self.embed_error() if callable(self.embed_error) else self.embed_error
        self.embed_calls.append(len(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=concept_vector(t)) for t in contents])

    def generate_content(self, model, contents, config=None):
        self.gen_prompts.append(contents)
        self.gen_calls.append((model, config))
        if model in self.per_model:
            return self.per_model[model](contents, config)
        if self.gen_error:
            raise self.gen_error() if callable(self.gen_error) else self.gen_error
        out = self.gen(contents)
        return SimpleNamespace(text=out if isinstance(out, str) else json.dumps(out))


def ids_in(prompt: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"\[({prefix}\d+)\]", prompt)))


def blocks(prompt: str, prefix: str) -> dict[str, str]:
    parts = re.split(rf"\n?\[({prefix}\d+)\] ", prompt)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def default_generate(prompt: str):
    """Rerank: relevance by concept overlap with the objective. Summaries/chat: grounded echoes."""
    if "rate how useful" in prompt:
        objective = re.search(r"Objective: (.*)", prompt).group(1)
        want = {WORD2CONCEPT.get(w) for w in re.findall(r"[a-z]+", objective.lower())} - {None}
        out = []
        for cid, text in blocks(prompt, "C").items():
            have = {WORD2CONCEPT.get(w) for w in re.findall(r"[a-z]+", text.lower())} - {None}
            out.append({"id": cid, "relevance": 3 if want & have else 0, "priority": 1})
        return {"assessments": out}
    if "For EACH passage id" in prompt:
        rids = ids_in(prompt, "R")
        return {
            "results": [{"id": r, "why": "This passage addresses your objective directly.",
                         "summary": "It explains the approach the team follows.",
                         "findings": ["The approach is described in the passage."],
                         "takeaways": ["Read this section first."], "limitations": []} for r in rids],
            "insights": [{"kind": "theme", "title": "Shared theme", "result_ids": rids[:2],
                          "text": "These sections describe how the platform is operated."}],
        }
    if "EVIDENCE" in prompt:
        eids = ids_in(prompt, "E")
        return {"answer": f"The document explains this in the relevant section [{eids[0]}].",
                "supported": True, "citations": [eids[0]]}
    return {}


def make_service(models: FakeModels, daily_limit: int = 0, model: str = "gemini-3.8-flash",
                 fallback: str = "", max_retries: int = 2) -> GeminiService:
    settings = GeminiSettings(api_key="test-key-not-real", enabled=True, model=model,
                              embedding_model="gemini-embedding-001", embedding_dim=DIM, timeout_s=5,
                              daily_limit=daily_limit, fallback_model=fallback, max_retries=max_retries)
    return GeminiService(settings, transport=SimpleNamespace(models=models))
