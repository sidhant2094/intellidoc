"""Gemini integration (fully mocked): client resilience, semantic + hybrid ranking, grounding,
fallbacks, Ask IntelliDoc, and provider-neutral output. No real API calls are made."""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.gemini import client as gclient
from app.gemini.client import GeminiService, GeminiUnavailable
from app.gemini.config import GeminiSettings
from app.gemini.embeddings import embed_texts
from app.gemini.grounding import Source, clean_text
from app.main import app
from app.pdf_extract import open_pdf
from app.pipeline import analyze
from app.session import store
from app.text_utils import normalize_ws
from tests.fakes import ApiErr, FakeModels, blocks, default_generate, ids_in, make_service

VOCAB_MISMATCH = "How do we ship new versions without downtime?"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(gclient.time, "sleep", lambda s: None)


def use(models: FakeModels, **kw) -> FakeModels:
    gclient.set_service(make_service(models, **kw))
    return models


def run(pdf: bytes, objective: str, persona="Software Engineer", expertise="Intermediate", focus=()):
    doc = open_pdf(pdf)
    events = list(analyze(doc, "t.pdf", persona, expertise, objective, list(focus)))
    return next(e["data"] for e in events if e["type"] == "result"), doc


# --------------------------------------------------------------------------- client


def test_missing_key_disables_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    gclient.set_service(None)
    assert gclient.get_service() is None


def test_disabled_flag(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    gclient.set_service(None)
    assert gclient.get_service() is None


def test_client_initialization_and_key_not_exposed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    monkeypatch.setenv("GEMINI_EMBEDDING_DIM", "512")
    gclient.set_service(None)
    svc = gclient.get_service()
    assert svc is not None and svc.settings.embedding_dim == 512
    assert "super-secret-value" not in repr(svc.settings)


def test_model_validation_substitutes_missing_model():
    m = use(FakeModels(available=("gemini-2.5-flash", "gemini-3-flash", "gemini-3-flash-lite", "gemini-embedding-001")))
    svc = gclient.get_service()
    assert svc.resolve_model("generate") == "gemini-3-flash"
    assert svc.resolve_model("embed") == "gemini-embedding-001"
    svc.resolve_model("generate")
    assert m.list_calls == 2  # cached per capability, not per request


def test_no_usable_model_raises():
    use(FakeModels(available=("gemini-embedding-001",)))
    with pytest.raises(GeminiUnavailable):
        gclient.get_service().resolve_model("generate")


def test_embedding_success_batches_normalizes_and_caches():
    m = use(FakeModels())
    svc = gclient.get_service()
    texts = [f"release number {i} rollout" for i in range(150)]
    vecs = embed_texts(svc, texts, "RETRIEVAL_DOCUMENT")
    assert vecs.shape == (150, 64)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1, atol=1e-5)
    assert m.embed_calls == [100, 50]  # batched at the API limit
    embed_texts(svc, texts[:10] + ["something new"], "RETRIEVAL_DOCUMENT")
    assert m.embed_calls == [100, 50, 1]  # cached chunks are not re-embedded


def test_embedding_failure_raises_and_pauses():
    m = use(FakeModels(embed_error=ApiErr(503, "unavailable")))
    svc = gclient.get_service()
    with pytest.raises(GeminiUnavailable):
        svc.embed(["x"], "RETRIEVAL_DOCUMENT")
    assert not svc.available("embed")


def test_rate_limit_is_not_retried_and_opens_breaker():
    calls = []

    def boom():
        calls.append(1)
        return ApiErr(429, "quota", retry="20s")

    use(FakeModels(gen_error=boom))
    svc = gclient.get_service()
    with pytest.raises(GeminiUnavailable):
        svc.generate_json("s", "p", {"type": "object"}, 100)
    assert len(calls) == 1
    assert not svc.available("generate")
    with pytest.raises(GeminiUnavailable):  # skipped instantly, no API call
        svc.generate_json("s", "p", {"type": "object"}, 100)
    assert len(calls) == 1


def test_timeout_retries_once_then_fails():
    calls = []

    def timeout():
        calls.append(1)
        return TimeoutError("read timed out")

    use(FakeModels(gen_error=timeout))
    with pytest.raises(GeminiUnavailable):
        gclient.get_service().generate_json("s", "p", {"type": "object"}, 100)
    assert len(calls) == 2


def test_auth_error_pauses_without_retry():
    m = use(FakeModels(gen_error=ApiErr(403, "permission denied")))
    svc = gclient.get_service()
    with pytest.raises(GeminiUnavailable):
        svc.generate_json("s", "p", {"type": "object"}, 100)
    assert len(m.gen_prompts) == 1 and not svc.available("generate")


def test_malformed_json_raises():
    use(FakeModels(gen=lambda p: "this is { not json"))
    with pytest.raises(GeminiUnavailable):
        gclient.get_service().generate_json("s", "p", {"type": "object"}, 100)


