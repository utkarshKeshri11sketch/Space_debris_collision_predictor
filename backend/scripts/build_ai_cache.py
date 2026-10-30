"""Regenerate app/ai/cache/ so the demo works with zero API calls (LLM_PROVIDER=cached).

    python scripts/build_ai_cache.py                 # uses the live providers configured in the environment
    LLM_PROVIDER=gemini python scripts/build_ai_cache.py

Runs the demo scenarios through the real pipeline against a live provider (GROQ_API_KEY / GEMINI_API_KEY /
CEREBRAS_API_KEY) and saves every VALIDATED model answer, keyed by call:
    negotiation/starlink-oneweb/*   Starlink x OneWeb (Starlink should move)
    negotiation/iss-cosmos/*        ISS x debris (ISS decides alone)
    brief/iss-cosmos                the Sentinel brief for ISS x COSMOS 1408 DEB
    ask/<question>                  the common Ask Sentinel questions
At replay time the saved text is validated again against the live facts, so a stale entry is ignored in
favour of the built-in template rather than shown with wrong numbers.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["AI_RECORD_CACHE"] = "1"

from app.ai import llm  # noqa: E402
from app.ai.ask import ask  # noqa: E402
from app.ai.brief import brief  # noqa: E402
from app.ai.demo import DEMO_QUESTIONS, scenarios  # noqa: E402
from app.ai.negotiator import negotiate  # noqa: E402


def _live_provider() -> str | None:
    return next((n for n in llm._chain() if n != "cached" and os.environ.get(llm._OPENAI_COMPAT[n][1])), None)


async def main() -> int:
    provider = _live_provider()
    if provider is None:
        print("No live provider: set GROQ_API_KEY (or GEMINI_API_KEY / CEREBRAS_API_KEY) and do not use LLM_PROVIDER=cached.")
        return 1
    now = datetime.now(timezone.utc)
    sc = scenarios(now)
    before = {p for p in llm.CACHE_DIR.rglob("*.txt")}

    async def settle() -> None:
        """Free tiers limit tokens per minute: pause between stages and forget any rate-limit cooldown."""
        await asyncio.sleep(float(os.environ.get("BUILD_PAUSE_S", "20")))
        llm._down_until.clear()

    negotiation = None
    for name, s in sc.items():
        events = [e async for e in negotiate(s["conjunction"], s["sat_a"], s["sat_b"], s["options"], pace_s=0)]
        print(f"negotiation/{name}: {len(events)} events, ends with {events[-1]['type']}")
        if name == "starlink-oneweb" and events[-1]["type"] == "agreement":  # lets Ask answer "who should move?"
            negotiation = {"agreement": events[-1], "reasoning": next(e["text"] for e in events if e["type"] == "message" and e["speaker"] == "mediator" and e["round"] == 3)}
        await settle()

    conjunctions = [s["conjunction"] for s in sc.values()]
    text = brief("ISS", conjunctions, now=now, use_llm=True)
    print(f"brief: {text[:110]}...")

    context = {"conjunctions": conjunctions, "negotiation": negotiation}
    for q in DEMO_QUESTIONS:
        await settle()
        print(f"ask {q!r}: {(await ask(q, context, now=now))[:90]}...")

    files = sorted(p for p in llm.CACHE_DIR.rglob("*.txt"))
    meta = {"generatedAt": now.isoformat(), "provider": provider, "model": llm._model(provider), "files": len(files),
            "note": "LLM answers recorded after validation; regenerate with scripts/build_ai_cache.py"}
    (llm.CACHE_DIR / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(files)} cache files ({len(set(files) - before)} new/updated) from {provider}:{meta['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
