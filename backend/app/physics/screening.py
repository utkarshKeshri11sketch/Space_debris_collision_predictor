"""OWNER: Screening agent (branch be-screening). Replace the stub bodies; keep the signatures."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import mock_data
from ..models import ConjunctionDetail


def screen(target_id: int | None = None, days: float = 7, min_pc: float = 1e-6) -> list[ConjunctionDetail]:
    """SGP4 conjunction search over the catalog for the next `days` days.

    target_id=None screens the whole watch-list. Returns events sorted by TCA with Pc >= min_pc.
    Each result must be a full ConjunctionDetail (the list endpoint trims it to Conjunction).
    Maneuver `options` may be filled by maneuver.options(); `brief` by app.ai.
    """
    horizon = datetime.now(timezone.utc).timestamp() + days * 86400
    return [c for c in mock_data.CONJUNCTIONS if c.pc >= min_pc
            and datetime.fromisoformat(c.tca.replace("Z", "+00:00")).timestamp() <= horizon
            and (target_id is None or target_id in (c.primary.noradId, c.secondary.noradId))]


def get_conjunction(conjunction_id: str) -> ConjunctionDetail | None:
    """Return one event by id from the latest screening run, or None."""
    return next((c for c in mock_data.CONJUNCTIONS if c.id == conjunction_id), None)
