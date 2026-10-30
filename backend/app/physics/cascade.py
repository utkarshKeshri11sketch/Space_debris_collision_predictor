"""OWNER: Physics agent (branch be-physics). Replace the stub body; keep the signature."""
from __future__ import annotations

from .. import mock_data
from ..models import CascadeRequest, CascadeResult


def simulate(scenario: CascadeRequest) -> CascadeResult:
    """Breakup cascade. Raise LookupError if scenario.noradId is not in the catalog (router -> 404)."""
    return mock_data.get_cascade(scenario)
