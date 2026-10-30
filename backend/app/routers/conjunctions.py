import logging

from fastapi import APIRouter, HTTPException, Query, Response

from ..ai import generate_brief
from ..models import Conjunction, ConjunctionDetail
from ..physics import screening

router = APIRouter(prefix="/api/conjunctions", tags=["conjunctions"])
LOG = logging.getLogger(__name__)


@router.get("", response_model=list[Conjunction])
def list_conjunctions(response: Response, days: float = Query(7, ge=0, le=7),
                      minPc: float = Query(1e-6, ge=0, le=1),
                      noradId: int | None = Query(None, ge=1, le=999999999)):
    events = screening.screen(noradId, days, minPc)
    status = screening.screening_status()
    response.headers["X-Screening-Complete"] = str(status.get("complete", False)).lower()
    response.headers["X-Screening-Issues"] = str(status.get("issues", 0))
    if "asOf" in status:
        response.headers["X-Screening-As-Of"] = status["asOf"]
    return events


@router.get("/{conjunction_id}", response_model=ConjunctionDetail)
def get_conjunction(conjunction_id: str):
    found = screening.get_conjunction(conjunction_id)
    if found is None:
        raise HTTPException(404, "Conjunction not found in this screening run.")
    try:
        # Sentinel brief from the AI layer (template, or a grounded LLM text when a provider is set).
        found = found.model_copy(update={"brief": generate_brief(found.model_dump())})
    except Exception:  # noqa: BLE001 - keep Screening's factual brief if the AI layer fails
        LOG.exception("Sentinel brief failed for %s", conjunction_id)
    return found
