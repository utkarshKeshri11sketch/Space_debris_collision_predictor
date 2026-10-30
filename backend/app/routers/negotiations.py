import uuid

from fastapi import APIRouter, HTTPException

from ..ai import negotiator
from ..models import NegotiationStart, NegotiationStarted
from ..physics import screening
from .sse import sse_response

router = APIRouter(prefix="/api/negotiations", tags=["negotiations"])

# The id embeds the conjunction id so it is stateless across Lambda containers: "<uuid>~<conjunctionId>".
_SEP = "~"


@router.post("", response_model=NegotiationStarted, status_code=201)
def start(body: NegotiationStart):
    conj = screening.get_conjunction(body.conjunctionId)
    if conj is None:
        raise HTTPException(404, "Conjunction not found.")
    if not (conj.primary.maneuverable and conj.secondary.maneuverable):
        raise HTTPException(422, "Negotiation requires two maneuverable spacecraft.")
    return NegotiationStarted(negotiationId=f"{uuid.uuid4()}{_SEP}{conj.id}")


@router.get("/{negotiation_id}/stream")
def stream(negotiation_id: str):
    conj = screening.get_conjunction(negotiation_id.partition(_SEP)[2]) if _SEP in negotiation_id else None
    if conj is None:
        raise HTTPException(404, "Negotiation expired. Start a new session.")
    return sse_response(negotiator.negotiate(conj))
