"""Fallback spacecraft parameters for fields the caller did not supply.

THE CONTRACT HAS NO PROPELLANT, MASS OR MISSION DATA. Every number below is an ILLUSTRATIVE ASSUMPTION
for the demo, not real spacecraft telemetry. The negotiator is normally given per-satellite fuel reserve (%)
and mission impact by the caller (Lead / operator data); these defaults only fill the gaps, and anything
filled from here is reported as "assumed" in the negotiation text.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

G0 = 9.80665  # m/s^2, standard gravity (used by the rocket equation)


@dataclass(frozen=True)
class Profile:
    label: str
    mass_kg: float          # assumed wet mass
    isp_s: float            # assumed specific impulse of the avoidance thruster
    capacity_kg: float      # assumed usable propellant in a full tank
    fuel_pct: float         # assumed fuel remaining (percent of capacity)
    mission_impact: float   # 0..1 assumed fraction of mission value lost by interrupting for a burn
    mission_note: str       # plain-English reason for that impact


# Matched case-insensitively against the object name, first hit wins. All values illustrative.
_PROFILES: list[tuple[str, Profile]] = [
    # Large LEO broadband constellation: many interchangeable satellites, electric propulsion, automated
    # collision avoidance, so a single burn costs little service and little propellant.
    (r"^STARLINK", Profile("large LEO constellation", 800.0, 1500.0, 12.0, 78.0, 0.15, "neighbouring satellites cover the service gap and burns are automated")),
    # Smaller constellation with fewer spares: a burn interrupts a coverage window.
    (r"^ONEWEB", Profile("small LEO constellation", 150.0, 1600.0, 4.0, 41.0, 0.45, "a burn interrupts a scheduled coverage window")),
    # Single-asset Earth-observation satellites: no spare covers the tasking gap.
    (r"^(CARTOSAT|OCEANSAT|NOAA|SENTINEL|LANDSAT|FENGYUN|METOP)", Profile("single-asset Earth-observation satellite", 1000.0, 220.0, 20.0, 55.0, 0.60, "a burn cancels imaging passes that no spare satellite can cover")),
    # Crewed station: burns are rare, planned and operationally heavy.
    (r"^ISS", Profile("crewed station", 420000.0, 300.0, 5000.0, 70.0, 0.80, "a reboost-style burn disrupts crew operations and needs weeks of planning")),
]
_DEFAULT = Profile("generic LEO satellite", 500.0, 220.0, 8.0, 50.0, 0.30, "a burn interrupts routine operations")


def profile_for(name: str) -> Profile:
    return next((p for pattern, p in _PROFILES if re.search(pattern, name, re.IGNORECASE)), _DEFAULT)


def estimate_propellant_kg(profile: Profile, dv_ms: float) -> float:
    """Tsiolkovsky rocket equation: m_prop = m0 * (1 - exp(-dv / (Isp * g0)))."""
    if dv_ms <= 0:
        return 0.0
    return profile.mass_kg * (1.0 - math.exp(-dv_ms / (profile.isp_s * G0)))
