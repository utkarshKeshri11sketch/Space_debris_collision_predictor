from fastapi import APIRouter, HTTPException

from ..ai import ask as ask_module
from ..models import AskRequest, AskToken
from .sse import sse_response

router = APIRouter(prefix="/api/ask", tags=["ask"])


async def _tokens(question: str):
    async for text in ask_module.ask(question):
        yield AskToken(text=text).model_dump()


@router.post("")
def ask(body: AskRequest):
    if not body.question.strip():
        raise HTTPException(400, "Enter a question about this screening run.")
    return sse_response(_tokens(body.question))
