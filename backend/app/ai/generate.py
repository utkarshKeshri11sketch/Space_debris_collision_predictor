"""Grounded text generation: ask the model, validate, retry once, else use the deterministic template.

The model only phrases things. Its text must (1) use only numbers that exist in the FACTS we gave it
(grounding.py), (2) contain what the caller requires (for example the recommended mover's name), (3) end
cleanly and stay short. Otherwise we ask once more naming the problem, and if that also fails we return the
template, so what the user sees is always consistent with the computed data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .grounding import ungrounded_numbers
from .llm import LLMUnavailable, acall_llm, cache_write, call_llm

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_WORDS = 120


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Prompts live in app/ai/prompts/<name>.md so they can be tuned without code changes."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


# Some models emit non-breaking hyphens/spaces and curly quotes inside names and units.
_UNICODE_FIXES = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
    "‘": "'", "’": "'", "“": '"', "”": '"',
})


def clean(text: str) -> str:
    text = text.translate(_UNICODE_FIXES)
    text = re.sub(r"[*_`#>]+", "", text).strip().strip('"')
    text = re.sub(r"^(agent [ab]|mediator|sentinel|assistant)\s*(\([^)]*\))?\s*:\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


def problems(text: str, facts: Any, names: Iterable[str], must_include: Sequence[str] = ()) -> list[str]:
    """Why `text` is not acceptable (empty list = fine). must_include: regexes that must each match."""
    if not text:
        return ["empty answer"]
    out = []
    if text[-1] not in ".!?)\"'":  # ends mid-sentence: the model ran out of tokens
        out.append("the answer was cut off; finish the last sentence")
    if len(text.split()) > MAX_WORDS:
        out.append(f"longer than {MAX_WORDS} words")
    if bad := ungrounded_numbers(text, facts, names):
        out.append("numbers not in FACTS: " + ", ".join(f"{n:g}" for n in bad))
    for pattern in must_include:
        if not re.search(pattern, text, re.IGNORECASE):
            out.append(f"it must mention: {pattern}")
    return out


def _round_hours(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (round(v) if k.startswith("hours") and isinstance(v, (int, float)) else _round_hours(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_hours(v) for v in value]
    return value


def keyed(cache_key: str | None, facts: Any, task: str) -> str | None:
    """Cache entries are tied to the facts they were written for: <key>-<hash>. Saved text is therefore only
    replayed for the same situation (hours are rounded so a few minutes of drift does not matter)."""
    if not cache_key:
        return None
    blob = json.dumps([_round_hours(facts), task], sort_keys=True, ensure_ascii=False, default=str)
    return f"{cache_key}-{hashlib.sha1(blob.encode()).hexdigest()[:8]}"


def _record(cache_key: str | None, text: str) -> None:
    """With AI_RECORD_CACHE=1 (scripts/build_ai_cache.py), save a VALIDATED answer for the offline demo."""
    if cache_key and os.environ.get("AI_RECORD_CACHE") == "1":
        cache_write(cache_key, text)


def _user(facts: Any, task: str) -> str:
    # Compact JSON: free tiers cap tokens per minute (Groq: 8,000), so every wasted token counts.
    return f"FACTS:\n{json.dumps(facts, separators=(',', ':'), ensure_ascii=False)}\n\n{task}"


def _retry_messages(user: str, bad_text: str, issues: list[str]) -> list[dict]:
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": bad_text},
        {"role": "user", "content": f"Rejected ({'; '.join(issues)}). Rewrite it, using only numbers that appear in FACTS."},
    ]


async def generate_grounded(
    llm: Callable[..., Any] | None, system: str, facts: Any, task: str, names: Iterable[str], fallback: str,
    *, cache_key: str | None = None, max_tokens: int = 300, retries: int = 1, must_include: Sequence[str] = (),
) -> str:
    """Never raises: any provider failure or invalid output yields `fallback`."""
    llm = llm or acall_llm
    names = list(names)
    cache_key = keyed(cache_key, facts, task)
    user = _user(facts, task)
    messages = [{"role": "user", "content": user}]
    for attempt in range(retries + 1):
        try:
            text = clean(await llm(system, messages, max_tokens=max_tokens, cache_key=cache_key if attempt == 0 else None))
        except Exception:  # noqa: BLE001 - LLMUnavailable or a broken provider must never break the demo
            return fallback
        issues = problems(text, facts, names, must_include)
        if not issues:
            _record(cache_key, text)
            return text
        messages = _retry_messages(user, text, issues)
    return fallback


def _call_sync(system: str, messages: list, *, max_tokens: int, cache_key: str | None) -> str:
    return call_llm(system, messages, max_tokens=max_tokens, cache_key=cache_key)  # type: ignore[return-value]


def generate_grounded_sync(
    system: str, facts: Any, task: str, names: Iterable[str], fallback: str,
    *, cache_key: str | None = None, max_tokens: int = 300, retries: int = 1, llm: Callable[..., str] | None = None,
    must_include: Sequence[str] = (),
) -> str:
    """Blocking twin of generate_grounded (the brief is built inside a normal sync route)."""
    llm = llm or _call_sync
    names = list(names)
    cache_key = keyed(cache_key, facts, task)
    user = _user(facts, task)
    messages = [{"role": "user", "content": user}]
    for attempt in range(retries + 1):
        try:
            text = clean(llm(system, messages, max_tokens=max_tokens, cache_key=cache_key if attempt == 0 else None))
        except Exception:  # noqa: BLE001
            return fallback
        issues = problems(text, facts, names, must_include)
        if not issues:
            _record(cache_key, text)
            return text
        messages = _retry_messages(user, text, issues)
    return fallback