def test_daily_budget_is_enforced():
    m = use(FakeModels(), daily_limit=2)
    svc = gclient.get_service()
    svc.resolve_model("generate")  # 1 request (model list)
    svc.generate_json("s", "p", {"type": "object"}, 100)  # 2
    with pytest.raises(GeminiUnavailable):
        svc.generate_json("s", "p", {"type": "object"}, 100)
    assert len(m.gen_prompts) == 1


# --------------------------------------------------------------------------- ranking


def test_local_engine_misses_vocabulary_mismatch(handbook_pdf):
    res, _ = run(handbook_pdf, VOCAB_MISMATCH)
    titles = [r["title"] for r in res["results"]]
    assert not titles or "Deployment" not in titles[0]


def test_semantic_retrieval_finds_meaning_not_words(handbook_pdf):
    use(FakeModels(gen_error=ApiErr(429, "quota")))  # embeddings only
    res, _ = run(handbook_pdf, VOCAB_MISMATCH)
    assert res["results"], "semantic retrieval should surface a match"
    top = res["results"][0]
    assert "Deployment" in top["title"]
    assert top["signals"]["semantic"] > 0.6
    assert top["signals"]["contextual"] == 0.0  # not measured; weight redistributed
    assert res["analysis"]["weights"]["contextual"] == 0


def test_hybrid_ranking_uses_reranker_and_drops_irrelevant(handbook_pdf):
    m = use(FakeModels())
    res, _ = run(handbook_pdf, "How are customers charged and refunded?", persona="Business Analyst")
    assert res["results"][0]["title"].endswith("Pricing and Billing")
    assert res["results"][0]["signals"]["contextual"] == 1.0
    assert res["analysis"]["weights"]["contextual"] > 0
    # Sections rated 0 by the reranker are not returned.
    assert all("Security" not in r["title"] for r in res["results"])
    assert len(m.gen_prompts) == 2  # one rerank + one summary call per analysis


def test_hybrid_weights_sum_to_one_and_scores_are_bounded(handbook_pdf):
    use(FakeModels())
    res, _ = run(handbook_pdf, "deployment rollout process")
    assert abs(sum(res["analysis"]["weights"].values()) - 1) < 1e-3
    assert all(0 <= r["match_score"] <= 1 for r in res["results"])
    assert len(res["results"]) <= 10


def test_offtopic_query_still_returns_nothing_with_ai(handbook_pdf):
    use(FakeModels())
    res, _ = run(handbook_pdf, "medieval falconry techniques and bird diets", persona="Student")
    assert res["results"] == []


def test_invalid_rerank_json_falls_back_to_semantic(handbook_pdf):
    def gen(prompt):
        return "not json" if "rate how useful" in prompt else default_generate(prompt)

    use(FakeModels(gen=gen))
    res, _ = run(handbook_pdf, VOCAB_MISMATCH)
    assert "Deployment" in res["results"][0]["title"]
    assert res["results"][0]["signals"]["contextual"] == 0.0


def test_invalid_candidate_ids_are_ignored(handbook_pdf):
    from app.gemini.reranker import validate

    ids = {"C1": "s1", "C2": "s2", "C3": "s3"}
    data = {"assessments": [{"id": "C1", "relevance": 3}, {"id": "C2", "relevance": 2},
                            {"id": "C99", "relevance": 3}, {"id": "C1", "relevance": 0},
                            {"id": "C3", "relevance": "high"}]}
    rel, _ = validate(data, ids)
    assert rel == {"s1": 1.0, "s2": 0.7}
    assert validate({"assessments": [{"id": "C9", "relevance": 3}]}, ids) is None  # too little coverage
    assert validate(["nope"], ids) is None


# --------------------------------------------------------------------------- explanations & grounding


def test_unsupported_claims_are_removed():
    src = Source(["Invoices are generated on the first business day. Refunds take thirty days, 10% fee."], {3}, {"3"})
    text = ("Invoices are generated on the first business day. Refunds cost 25% of the order. "
            "See page 9 for details. Section 7 covers taxes. It says “all customers receive free upgrades forever”. "
            "A 10% fee applies, as described in section 3 on page 3.")
    out = clean_text(text, src)
    assert "first business day" in out
    assert "10% fee" in out
    for bad in ("25%", "page 9", "Section 7", "free upgrades"):
        assert bad not in out


