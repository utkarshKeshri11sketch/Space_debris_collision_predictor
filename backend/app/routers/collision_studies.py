from fastapi import APIRouter, HTTPException

from ..casestudy import collision
from ..models import CollisionStudy

router = APIRouter(prefix="/api/collision-studies", tags=["case-studies"])


@router.get("")
def list_collision_studies():
    return [collision.summary()]


@router.get("/{study_id}", response_model=CollisionStudy)
def get_collision_study(study_id: str):
    if study_id != collision.ID:
        raise HTTPException(404, "Collision study not found.")
    return collision.study()
