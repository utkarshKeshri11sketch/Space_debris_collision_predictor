"""OWNER: Physics agent (branch be-physics). Replace the stub bodies; keep the signatures."""
from __future__ import annotations

from .. import mock_data
from ..models import Conjunction, ManeuverOption


def options(conjunction: Conjunction) -> list[ManeuverOption]:
    """Candidate avoidance burns (dv, burnAt, newMissM, newPc, propellantKg) plus a 'no-action' option.

    Exactly one option has recommended=True. The no-action option has direction='none', burnAt=None.
    """
    match = next((c for c in mock_data.CONJUNCTIONS if c.id == conjunction.id), None)
    return match.options if match else []
