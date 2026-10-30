from fastapi import APIRouter, HTTPException

from ..ai import ask_stream
from ..data import catalog
from ..models import AskRequest, AskToken
from ..physics import screening
from .sse import sse_response

router = APIRouter(prefix="/api/ask", tags=["ask"])


def _context() -> dict:
    """Ask Sentinel is grounded only in the current screening run and catalog summary."""
    return {"conjunctions": [c.model_dump() for c in screening.screen(None, 7, 0)],
            "catalogMeta": catalog.catalog_meta().model_dump()}


async def _tokens(question: str, context: dict):
    async for text in ask_stream(question, context):
        yield AskToken(text=text).model_dump()


@router.post("")
def ask(body: AskRequest):
    if not body.question.strip():
        raise HTTPException(400, "Enter a question about this screening run.")
    return sse_response(_tokens(body.question, _context()))
