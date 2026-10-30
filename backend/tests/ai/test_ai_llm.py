"""Provider chain: fallback order, rate limits, cached mode with no keys."""
import pytest

from app.ai import llm

MSG = [{"role": "user", "content": "hi"}]


class RateLimit(Exception):
    status_code = 429


def keys(monkeypatch, **names):
    for k, v in names.items():
        monkeypatch.setenv(f"{k.upper()}_API_KEY", v)


def fake_live(monkeypatch, behaviour):
    calls = []

    def _live(name, system, messages, json_mode, max_tokens):
        calls.append(name)
        out = behaviour[name]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(llm, "_live_complete", _live)
    return calls


def test_default_chain_is_groq_gemini_cerebras_then_cached(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    assert llm._chain() == ["groq", "gemini", "cerebras", "cached"]


def test_chain_starts_at_chosen_provider_and_wraps(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert llm._chain() == ["gemini", "cerebras", "groq", "cached"]


def test_429_on_groq_falls_through_to_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    keys(monkeypatch, groq="g", gemini="m")
    calls = fake_live(monkeypatch, {"groq": RateLimit("too many"), "gemini": "from gemini"})
    assert llm.call_llm("sys", MSG) == "from gemini"
    assert calls == ["groq", "gemini"]


def test_failed_provider_is_skipped_during_cooldown(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    keys(monkeypatch, groq="g", gemini="m")
    calls = fake_live(monkeypatch, {"groq": RateLimit("x"), "gemini": "ok"})
    llm.call_llm("s", MSG)
    llm.call_llm("s", MSG)
    assert calls == ["groq", "gemini", "gemini"]


def test_timeout_and_generic_errors_also_fall_through(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    keys(monkeypatch, groq="g", gemini="m", cerebras="c")
    calls = fake_live(monkeypatch, {"groq": TimeoutError("slow"), "gemini": RuntimeError("500"), "cerebras": "third"})
    assert llm.call_llm("s", MSG) == "third" and calls == ["groq", "gemini", "cerebras"]


def test_providers_without_keys_are_skipped_silently(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    keys(monkeypatch, cerebras="c")
    calls = fake_live(monkeypatch, {"cerebras": "only one with a key"})
    assert llm.call_llm("s", MSG) == "only one with a key" and calls == ["cerebras"]


def test_everything_down_falls_back_to_cache_then_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    keys(monkeypatch, groq="g")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    llm.cache_write("demo/answer", "saved text")
    fake_live(monkeypatch, {"groq": RateLimit("x")})
    assert llm.call_llm("s", MSG, cache_key="demo/answer") == "saved text"
    llm.reset_state()
    with pytest.raises(llm.LLMUnavailable):
        llm.call_llm("s", MSG, cache_key="never/saved")


def test_cached_mode_makes_zero_live_calls_and_needs_no_keys(monkeypatch, tmp_path):
    # the autouse fixture makes any live call raise AssertionError
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    llm.cache_write("k", "cached answer")
    assert llm.call_llm("s", MSG, cache_key="k") == "cached answer"
    assert "".join(llm.call_llm("s", MSG, stream=True, cache_key="k")) == "cached answer"
    with pytest.raises(llm.LLMUnavailable):
        llm.call_llm("s", MSG)  # no cache key -> nothing to replay


def test_cache_keys_cannot_escape_the_cache_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    inside = llm._cache_path("../../etc/passwd")
    assert inside is not None and (tmp_path / "cache") in inside.parents  # leading ../ is stripped, never followed
    assert llm._cache_path("a/../../b") is None
    assert llm._cache_path("") is None
    assert llm._cache_path("ask/why-risky").parent.name == "ask"


def test_request_shape_json_mode_and_reasoning_models():
    req = llm._request("groq", "sys", MSG, True, 123, False)
    assert req["response_format"] == {"type": "json_object"} and req["max_tokens"] == 123
    assert req["messages"][0] == {"role": "system", "content": "sys"} and req["reasoning_effort"] == "low"
    assert llm._request("gemini", "s", MSG, False, 10, False)["extra_body"] == {"reasoning_effort": "none"}
    assert "response_format" not in llm._request("cerebras", "s", MSG, False, 10, False)


def test_timeout_is_15_seconds_and_models_are_env_overridable(monkeypatch):
    assert llm.TIMEOUT_S == 15.0
    monkeypatch.setenv("GROQ_MODEL", "some/other-model")
    assert llm._model("groq") == "some/other-model"


def test_shipped_cache_has_the_demo_entries():
    for key in ("negotiation/starlink-oneweb/mediator", "negotiation/starlink-oneweb/agentA_1", "brief/iss-cosmos", "ask/why-is-this-risky"):
        assert llm.cache_find(key), key
