"""Deterministic mediator scoring. The LLM never computes or alters these numbers.

For each candidate mover (agent A = primary, agent B = secondary) we score 0-100 how SUITABLE that
spacecraft is to be the one that maneuvers; higher is better. Weights are fixed by the product
spec: propellant reserve 35%, maneuver cost 25%, mission impact 20%, delta-v 20%.

Criteria (all comparative between the two candidates, so scores are scale-free):
  Propellant reserve  remaining propellant after the burn, relative to the larger of the two
  Maneuver cost       propellant mass spent, relative to the cheaper burn (cheaper = 100)
  Mission impact      100 * (1 - assumed mission_impact)   [from profiles.py, illustrative]
  Delta-v             delta-v of the burn, relative to the smaller burn (smaller = 100)
"""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS: list[tuple[str, float]] = [
    ("Propellant reserve", 0.35),
    ("Maneuver cost", 0.25),
    ("Mission impact", 0.20),
    ("Delta-v", 0.20),
]
# Post-burn collision probability an option must reach to count as a resolution. 1e-6 matches the
# watch-list floor the frontend requests (minPc=1e-6). Operators often use 1e-4 to trigger a burn
# and ~1e-5..1e-6 as the post-burn target; this is an assumption, not a regulation.
TARGET_PC = 1e-6
# Totals closer than this (points out of 100) are a statistical tie; see decide().
TIE_MARGIN = 2.0


@dataclass(frozen=True)
class Candidate:
    """One spacecraft's proposal to be the mover."""

    side: str               # "A" or "B"
    reserve_kg: float
    propellant_kg: float
    dv_ms: float
    mission_impact: float   # 0..1
    new_pc: float


def _ratio_low_is_good(mine: float, other: float) -> float:
    best = min(mine, other)
    if mine <= 0:
        return 100.0
    return 100.0 * best / mine


def criteria(a: Candidate, b: Candidate) -> list[dict]:
    rem_a = max(a.reserve_kg - a.propellant_kg, 0.0)
    rem_b = max(b.reserve_kg - b.propellant_kg, 0.0)
    top = max(rem_a, rem_b)
    raw = {
        "Propellant reserve": ((100.0 * rem_a / top) if top else 100.0, (100.0 * rem_b / top) if top else 100.0),
        "Maneuver cost": (_ratio_low_is_good(a.propellant_kg, b.propellant_kg), _ratio_low_is_good(b.propellant_kg, a.propellant_kg)),
        "Mission impact": (100.0 * (1 - a.mission_impact), 100.0 * (1 - b.mission_impact)),
        "Delta-v": (_ratio_low_is_good(a.dv_ms, b.dv_ms), _ratio_low_is_good(b.dv_ms, a.dv_ms)),
    }
    return [{"name": n, "weight": w, "a": round(raw[n][0]), "b": round(raw[n][1])} for n, w in WEIGHTS]


def totals(rows: list[dict]) -> tuple[float, float]:
    total_w = sum(r["weight"] for r in rows) or 1.0
    return (
        sum(r["a"] * r["weight"] for r in rows) / total_w,
        sum(r["b"] * r["weight"] for r in rows) / total_w,
    )


@dataclass(frozen=True)
class Decision:
    mover: str              # "A" or "B"
    total_a: float
    total_b: float
    reason: str             # "score" | "tie" | "only-eligible" | "none-eligible"
    eligible_a: bool
    eligible_b: bool


def decide(a: Candidate, b: Candidate, rows: list[dict]) -> Decision:
    """Pick the mover. Eligibility (meets TARGET_PC) beats score; near-ties go to the larger reserve.

    The tie-break favours the spacecraft with more propellant left because running a spacecraft
    low on propellant shortens its life, which is the costliest outcome of a close call.
    """
    ta, tb = totals(rows)
    ok_a, ok_b = a.new_pc <= TARGET_PC, b.new_pc <= TARGET_PC
    if ok_a != ok_b:
        return Decision("A" if ok_a else "B", ta, tb, "only-eligible", ok_a, ok_b)
    reason = "score" if ok_a else "none-eligible"
    if abs(ta - tb) < TIE_MARGIN:
        rem_a, rem_b = a.reserve_kg - a.propellant_kg, b.reserve_kg - b.propellant_kg
        return Decision("A" if rem_a >= rem_b else "B", ta, tb, "tie" if ok_a else reason, ok_a, ok_b)
    return Decision("A" if ta > tb else "B", ta, tb, reason, ok_a, ok_b)
