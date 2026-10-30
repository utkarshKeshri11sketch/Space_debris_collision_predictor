"""OWNER: Data agent (branch be-data). Replace the stub bodies; keep the signatures."""
from __future__ import annotations

from .. import mock_data
from ..models import CatalogMeta, CatalogObject


def load_catalog() -> list[CatalogObject]:
    """Return the full catalog as CatalogObject records (OMM fields in `omm`, CelesTrak names).

    Real impl: read the S3/local cached CelesTrak GP snapshot, refreshing at most once per 2 hours.
    """
    return mock_data.get_catalog()


def catalog_meta() -> CatalogMeta:
    """Return objectCount, byType counts, syncedAt (ISO UTC) and a human-readable `source`."""
    return mock_data.get_meta()
