"""OWNER: AI agent (branch be-ai). Replace the stub body; keep the signature."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .. import mock_data
from ..models import ConjunctionDetail


async def negotiate(conjunction: ConjunctionDetail) -> AsyncIterator[dict]:
    """Yield NegotiationEvent dicts (see models.py: message | scores | agreement | error), paced for the UI.

    The router adds SSE framing and the final `[DONE]`. Yield an {"type":"error"} event instead of raising.
    """
    for i, event in enumerate(mock_data.negotiation_events(conjunction.id)):
        await asyncio.sleep(0.2 if i == 0 else 1.35 + (i % 3) * 0.19)
        yield event
