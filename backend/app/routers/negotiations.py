import logging
import uuid

from fastapi import APIRouter, HTTPException

from ..ai import negotiator
from ..casestudy import service as casestudy
from ..models import NegotiationStart, NegotiationStarted
from ..physics import maneuver, screening
from .sse import sse_response

router = APIRouter(prefix="/api/negotiations", tags=["negotiations"])
LOG = logging.getLogger(__name__)

# The id embeds the conjunction id so it is stateless across Lambda containers: "<uuid>~<conjunctionId>".
_SEP = "~"


def _side_options(detail: dict, conjunction_id: str) -> dict:
    """Burn options computed by Physics for EACH side moving, from Screening's exact TCA geometry."""
    encounter = screening.get_encounter(conjunction_id)
    options = {}
    for side, ref in (("a", detail["primary"]), ("b", detail["secondary"])):
        try:
            options[side] = maneuver.options_for(detail, ref["noradId"], encounter=encounter)
        except (ValueError, KeyError, TypeError) as exc:
            # The negotiator scales the other side's burn and labels it as an estimate.
            LOG.warning("No maneuver options for %s in %s: %s", ref["name"], conjunction_id, exc)
            options[side] = []
    return options


def _find(conjunction_id: str):
    if casestudy.is_case(conjunction_id):
        return casestudy.get_conjunction(conjunction_id)
    return screening.get_conjunction(conjunction_id)


@router.post("", response_model=NegotiationStarted, status_code=201)
def start(body: NegotiationStart):
    conj = _find(body.conjunctionId)
    if conj is None:
        raise HTTPException(404, "Conjunction not found.")
    if not (conj.primary.maneuverable and conj.secondary.maneuverable):
        raise HTTPException(422, "Negotiation requires two maneuverable spacecraft.")
    return NegotiationStarted(negotiationId=f"{uuid.uuid4()}{_SEP}{conj.id}")


@router.get("/{negotiation_id}/stream")
def stream(negotiation_id: str):
    conjunction_id = negotiation_id.partition(_SEP)[2] if _SEP in negotiation_id else ""
    if conjunction_id and casestudy.is_case(conjunction_id):
        inputs = casestudy.negotiation_inputs(conjunction_id)
        if inputs is None:
            raise HTTPException(404, "Case study reconstruction is not available yet.")
        return sse_response(negotiator.negotiate(*inputs))
    conj = screening.get_conjunction(conjunction_id) if conjunction_id else None
    if conj is None:
        raise HTTPException(404, "Negotiation expired. Start a new session.")
    detail = conj.model_dump()
    # Operator fuel/mission inputs are not public: None lets the AI use its labelled profiles.
    return sse_response(negotiator.negotiate(detail, None, None, _side_options(detail, conj.id)))
