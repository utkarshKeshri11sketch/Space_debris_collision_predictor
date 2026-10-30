from fastapi import APIRouter, HTTPException, Query

from ..models import Conjunction, ConjunctionDetail
from ..physics import screening

router = APIRouter(prefix="/api/conjunctions", tags=["conjunctions"])


@router.get("", response_model=list[Conjunction])
def list_conjunctions(days: float = Query(7, ge=0, le=7), minPc: float = 1e-6):
    return screening.screen(None, days, minPc)


@router.get("/{conjunction_id}", response_model=ConjunctionDetail)
def get_conjunction(conjunction_id: str):
    found = screening.get_conjunction(conjunction_id)
    if found is None:
        raise HTTPException(404, "Conjunction not found in this screening run.")
    return found
