"""OrbitSentinel AI layer: negotiator, Sentinel brief and Ask Sentinel. Free LLM providers only.

Public entry points (plain JSON-shaped dicts, frontend camelCase field names, no dependency on app/models.py):

    negotiate(conjunction, sat_a, sat_b, options)        async iterator of NegotiationEvent dicts
    negotiate_override(..., rejected)                    same, after a human rejects the recommendation
    brief(target, conjunctions) / generate_brief(detail) str for ConjunctionDetail.brief / dashboard
    ask(question, context) / ask_stream(question, ctx)   str / async iterator of text chunks
    call_llm(system, messages, stream, json_mode)        the single LLM entry point (groq>gemini>cerebras>cached)
"""
from .ask import ask, ask_stream
from .brief import brief, conjunction_brief, generate_brief, overview_brief
from .llm import LLMUnavailable, call_llm
from .negotiator import negotiate, negotiate_override

__all__ = [
    "LLMUnavailable", "ask", "ask_stream", "brief", "call_llm", "conjunction_brief", "generate_brief",
    "negotiate", "negotiate_override", "overview_brief",
]
