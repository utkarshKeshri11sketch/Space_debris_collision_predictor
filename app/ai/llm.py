"""LLM access with provider failover: Bedrock -> Gemini -> (callers' deterministic templates).

Every public call either returns text or raises LLMUnavailable; callers always have a template to
fall back to, so the demo never depends on a network service. Providers are synchronous (boto3 and
urllib are blocking); the async helpers run them in a worker thread.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import AsyncIterator, Iterator, Protocol

from .config import AiConfig


class LLMUnavailable(RuntimeError):
    """No provider could produce text (misconfigured, offline, throttled, or in cooldown)."""


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class BedrockProvider:
    name = "bedrock"

    def __init__(self, cfg: AiConfig):
        self.cfg = cfg
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy: boto3 ships with the Lambda runtime but not necessarily local dev
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.cfg.bedrock_region,
                config=Config(read_timeout=self.cfg.timeout_s, retries={"max_attempts": 1}),
            )
        return self._client

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self._get_client().converse(
            modelId=self.cfg.bedrock_model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()


class GeminiProvider:
    """Plain REST call (stdlib only) to keep the Lambda package small."""

    name = "gemini"

    def __init__(self, cfg: AiConfig):
        self.cfg = cfg

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        if not self.cfg.gemini_api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.cfg.gemini_model}:generateContent"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            # Key goes in a header, never in the URL, so it cannot leak into logs.
            headers={"Content-Type": "application/json", "x-goog-api-key": self.cfg.gemini_api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as r:
                data = json.load(r)
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
            raise LLMUnavailable(f"gemini failed: {exc}") from exc


class ResponseCache:
    """Memory cache with optional on-disk record/replay (set AI_CACHE_DIR). Keyed by prompt hash."""

    def __init__(self, directory: str = ""):
        self._mem: dict[str, str] = {}
        self._dir = Path(directory) if directory else None
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(system: str, user: str) -> str:
        return hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()

    def get(self, key: str) -> str | None:
        if key in self._mem:
            return self._mem[key]
        if self._dir and (path := self._dir / f"{key}.txt").exists():
            self._mem[key] = path.read_text(encoding="utf-8")
            return self._mem[key]
        return None

    def put(self, key: str, text: str) -> None:
        self._mem[key] = text
        if self._dir:
            (self._dir / f"{key}.txt").write_text(text, encoding="utf-8")


class LLM:
    def __init__(self, cfg: AiConfig | None = None, providers: list[Provider] | None = None):
        self.cfg = cfg or AiConfig.from_env()
        self.cache = ResponseCache(self.cfg.cache_dir)
        self._down_until: dict[str, float] = {}
        self.providers = providers if providers is not None else self._build_providers()

    def _build_providers(self) -> list[Provider]:
        order = {"auto": ["bedrock", "gemini"], "bedrock": ["bedrock"], "gemini": ["gemini"]}.get(
            self.cfg.provider, []  # "cached"/"none"/unknown: replay + templates only
        )
        make = {"bedrock": BedrockProvider, "gemini": GeminiProvider}
        return [make[n](self.cfg) for n in order]

    def complete(self, system: str, user: str, *, max_tokens: int | None = None, use_cache: bool = True) -> str:
        key = ResponseCache.key(system, user)
        # A recorded answer is replayed only when every live provider fails; fresh text is preferred.
        for provider in self.providers:
            if time.monotonic() < self._down_until.get(provider.name, 0.0):
                continue
            try:
                text = provider.complete(system, user, max_tokens or self.cfg.max_tokens)
            except Exception:  # noqa: BLE001 - any SDK/network error means "try the next provider"
                self._down_until[provider.name] = time.monotonic() + self.cfg.cooldown_s
                continue
            if text:
                if use_cache:
                    self.cache.put(key, text)
                return text
        if use_cache and (cached := self.cache.get(key)) is not None:
            return cached
        raise LLMUnavailable("no LLM provider available")

    async def acomplete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        return await asyncio.to_thread(self.complete, system, user, max_tokens=max_tokens)


def chunk_words(text: str) -> Iterator[str]:
    """Split into word+trailing-space chunks, matching the frontend mock's token granularity."""
    yield from re.findall(r"\S+\s*", text)


async def stream_text(text: str, delay_s: float = 0.0) -> AsyncIterator[str]:
    """Stream finished text word by word.

    Answers are short (<=400 tokens) and must be grounding-checked in full before the user sees
    them, so we complete first and then stream rather than relaying provider tokens.
    """
    for chunk in chunk_words(text):
        yield chunk
        if delay_s:
            await asyncio.sleep(delay_s)


_default: LLM | None = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM()
    return _default
