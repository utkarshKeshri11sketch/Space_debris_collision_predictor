"""OWNER: AI agent (branch be-ai). Ask Sentinel: grounded Q&A streamed as text tokens."""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from .. import mock_data


async def ask(question: str) -> AsyncIterator[str]:
    """Yield answer text chunks. Ground answers ONLY in computed data (screening/maneuver/cascade output)."""
    q = question.lower()
    if "iss" in q or "safe" in q:
        answer = "In this sample screening, the ISS has one critical conjunction: a COSMOS 1408 fragment at 412 m, with collision probability 3.1 × 10⁻⁴. Review the 0.42 m/s prograde option, which increases modeled separation to 4.2 km. A human operator must approve any maneuver."
    elif "cascade" in q or "debris" in q:
        answer = "The Cascade Lab models a breakup as seeded fragments spreading along the parent orbit. The 25-year sample includes two secondary collisions. This is an approximate visual model, not a forecast of actual collisions. Select SL-16 R/B and run a collision scenario to explore it."
    elif "negot" in q:
        answer = "STARLINK-31502 and ONEWEB-0461 can both maneuver. Their sample negotiation compares fuel efficiency, mission continuity, operator readiness and risk reduction. Start the session in Negotiator; the agreement remains pending human flight approval."
    else:
        answer = mock_data.SENTINEL_BRIEF
    for chunk in re.findall(r"\S+\s*", answer):
        await asyncio.sleep(0.02)
        yield chunk
