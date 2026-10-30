"""SSE framing shared by the streaming routers. Format matches frontend/src/api/client.ts `stream()`."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def frame(payload: object) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


async def sse_stream(items: AsyncIterator[object]) -> AsyncIterator[bytes]:
    try:
        async for item in items:
            yield frame(item)
    except Exception as exc:  # surface failures in-band; HTTP status is already 200
        yield frame({"type": "error", "message": str(exc) or "Stream failed."})
    yield b"data: [DONE]\n\n"


def sse_response(items: AsyncIterator[object]) -> StreamingResponse:
    return StreamingResponse(sse_stream(items), media_type="text/event-stream", headers=HEADERS)
