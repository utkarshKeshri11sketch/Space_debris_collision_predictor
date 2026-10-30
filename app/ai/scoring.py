"""Deterministic mediator scoring. THE LLM NEVER COMPUTES OR ALTERS THESE NUMBERS.

For each candidate mover (A = primary, B = secondary) we score 0-100 how SUITABLE that spacecraft is to be
the one that maneuvers; higher is better. Weights are fixed by the product spec: propellant reserve 35%,
maneuver cost 25%, mission impact 20%, delta-v 20%. Each criterion is normalised 0-100 between the two:

  Propellant reserve  fuel left AFTER the burn (percent of tank), relative to the better-off spacecraft
  Maneuver cost       propellant mass spent, relative to the cheaper burn (cheaper = 100)
  Mission impact      100 * (1 - mission_impact)
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
# watch-list floor the frontend requests (minPc=1e-6). Operators often use ~1e-4 to trigger a burn and
# ~1e-5..1e-6 as the post-burn target; this is an assumption, not a regulation.
TARGET_PC = 1e-6
# Collision probability at or above which a lone maneuverable satellite should burn (debris case).
ACT_PC = 1e-5
# Weighted totals closer than this (points out of 100) are a statistical tie; see decide().
TIE_MARGIN = 2.0
# A burn that uses more than this fraction of the remaining propellant triggers a split-burn check.
SPLIT_TRIGGER = 0.25


@dataclass(frozen=True)
class Candidate:
    """One spacecraft's proposal to be the mover."""

    side: str                 # "A" or "B"
    fuel_after_pct: float     # percent of tank left after the burn
    propellant_kg: float
    dv_ms: float
    mission_impact: float     # 0..1
    new_pc: float


def _low_is_good(mine: float, other: float) -> float:
    return 100.0 if mine <= 0 else 100.0 * min(mine, other) / mine


def criteria(a: Candidate, b: Candidate) -> list[dict]:
    top = max(a.fuel_after_pct, b.fuel_after_pct)
    reserve = lambda c: 100.0 if top <= 0 else 100.0 * c.fuel_after_pct / top  # noqa: E731
    raw = {
        "Propellant reserve": (reserve(a), reserve(b)),
        "Maneuver cost": (_low_is_good(a.propellant_kg, b.propellant_kg), _low_is_good(b.propellant_kg, a.propellant_kg)),
        "Mission impact": (100.0 * (1 - a.mission_impact), 100.0 * (1 - b.mission_impact)),
        "Delta-v": (_low_is_good(a.dv_ms, b.dv_ms), _low_is_good(b.dv_ms, a.dv_ms)),
    }
    return [{"name": n, "weight": w, "a": round(raw[n][0]), "b": round(raw[n][1])} for n, w in WEIGHTS]


def totals(rows: list[dict]) -> tuple[float, float]:
    total_w = sum(r["weight"] for r in rows) or 1.0
    return (sum(r["a"] * r["weight"] for r in rows) / total_w, sum(r["b"] * r["weight"] for r in rows) / total_w)


@dataclass(frozen=True)
class Decision:
    mover: str              # "A" or "B"
    total_a: float
    total_b: float
    reason: str             # "score" | "tie" | "only-eligible" | "none-eligible"
    deciding: tuple[str, ...]  # the criteria that favoured the winner most


def decide(a: Candidate, b: Candidate, rows: list[dict]) -> Decision:
    """Pick the mover. Meeting TARGET_PC beats score; near-ties go to the spacecraft with more fuel left.

    The tie-break protects the spacecraft that would otherwise be left low on propellant, which shortens
    its life and is the costliest outcome of a close call.
    """
    ta, tb = totals(rows)
    ok_a, ok_b = a.new_pc <= TARGET_PC, b.new_pc <= TARGET_PC
    if ok_a != ok_b:
        mover, reason = ("A" if ok_a else "B"), "only-eligible"
    elif abs(ta - tb) < TIE_MARGIN:
        mover, reason = ("A" if a.fuel_after_pct >= b.fuel_after_pct else "B"), ("tie" if ok_a else "none-eligible")
    else:
        mover, reason = ("A" if ta > tb else "B"), ("score" if ok_a else "none-eligible")
    sign = 1 if mover == "A" else -1
    gains = sorted(rows, key=lambda r: sign * (r["a"] - r["b"]) * r["weight"], reverse=True)
    deciding = tuple(r["name"] for r in gains[:2] if sign * (r["a"] - r["b"]) > 0)
    return Decision(mover, ta, tb, reason, deciding)


@dataclass(frozen=True)
class Split:
    share_a: float          # fraction of the total delta-v flown by A (0..1)
    cost_split: float
    cost_best_single: float


def evaluate_split(prop_a: float, prop_b: float, fuel_kg_a: float, fuel_kg_b: float, impact_a: float, impact_b: float, single_mover: str) -> Split | None:
    """Would two smaller burns (one per spacecraft) beat the best single burn?  Returns the split if so.

    ASSUMPTIONS (documented, not measured):
      * Relative motion is symmetric: the same total delta-v D gives the same miss distance whichever
        spacecraft flies it, and propellant is proportional to the delta-v it flies (prop_a/prop_b are the
        propellant for the FULL D by A or by B).
      * Scarcity cost of spending propellant p from a tank holding R is (p/R)^2: the emptier the tank, the
        more each kilogram hurts, which is what makes sharing a burn worthwhile.
      * Each spacecraft that burns pays its mission impact once (an interrupted service window costs the
        same however short the burn), added to scarcity cost as dimensionless fractions with weight 1.
    Only checked when the single burn would use more than SPLIT_TRIGGER of the mover's remaining fuel.
    """
    if min(fuel_kg_a, fuel_kg_b) <= 0:
        return None
    ua, ub = prop_a / fuel_kg_a, prop_b / fuel_kg_b  # fraction of remaining fuel for the FULL burn
    single_use = ua if single_mover == "A" else ub
    if single_use <= SPLIT_TRIGGER:
        return None
    cost_single = single_use**2 + (impact_a if single_mover == "A" else impact_b)
    f = (ub**2) / (ua**2 + ub**2) if (ua**2 + ub**2) else 0.5  # minimiser of (f*ua)^2 + ((1-f)*ub)^2
    f = min(max(f, 0.1), 0.9)  # a share under 10% is not a real burn
    cost_split = (f * ua) ** 2 + ((1 - f) * ub) ** 2 + impact_a + impact_b
    return Split(f, cost_split, cost_single) if cost_split < cost_single else None
