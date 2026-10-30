"""Operator/spacecraft profiles used to score who should move.

THE CONTRACT HAS NO PROPELLANT, MASS OR MISSION DATA. Every number below is an ILLUSTRATIVE
ASSUMPTION for the demo, not real spacecraft telemetry; real operators would supply their own
(see docs/CONTRACT_REQUESTS.md). Callers can override per side with a `profile` dict in the
negotiation context. The negotiator labels profile-derived values as "assumed" in its messages.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

G0 = 9.80665  # m/s^2, standard gravity (used by the rocket equation)


@dataclass(frozen=True)
class Profile:
    label: str
    mass_kg: float             # assumed wet mass
    isp_s: float               # assumed specific impulse of the avoidance thruster
    reserve_kg: float          # assumed usable propellant remaining before this burn
    mission_impact: float      # 0..1 assumed fraction of mission value lost by interrupting for a burn
    assumed: bool = True


# Matched case-insensitively against the object name, first hit wins. All values illustrative.
_PROFILES: list[tuple[str, Profile]] = [
    # Large LEO broadband constellation: many interchangeable satellites, electric propulsion, so a
    # single burn costs little service and little propellant.
    (r"^STARLINK", Profile("large LEO constellation (illustrative)", 800.0, 1500.0, 12.0, 0.15)),
    # Smaller constellation with fewer spares: a burn interrupts a coverage window.
    (r"^ONEWEB", Profile("small LEO constellation (illustrative)", 150.0, 1600.0, 4.0, 0.45)),
    # Single-asset Earth-observation satellites: no spare covers the tasking gap.
    (r"^(CARTOSAT|OCEANSAT|NOAA|SENTINEL|LANDSAT|FENGYUN|METOP)", Profile("single-asset EO satellite (illustrative)", 1000.0, 220.0, 20.0, 0.60)),
    # Crewed station: burns are rare, planned and operationally heavy.
    (r"^ISS", Profile("crewed station (illustrative)", 420000.0, 300.0, 5000.0, 0.80)),
]
_DEFAULT = Profile("generic LEO satellite (illustrative)", 500.0, 220.0, 8.0, 0.30)


def profile_for(name: str, override: Mapping[str, Any] | None = None) -> Profile:
    base = next((p for pattern, p in _PROFILES if re.search(pattern, name, re.IGNORECASE)), _DEFAULT)
    if not override:
        return base
    fields = {
        "mass_kg": "mass_kg", "massKg": "mass_kg", "isp_s": "isp_s", "ispS": "isp_s",
        "reserve_kg": "reserve_kg", "reserveKg": "reserve_kg",
        "mission_impact": "mission_impact", "missionImpact": "mission_impact",
    }
    updates = {dest: float(override[src]) for src, dest in fields.items() if src in override}
    return replace(base, assumed=False, **updates) if updates else base


def estimate_propellant_kg(profile: Profile, dv_ms: float) -> float:
    """Tsiolkovsky rocket equation: m_prop = m0 * (1 - exp(-dv / (Isp * g0)))."""
    if dv_ms <= 0:
        return 0.0
    return profile.mass_kg * (1.0 - math.exp(-dv_ms / (profile.isp_s * G0)))
