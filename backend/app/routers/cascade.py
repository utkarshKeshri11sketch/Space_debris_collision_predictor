import threading

from fastapi import APIRouter, HTTPException

from ..data import catalog
from ..models import CascadeRequest, CascadeResult
from ..physics import cascade

router = APIRouter(prefix="/api/cascade", tags=["cascade"])

# The catalog environment (altitude-shell census) takes ~1 s to build; reuse it per catalog sync.
_env_lock = threading.Lock()
_env: tuple[str, object] | None = None


def _environment(objects: list, synced_at: str):
    global _env
    with _env_lock:
        if _env is None or _env[0] != synced_at:
            _env = synced_at, cascade.build_environment(objects)
        return _env[1]


@router.post("", response_model=CascadeResult)
def run(body: CascadeRequest):
    objects = catalog.load_catalog()
    environment = _environment(objects, catalog.catalog_meta().syncedAt)
    try:
        return cascade.simulate(body.model_dump(), objects, environment=environment).result
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
