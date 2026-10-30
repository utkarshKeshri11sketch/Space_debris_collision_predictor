"""Small env-driven settings that are not provider selection (that lives in llm.py).

Variables (see app/ai/.env.example): LLM_PROVIDER, GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY,
GROQ_MODEL / GEMINI_MODEL / CEREBRAS_MODEL, AI_COOLDOWN_S, AI_MAX_TOKENS, AI_RECORD_CACHE,
AI_NEGOTIATION_PACE_S, AI_NEGOTIATION_REBUTTALS, AI_BRIEF_MODE.
"""
from __future__ import annotations

import os


def negotiation_pace_s() -> float:
    """Pause between streamed negotiation events so the UI animates like a live chat."""
    return float(os.environ.get("AI_NEGOTIATION_PACE_S", "0.7"))


def rebuttals_enabled() -> bool:
    return os.environ.get("AI_NEGOTIATION_REBUTTALS", "1") != "0"


def brief_uses_llm() -> bool:
    return os.environ.get("AI_BRIEF_MODE", "llm").lower() == "llm"
