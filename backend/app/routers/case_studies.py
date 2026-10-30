from fastapi import APIRouter, HTTPException

from ..casestudy import facts, service
from ..models import CaseStudy

router = APIRouter(prefix="/api/case-studies", tags=["case-studies"])


@router.get("")
def list_case_studies():
    return [{"id": c["id"], "title": c["title"], "date": c["date"]} for c in facts.CASES]


@router.get("/{case_id}", response_model=CaseStudy)
def get_case_study(case_id: str):
    found = service.build(case_id)
    if found is None:
        raise HTTPException(404, "Case study not found.")
    return found
