"""OWNER: AI agent. Decide and narrate how OrbitSentinel would have resolved a past incident.

Replace the stub bodies; keep the signatures and the output shapes in docs/case_studies/CONTRACT.md.
"""
from __future__ import annotations


def recommend(conjunction: dict, options_by_side: dict) -> dict:
    """Mediator decision with the brief's weights: {"moverSide": "a"|"b", "maneuver", "criteria"}."""
    raise NotImplementedError("AI incident recommendation not delivered yet")


def narrate(case: dict, analysis: dict, decision: dict) -> dict:
    """Plain-English story grounded only in `case` facts and computed numbers:
    {"reality": str, "orbitSentinel": str, "brief": str}."""
    raise NotImplementedError("AI incident narrative not delivered yet")


def sat_profiles(case: dict) -> tuple[dict, dict]:
    """(sat_a, sat_b) inputs for negotiate(): the station and the Starlink as they were in 2021."""
    raise NotImplementedError("AI incident profiles not delivered yet")
