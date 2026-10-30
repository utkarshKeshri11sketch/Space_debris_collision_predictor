"""One entry point for every model call: call_llm(system, messages, stream=False, json_mode=False).

FREE PROVIDERS ONLY. Never add a paid provider here.

Provider order (automatic fallback): groq -> gemini -> cerebras -> cached
  groq      Groq free tier, OpenAI-compatible, model llama-3.3-70b-versatile, key GROQ_API_KEY
  gemini    Google AI Studio free tier (OpenAI-compatible endpoint), key GEMINI_API_KEY
  cerebras  Cerebras free tier, OpenAI-compatible, Llama 3.3 70B, key CEREBRAS_API_KEY
  cached    saved responses in app/ai/cache/, zero API calls

LLM_PROVIDER picks where the chain starts (default "groq"); the remaining providers follow in the order
above, then "cached". LLM_PROVIDER=cached makes no network call at all. A provider without a key is
skipped. HTTP 429, timeouts (>15 s) and any other error move on to the next provider, and the failing
provider is skipped for AI_COOLDOWN_S seconds so a rate-limited free tier is not hammered.

Callers always have a deterministic template to fall back on, so call_llm raising LLMUnavailable is a normal,
handled outcome (it is what "cached mode with a cache miss" looks like).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

logger = logging.getLogger("orbitsentinel.ai.llm")

CACHE_DIR = Path(__file__).parent / "cache"
TIMEOUT_S = 15.0
ORDER = ["groq", "gemini", "cerebras"]


class LLMUnavailable(RuntimeError):
    """No provider (including the cache) could answer this call."""


# name -> (base_url, key env var, model env var, default model)
# Free-tier model names change often. Verified with real keys on 2026-10-30: Groq no longer serves
# llama-3.3-70b-versatile (its chat models were openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b),
# and gemini-2.5-flash works. The Cerebras default is UNVERIFIED (no key was available); override any of
# them with GROQ_MODEL / GEMINI_MODEL / CEREBRAS_MODEL.
_OPENAI_COMPAT: dict[str, tuple[str, str, str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "CEREBRAS_MODEL", "llama-3.3-70b"),
}

Messages = Sequence[dict[str, str]]
_down_until: dict[str, float] = {}
_clients: dict[tuple[str, str], Any] = {}


# ----------------------------------------------------------------------------------------- cache


def _cache_path(key: str) -> Path | None:
    """cache_key -> file under app/ai/cache/. Rejects anything that could escape the folder."""
    safe = re.sub(r"[^a-zA-Z0-9_./-]+", "_", key).strip("/.")
    if not safe or ".." in safe:
        return None
    return CACHE_DIR / f"{safe}.txt"


def cache_read(key: str | None) -> str | None:
    path = _cache_path(key) if key else None
    return path.read_text(encoding="utf-8").strip() if path and path.exists() else None


def cache_find(prefix: str) -> str | None:
    """First saved response whose key starts with `prefix` (entries are named <key>-<facts hash>)."""
    base = _cache_path(prefix)
    if base is None:
        return None
    hit = next(iter(sorted(base.parent.glob(base.stem + "-*.txt"))), None)
    return hit.read_text(encoding="utf-8").strip() if hit else None


def cache_write(key: str, text: str) -> None:
    path = _cache_path(key)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------- providers


def _client(name: str):
    base_url, key_env, _, _ = _OPENAI_COMPAT[name]
    key = os.environ.get(key_env, "")
    if (name, key) not in _clients:
        from openai import OpenAI  # lazy: only needed when a live provider is used

        _clients[(name, key)] = OpenAI(api_key=key, base_url=base_url, timeout=TIMEOUT_S, max_retries=0)
    return _clients[(name, key)]


def _model(name: str) -> str:
    _, _, model_env, default = _OPENAI_COMPAT[name]
    return os.environ.get(model_env, default)


def _request(name: str, system: str, messages: Messages, json_mode: bool, max_tokens: int, stream: bool) -> dict:
    kwargs: dict[str, Any] = {
        "model": _model(name),
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": stream,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    # Reasoning models spend max_tokens on hidden thinking, which can leave an empty answer: keep it minimal.
    if name == "groq" and kwargs["model"].startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = "low"
    elif name == "gemini":
        kwargs["extra_body"] = {"reasoning_effort": "none"}
    return kwargs


def _live_complete(name: str, system: str, messages: Messages, json_mode: bool, max_tokens: int) -> str:
    resp = _client(name).chat.completions.create(**_request(name, system, messages, json_mode, max_tokens, False))
    return (resp.choices[0].message.content or "").strip()


def _live_stream(name: str, system: str, messages: Messages, json_mode: bool, max_tokens: int) -> Iterator[str]:
    for chunk in _client(name).chat.completions.create(**_request(name, system, messages, json_mode, max_tokens, True)):
        if chunk.choices and (piece := chunk.choices[0].delta.content):
            yield piece


def _chain() -> list[str]:
    start = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    if start == "cached":
        return ["cached"]
    live = ORDER[ORDER.index(start):] + ORDER[: ORDER.index(start)] if start in ORDER else list(ORDER)
    return [*live, "cached"]


def _usable(name: str) -> bool:
    if name == "cached":
        return True
    if not os.environ.get(_OPENAI_COMPAT[name][1]):
        return False  # no key: skip silently
    return time.monotonic() >= _down_until.get(name, 0.0)


def _mark_down(name: str, exc: Exception) -> None:
    cooldown = float(os.environ.get("AI_COOLDOWN_S", "60"))
    if getattr(exc, "status_code", None) == 429:  # per-minute free-tier limits clear quickly
        cooldown = min(cooldown, 15.0)
    _down_until[name] = time.monotonic() + cooldown
    logger.warning("llm provider=%s failed (%s: %s); skipping it for %.0fs", name, type(exc).__name__, exc, cooldown)


def reset_state() -> None:
    """Forget cooldowns and clients (used by tests)."""
    _down_until.clear()
    _clients.clear()


def _words(text: str) -> Iterator[str]:
    yield from re.findall(r"\S+\s*", text)


# ----------------------------------------------------------------------------------------- public


def call_llm(
    system: str,
    messages: Messages,
    stream: bool = False,
    json_mode: bool = False,
    *,
    max_tokens: int | None = None,
    cache_key: str | None = None,
) -> str | Iterator[str]:
    """Ask the model. Returns the full text, or (stream=True) an iterator of text chunks.

    cache_key: stable name for this call (e.g. "negotiation/starlink-oneweb/agentA_1"). The "cached" provider
    uses it to find a saved response. Saving happens in generate.py, after the text has been validated
    (AI_RECORD_CACHE=1, used by scripts/build_ai_cache.py), so unvalidated model output is never cached.
    """
    max_tokens = max_tokens or int(os.environ.get("AI_MAX_TOKENS", "400"))
    if stream:
        return _stream(system, messages, json_mode, max_tokens, cache_key)
    for name in _chain():
        if not _usable(name):
            continue
        if name == "cached":
            if (saved := cache_read(cache_key)) is not None:
                logger.info("llm provider=cached key=%s", cache_key)
                return saved
            continue
        try:
            text = _live_complete(name, system, messages, json_mode, max_tokens)
        except Exception as exc:  # noqa: BLE001 - 429, timeout, auth, network: all mean "try the next one"
            _mark_down(name, exc)
            continue
        if text:
            logger.info("llm provider=%s", name)
            return text
    raise LLMUnavailable("no LLM provider answered (check API keys, or run with LLM_PROVIDER=cached)")


def _stream(system, messages, json_mode, max_tokens, cache_key) -> Iterator[str]:
    for name in _chain():
        if not _usable(name):
            continue
        if name == "cached":
            if (saved := cache_read(cache_key)) is not None:
                logger.info("llm provider=cached key=%s", cache_key)
                yield from _words(saved)
                return
            continue
        sent: list[str] = []
        try:
            for piece in _live_stream(name, system, messages, json_mode, max_tokens):
                sent.append(piece)
                yield piece
        except Exception as exc:  # noqa: BLE001
            _mark_down(name, exc)
            if sent:  # already partly delivered: cannot restart on another provider without duplicating text
                return
            continue
        if sent:
            logger.info("llm provider=%s (stream)", name)
            return
    raise LLMUnavailable("no LLM provider answered (check API keys, or run with LLM_PROVIDER=cached)")


async def acall_llm(system: str, messages: Messages, json_mode: bool = False, **kwargs: Any) -> str:
    """Async wrapper (the SDK is blocking, so run it in a worker thread)."""
    return await asyncio.to_thread(call_llm, system, messages, False, json_mode, **kwargs)


LlmFn = Callable[..., Any]  # signature-compatible with acall_llm; tests inject fakes


async def stream_words(text: str, delay_s: float = 0.0):
    """Stream finished text word by word (matches the frontend mock's token granularity)."""
    for chunk in _words(text):
        yield chunk
        if delay_s:
            await asyncio.sleep(delay_s)
