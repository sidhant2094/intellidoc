"""Generation reliability: non-empty text, MAX_TOKENS, transient errors, retries/backoff, cooldown,
fallback model, local fallback, and embeddings staying independent. Fully mocked."""

from __future__ import annotations

import pytest

from app.gemini import client as gclient
from app.gemini.client import GeminiUnavailable
from app.pdf_extract import open_pdf
from app.pipeline import analyze
from tests.fakes import ApiErr, FakeModels, default_generate, make_service, response

PRIMARY, FALLBACK = "gemini-3.1-flash-lite", "gemini-3.6-flash"
MODELS = (PRIMARY, FALLBACK, "gemini-embedding-001")


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(gclient.time, "sleep", lambda s: waits.append(s))
    return waits


def svc_with(per_model=None, fallback=FALLBACK, thinking=(), **kw):
    m = FakeModels(available=MODELS, per_model=per_model or {}, thinking=thinking, **kw)
    gclient.set_service(make_service(m, model=PRIMARY, fallback=fallback))
    return gclient.get_service(), m


def ok(text="hello"):
    return lambda prompt, cfg: response(text)


def fail(exc_factory):
    def f(prompt, cfg):
        raise exc_factory()
    return f


def calls_to(m: FakeModels, model: str) -> int:
    return sum(1 for name, _ in m.gen_calls if name == model)


# --------------------------------------------------------------------------- responses


def test_successful_nonempty_generation_ignores_thought_parts(sleeps):
    svc, _ = svc_with({PRIMARY: lambda p, c: response("The answer.", thought="internal reasoning")})
    gen = svc.generate("sys", "prompt", 100)
    assert gen.text == "The answer." and gen.model == PRIMARY and gen.finish_reason == "STOP"


def test_empty_response_is_not_success_and_uses_fallback(sleeps):
    svc, m = svc_with({PRIMARY: lambda p, c: response(""), FALLBACK: ok("from fallback")})
    assert svc.generate("s", "p", 100).text == "from fallback"
    assert calls_to(m, PRIMARY) == 1


def test_empty_response_without_fallback_raises(sleeps):
    svc, _ = svc_with({PRIMARY: lambda p, c: response(None, thought="only thinking")}, fallback="")
    with pytest.raises(GeminiUnavailable, match="empty response"):
        svc.generate("s", "p", 100)


def test_max_tokens_retries_once_with_larger_budget(sleeps):
    budgets = []

    def gen(prompt, cfg):
        budgets.append(cfg.max_output_tokens)
        return response(None, finish="MAX_TOKENS") if len(budgets) == 1 else response('{"ok": true}')

    svc, _ = svc_with({PRIMARY: gen})
    assert svc.generate_json("s", "p", {"type": "object"}, 300) == {"ok": True}
    assert budgets[1] == budgets[0] * 2


def test_repeated_max_tokens_is_a_failure(sleeps):
    svc, _ = svc_with({PRIMARY: lambda p, c: response('{"partial": ', finish="MAX_TOKENS")}, fallback="")
    with pytest.raises(GeminiUnavailable, match="MAX_TOKENS"):
        svc.generate("s", "p", 100)


def test_safety_block_does_not_try_fallback(sleeps):
    svc, m = svc_with({PRIMARY: lambda p, c: response(None, blocked=True), FALLBACK: ok()})
    with pytest.raises(GeminiUnavailable, match="blocked"):
        svc.generate("s", "p", 100)
    assert calls_to(m, FALLBACK) == 0


def test_thinking_config_only_for_thinking_models(sleeps):
    svc, m = svc_with({PRIMARY: ok(), FALLBACK: ok()}, thinking=(PRIMARY,))
    svc.generate("s", "p", 100)
    cfg = m.gen_calls[-1][1]
    assert cfg.thinking_config is not None and cfg.max_output_tokens == 100 + gclient.THINKING_HEADROOM
    svc2, m2 = svc_with({PRIMARY: ok()}, thinking=())
    svc2.generate("s", "p", 100)
    assert m2.gen_calls[-1][1].thinking_config is None and m2.gen_calls[-1][1].max_output_tokens == 100


def test_model_rejecting_thinking_is_retried_without_it(sleeps):
    def gen(prompt, cfg):
        if cfg.thinking_config is not None:
            raise ApiErr(400, "Thinking level is not supported for this model.")
        return response("plain")

    svc, _ = svc_with({PRIMARY: gen}, thinking=(PRIMARY,), fallback="")
    assert svc.generate("s", "p", 100).text == "plain"
    assert svc.generate("s", "p", 100).text == "plain"  # remembered: no second rejection needed


# --------------------------------------------------------------------------- errors, retries, cooldown


@pytest.mark.parametrize("code", [500, 503, 504])
def test_transient_errors_retry_with_backoff_then_fallback(code, sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(code, "high demand")), FALLBACK: ok("fallback text")})
    assert svc.generate("s", "p", 100).text == "fallback text"
    assert calls_to(m, PRIMARY) == 3  # 1 + 2 bounded retries
    assert len(sleeps) == 2 and 1.0 <= sleeps[0] < 1.6 and 2.0 <= sleeps[1] < 2.6  # exponential + jitter
    assert svc._cooling(f"model:{PRIMARY}") and not svc._cooling(f"model:{FALLBACK}")
    assert svc.available("generate")  # still available through the fallback model


