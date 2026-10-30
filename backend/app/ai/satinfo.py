"""Normalise the per-satellite inputs of negotiate() (Python-side, snake_case) into one Sat record.

Accepted keys for sat_a / sat_b (camelCase twins also work):
    name, operator, can_maneuver, fuel_reserve_pct (0-100), mission_impact (0-1 float, or a note string,
    or {"score": 0-1, "note": str}), mission_note, propellant_capacity_kg, mass_kg, isp_s,
    noradId, type   (identity fields; default to the conjunction's primary/secondary)
Missing fuel/impact values are filled from profiles.py (illustrative) and listed in `assumed`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .profiles import Profile, profile_for


@dataclass
class Sat:
    ref: dict
    operator: str
    can_maneuver: bool
    fuel_pct: float
    mission_impact: float
    mission_note: str
    capacity_kg: float
    mass_kg: float
    isp_s: float
    assumed: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.ref["name"]

    @property
    def is_debris(self) -> bool:
        return self.ref.get("type") in ("DEBRIS", "ROCKET_BODY") or (not self.can_maneuver and "DEB" in self.name.upper())

    @property
    def fuel_kg(self) -> float:
        return self.capacity_kg * self.fuel_pct / 100.0


def _pick(d: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    return next((d[k] for k in keys if k in d and d[k] is not None), default)


def build_sat(info: Mapping[str, Any] | None, fallback_ref: Mapping[str, Any]) -> Sat:
    info = info or {}
    ref = {k: _pick(info, k, default=fallback_ref.get(k)) for k in ("noradId", "name", "type")}
    ref["maneuverable"] = bool(_pick(info, "can_maneuver", "canManeuver", "maneuverable", default=fallback_ref.get("maneuverable", False)))
    prof: Profile = profile_for(ref["name"])
    assumed: list[str] = []

    fuel = _pick(info, "fuel_reserve_pct", "fuelReservePct")
    if fuel is None:
        fuel = prof.fuel_pct
        assumed.append(f"{ref['name']} fuel reserve")
    impact = _pick(info, "mission_impact", "missionImpact")
    note = _pick(info, "mission_note", "missionNote", default="")
    if isinstance(impact, Mapping):
        impact, note = impact.get("score"), impact.get("note", note)
    elif isinstance(impact, str):
        impact, note = None, impact
    if impact is None:
        impact, note = prof.mission_impact, note or prof.mission_note
        assumed.append(f"{ref['name']} mission impact")
    return Sat(
        ref=ref, operator=str(_pick(info, "operator", default=f"{ref['name']} operator")), can_maneuver=ref["maneuverable"],
        fuel_pct=max(0.0, min(100.0, float(fuel))), mission_impact=max(0.0, min(1.0, float(impact))), mission_note=str(note),
        capacity_kg=float(_pick(info, "propellant_capacity_kg", "propellantCapacityKg", default=prof.capacity_kg)),
        mass_kg=float(_pick(info, "mass_kg", "massKg", default=prof.mass_kg)),
        isp_s=float(_pick(info, "isp_s", "ispS", default=prof.isp_s)), assumed=assumed,
    )