def test_ai_fields_are_grounded_and_excerpt_stays_verbatim(handbook_pdf):
    def gen(prompt):
        if "For EACH passage id" in prompt:
            rids = ids_in(prompt, "R")
            return {"results": [{"id": r, "why": "Shows how rollouts work. It claims 99.99% uptime on page 42.",
                                 "summary": "Services roll out gradually.", "findings": ["Latency regressions block releases.", "Saves $5,000 yearly."],
                                 "takeaways": ["Plan backward compatible migrations."], "limitations": []} for r in rids]
                    + [{"id": "R77", "why": "fabricated", "summary": "fabricated"}],
                    "insights": [{"kind": "risk", "title": "Rollout risk", "text": "Old and new containers run side by side during a rollout.", "result_ids": ["R1", "R99"]},
                                 {"kind": "theme", "title": "Made up", "text": "Nothing to see here at all, really.", "result_ids": ["R42"]}]}
        return default_generate(prompt)

    use(FakeModels(gen=gen))
    res, doc = run(handbook_pdf, "deployment rollout and database migrations")
    top = res["results"][0]
    assert "Deployment" in top["title"]
    assert top["why_relevant"] == "Shows how rollouts work."  # unsupported sentence removed
    assert top["findings"] == ["Latency regressions block releases."]
    assert top["summary"] == "Services roll out gradually."
    # Verbatim excerpt still comes from the PDF on the cited page
    assert normalize_ws(top["excerpt"].rstrip(" …")) in normalize_ws(doc[top["excerpt_page"] - 1].get_text())
    assert top["highlights"] and top["highlights"][0]["page"] == top["excerpt_page"]
    # Insights cite only real results; pages come from our data, not the model.
    assert len(res["insights"]) >= 1
    ins = res["insights"][0]
    assert ins["result_ids"] == [top["id"]] and ins["pages"] == list(range(top["page_start"], top["page_end"] + 1))
    assert all(i["title"] != "Made up" for i in res["insights"])


def test_summary_failure_keeps_deterministic_explanations(handbook_pdf):
    def gen(prompt):
        if "For EACH passage id" in prompt:
            raise ApiErr(500, "boom")
        return default_generate(prompt)

    use(FakeModels(gen=lambda p: gen(p)))
    res, _ = run(handbook_pdf, "deployment rollout process")
    top = res["results"][0]
    assert top["why_relevant"] and top["summary"] == "" and top["findings"] == []


# --------------------------------------------------------------------------- fallback & consistency


def test_total_outage_matches_local_engine(handbook_pdf):
    local, _ = run(handbook_pdf, "deployment rollout and database migrations")
    use(FakeModels(embed_error=ApiErr(503), gen_error=ApiErr(503)))
    fallback, _ = run(handbook_pdf, "deployment rollout and database migrations")
    assert [r["title"] for r in fallback["results"]] == [r["title"] for r in local["results"]]
    assert [r["match_score"] for r in fallback["results"]] == [r["match_score"] for r in local["results"]]


def test_partial_failure_embeddings_ok_generation_down(handbook_pdf):
    use(FakeModels(gen_error=ApiErr(429, "quota")))
    res, _ = run(handbook_pdf, "deployment rollout process")
    assert res["results"] and res["results"][0]["why_relevant"]
    assert res["results"][0]["findings"] == []


def _shape(obj):
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in sorted(obj.items()) if k not in ("insights",)}
    if isinstance(obj, list):
        return "list"
    return type(obj).__name__


def test_response_is_provider_neutral(handbook_pdf):
    local, _ = run(handbook_pdf, "deployment rollout process")
    use(FakeModels())
    hybrid, _ = run(handbook_pdf, "deployment rollout process")
    assert _shape(local["results"][0]) == _shape(hybrid["results"][0])
    assert set(local) == set(hybrid)
    assert local["analysis"]["method"] == hybrid["analysis"]["method"]
    for payload in (local, hybrid):
        blob = json.dumps(payload).lower()
        for word in ("gemini", "google", "tf-idf", "tfidf", "local engine", "offline", "llm", "provider"):
            assert word not in blob, word


def test_stage_messages_identical_across_paths(handbook_pdf):
    def stages():
        doc = open_pdf(handbook_pdf)
        return [(e["stage"], e["detail"]) for e in analyze(doc, "t.pdf", "Student", "Beginner", "deployment rollout", [])
                if e["type"] == "stage"]

    local = stages()
    use(FakeModels())
    assert stages() == local


# --------------------------------------------------------------------------- Ask IntelliDoc


def _session(pdf, objective="deployment rollout process"):
    res, _ = run(pdf, objective)
    return store.get(res["session_id"]), res