def test_transient_then_success_on_same_model(sleeps):
    n = {"i": 0}

    def flaky(prompt, cfg):
        n["i"] += 1
        if n["i"] == 1:
            raise ApiErr(503, "high demand")
        return response("recovered")

    svc, m = svc_with({PRIMARY: flaky})
    assert svc.generate("s", "p", 100).text == "recovered"
    assert calls_to(m, FALLBACK) == 0 and not svc._cooling(f"model:{PRIMARY}")


def test_cooldown_prevents_hammering_failing_model(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(503)), FALLBACK: ok()})
    svc.generate("s", "p", 100)
    svc.generate("s", "p", 100)
    assert calls_to(m, PRIMARY) == 3  # second request skipped the cooled-down primary entirely
    assert calls_to(m, FALLBACK) == 2


def test_all_models_failing_raises_and_then_skips_without_calls(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(503)), FALLBACK: fail(lambda: ApiErr(504))})
    with pytest.raises(GeminiUnavailable):
        svc.generate("s", "p", 100)
    before = len(m.gen_calls)
    assert not svc.available("generate")
    with pytest.raises(GeminiUnavailable):
        svc.generate("s", "p", 100)
    assert len(m.gen_calls) == before


def test_rate_limit_long_delay_not_retried_but_fallback_tried(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(429, "quota", retry="40s")), FALLBACK: ok("fb")})
    assert svc.generate("s", "p", 100).text == "fb"
    assert calls_to(m, PRIMARY) == 1 and sleeps == []
    assert svc._cooldown[f"model:{PRIMARY}"] - gclient.time.monotonic() > 30


def test_rate_limit_short_retry_after_header_is_honored(sleeps):
    n = {"i": 0}

    def gen(prompt, cfg):
        n["i"] += 1
        if n["i"] == 1:
            raise ApiErr(429, "slow down", retry_after="2")
        return response("after wait")

    svc, _ = svc_with({PRIMARY: gen})
    assert svc.generate("s", "p", 100).text == "after wait"
    assert 2.0 <= sleeps[0] < 2.6


def test_missing_model_404_is_benched_and_fallback_used(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(404, "no longer available to new users")), FALLBACK: ok()})
    svc.generate("s", "p", 100)
    svc.generate("s", "p", 100)
    assert calls_to(m, PRIMARY) == 1
    assert svc._cooldown[f"model:{PRIMARY}"] - gclient.time.monotonic() > 3000


def test_bad_request_does_not_fall_back(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(400, "invalid argument")), FALLBACK: ok()})
    with pytest.raises(GeminiUnavailable):
        svc.generate("s", "p", 100)
    assert calls_to(m, FALLBACK) == 0


# --------------------------------------------------------------------------- independence & pipeline


def test_embeddings_keep_working_while_generation_is_down(sleeps):
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(503)), FALLBACK: fail(lambda: ApiErr(503))})
    with pytest.raises(GeminiUnavailable):
        svc.generate("s", "p", 100)
    assert not svc.available("generate")
    assert svc.available("embed")
    vecs = svc.embed(["deployment rollout", "billing"], "RETRIEVAL_DOCUMENT")
    assert vecs.shape[0] == 2 and m.embed_calls == [2]


def test_analysis_uses_fallback_model_when_primary_overloaded(handbook_pdf, sleeps):
    def fb(prompt, cfg):
        return response(__import__("json").dumps(default_generate(prompt)))

    svc_with({PRIMARY: fail(lambda: ApiErr(503, "high demand")), FALLBACK: fb})
    doc = open_pdf(handbook_pdf)
    res = next(e["data"] for e in analyze(doc, "h.pdf", "Software Engineer", "Intermediate",
                                         "deployment rollout process", []) if e["type"] == "result")
    top = res["results"][0]
    assert "Deployment" in top["title"]
    assert top["summary"] and top["signals"]["contextual"] > 0  # reranked + summarized via fallback


def test_analysis_falls_back_to_local_when_generation_down(handbook_pdf, sleeps):
    doc = open_pdf(handbook_pdf)
    local = next(e["data"] for e in analyze(doc, "h.pdf", "Software Engineer", "Intermediate",
                                           "deployment rollout process", []) if e["type"] == "result")
    svc, m = svc_with({PRIMARY: fail(lambda: ApiErr(503)), FALLBACK: fail(lambda: ApiErr(503))})
    doc = open_pdf(handbook_pdf)
    res = next(e["data"] for e in analyze(doc, "h.pdf", "Software Engineer", "Intermediate",
                                         "deployment rollout process", []) if e["type"] == "result")
    assert res["results"] and res["results"][0]["title"] == local["results"][0]["title"]
    assert res["results"][0]["summary"] == "" and res["results"][0]["why_relevant"]
    assert m.embed_calls  # semantic retrieval still used embeddings
    assert len(m.gen_calls) == 6  # one failed rerank attempt chain per model; summary call skipped (cooled down)
