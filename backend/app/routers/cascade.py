from fastapi import APIRouter, HTTPException

from ..models import CascadeRequest, CascadeResult
from ..physics import cascade

router = APIRouter(prefix="/api/cascade", tags=["cascade"])


@router.post("", response_model=CascadeResult)
def run(body: CascadeRequest):
    try:
        return cascade.simulate(body)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
