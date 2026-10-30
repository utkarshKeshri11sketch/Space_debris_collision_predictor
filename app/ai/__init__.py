"""OrbitSentinel AI layer: negotiator, Sentinel brief and Ask Sentinel.

Public entry points (all take/return plain JSON-shaped dicts using the frontend's camelCase field
names, so they do not depend on app/models.py):

    negotiate(context)        -> async iterator of NegotiationEvent dicts
    conjunction_brief(detail) -> str   (template; no network)
    generate_brief(detail)    -> str   (LLM with template fallback, cached)
    overview_brief(items)     -> str   (dashboard-level summary, template)
    ask_stream(question, ctx) -> async iterator of answer text chunks
"""
from .ask import ask_stream
from .brief import conjunction_brief, generate_brief, overview_brief
from .negotiator import negotiate

__all__ = ["ask_stream", "conjunction_brief", "generate_brief", "negotiate", "overview_brief"]