def test_ask_citations_are_valid_and_renumbered(handbook_pdf):
    def gen(prompt):
        if "EVIDENCE" in prompt:
            ev = blocks(prompt, "E")
            dep = next(e for e, t in ev.items() if "Deployment" in t.split("\n")[0])
            return {"answer": f"Releases roll out gradually [{dep}]. Migrations must be backwards compatible [{dep}, E99]. "
                              "It also guarantees 99.9% uptime [E1].",
                    "supported": True, "citations": [dep, "E42"]}
        return default_generate(prompt)

    use(FakeModels(gen=gen))
    sess, res = _session(handbook_pdf)
    from app.gemini.chat import answer

    out = answer(sess, "How are releases rolled out?", gclient.get_service())
    assert out["supported"] is True
    assert "[1]" in out["answer"] and "E99" not in out["answer"] and "99.9%" not in out["answer"]
    assert len(out["citations"]) == 1
    c = out["citations"][0]
    sec = next(s for s in sess.sections if s.id == c["section_id"])
    assert "Deployment" in c["title"] and sec.page_start <= c["excerpt_page"] <= sec.page_end
    assert normalize_ws(c["excerpt"].rstrip(" …")) in normalize_ws(sec.text)
    assert c["result_id"] in {r["id"] for r in res["results"]}


def test_ask_unsupported_answer_is_honest(handbook_pdf):
    def gen(prompt):
        if "EVIDENCE" in prompt:
            return {"answer": "The founders started the company in 1998.", "supported": True, "citations": []}
        return default_generate(prompt)

    use(FakeModels(gen=gen))
    sess, _ = _session(handbook_pdf)
    from app.gemini.chat import NOT_FOUND, answer

    out = answer(sess, "When was the company founded?", gclient.get_service())
    assert out["supported"] is False and out["citations"] == [] and out["answer"] == NOT_FOUND


def test_ask_conversation_context_is_used_and_bounded(handbook_pdf):
    use(FakeModels())
    sess, _ = _session(handbook_pdf)
    from app.gemini.chat import answer
    from app.session import MAX_TURNS

    m = gclient.get_service()._client.models
    answer(sess, "How do database migrations work during a rollout?", gclient.get_service())
    answer(sess, "And why?", gclient.get_service())
    last = m.gen_prompts[-1]
    assert "EARLIER IN THIS CONVERSATION" in last and "database migrations" in last
    assert "Objective: deployment rollout process" in last  # original objective retained
    for i in range(MAX_TURNS + 3):
        answer(sess, f"question {i} about security keys", gclient.get_service())
    assert len(sess.history) == MAX_TURNS


def test_ask_section_reference_and_local_fallback(handbook_pdf):
    sess, _ = _session(handbook_pdf)  # Gemini off
    from app.gemini.chat import answer

    out = answer(sess, "Explain section 3 for a beginner", None)
    assert out["citations"] and "Pricing" in out["citations"][0]["title"]
    for c in out["citations"]:
        assert f"“{c['excerpt']}” [{c['n']}]" in out["answer"]  # verbatim, quoted, cited
    none = answer(sess, "What do medieval falconers feed their birds?", None)
    assert none["supported"] is False and none["citations"] == []


def test_ask_endpoint_and_expired_session(handbook_pdf):
    client = TestClient(app)
    r = client.post("/api/analyze", data={"persona": "Software Engineer", "expertise": "Intermediate",
                                          "objective": "deployment rollout process"},
                    files={"file": ("h.pdf", handbook_pdf, "application/pdf")})
    data = json.loads(r.text.strip().splitlines()[-1])["data"]
    sid = data["session_id"]
    ok = client.post(f"/api/session/{sid}/ask", json={"question": "How are deployments rolled out?"})
    assert ok.status_code == 200 and ok.json()["citations"]
    assert client.post("/api/session/nope/ask", json={"question": "hi there"}).json()["error"]["code"] == "session_expired"
    assert client.post(f"/api/session/{sid}/ask", json={"question": ""}).status_code == 400


def test_ask_generic_question_uses_reading_path_locally(handbook_pdf):
    sess, res = _session(handbook_pdf, "deployment rollout process")
    from app.gemini.chat import answer

    out = answer(sess, "What are the three most important findings?", None)
    assert out["supported"] and out["citations"]
    assert out["citations"][0]["result_id"] == res["results"][0]["id"]


def test_ask_retrieval_skips_boilerplate_unless_asked():
    from app.gemini.chat import retrieve
    from app.ranking import build_query
    from app.sections import Chunk, Section
    from app.session import Session

    def sec(i, title, text, boiler=False):
        return Section(f"s{i}", title, 1, [title], text, [0], [i], [], i, boiler)

    body = sec(1, "Results", "Our method improves accuracy on the benchmark by a wide margin. " * 5)
    refs = sec(2, "References", "Smith et al. Improving accuracy on the benchmark. Journal of Results. " * 5, True)
    chunks = [Chunk(0, body, 0, len(body.text), body.text), Chunk(1, refs, 0, len(refs.text), refs.text)]
    s = Session("x", "f.pdf", [body, refs], chunks, build_query("accuracy", "Researcher", "Advanced", []), [])
    assert retrieve(s, "How much does accuracy improve on the benchmark?", None)[0][0].section.title == "Results"
    assert retrieve(s, "Which references discuss benchmark accuracy?", None)[0][0].section.title == "References"
