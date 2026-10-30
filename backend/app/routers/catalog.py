from fastapi import APIRouter

from ..data import catalog
from ..models import CatalogMeta, CatalogObject

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("", response_model=list[CatalogObject])
def get_catalog():
    return catalog.load_catalog()


@router.get("/meta", response_model=CatalogMeta)
def get_meta():
    return catalog.catalog_meta()
