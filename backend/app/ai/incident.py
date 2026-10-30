"""How OrbitSentinel's negotiator would have resolved a past incident (OWNER: Lead, for the case study).

Numbers come from Physics (app/physics/incident.py) and the deterministic mediator scoring
(app/ai/scoring.py), exactly as in a live negotiation. Text is built from templates over sourced
facts (app/casestudy/facts.py) and those numbers, so it never states anything not in them.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from . import fmt
from .negotiator import _candidate, build_setup, pick_option
from .scoring import criteria, decide, evaluate_split

# ASSUMPTIONS for the 2021 spacecraft. The station's mass and Isp come from Physics' reconstruction
# ("reality"), so propellant figures agree; these fill only what Physics does not supply.
STATION_PROPELLANT_CAPACITY_KG = 2000.0  # assumption: usable avoidance propellant aboard; not published
STATION_FUEL_PCT = 70.0                  # assumption: same reserve level as the ISS profile
STATION_IMPACT = 0.80                    # assumption: crewed station, same as the ISS profile
STARLINK_V1_MASS_KG = 260.0              # Starlink v1.x launch mass (public catalog entries, e.g. keeptrack.space 47989)
STARLINK_V1_ISP_S = 1500.0               # assumption: krypton Hall-effect thrusters
STARLINK_V1_CAPACITY_KG = 4.0            # assumption: krypton load scaled from the v2-mini profile by mass
STARLINK_FUEL_PCT = 60.0                 # assumption
STARLINK_IMPACT = 0.15                   # assumption: same as the live Starlink profile (spares cover the gap)


def sat_profiles(case: Mapping[str, Any], analysis: Mapping[str, Any] | None = None) -> tuple[dict, dict]:
    """(sat_a, sat_b) for negotiate(): the 2021 station (side a) and the 2021 Starlink (side b)."""
    reality = (analysis or {}).get("reality") or {}
    station = {
        "operator": "China Manned Space Agency", "can_maneuver": True,
        "mass_kg": reality.get("massKg"), "isp_s": reality.get("ispS"),
        "propellant_capacity_kg": STATION_PROPELLANT_CAPACITY_KG, "fuel_reserve_pct": STATION_FUEL_PCT,
        "mission_impact": {"score": STATION_IMPACT,
                           "note": "crew were aboard; a burn interrupts crew operations and on-board experiments"},
    }
    starlink = {
        "operator": "SpaceX", "can_maneuver": True,
        "mass_kg": STARLINK_V1_MASS_KG, "isp_s": STARLINK_V1_ISP_S,
        "propellant_capacity_kg": STARLINK_V1_CAPACITY_KG, "fuel_reserve_pct": STARLINK_FUEL_PCT,
        "mission_impact": {"score": STARLINK_IMPACT,
                           "note": "neighbouring constellation satellites cover the service gap and burns are automated"},
    }
    return {k: v for k, v in station.items() if v is not None}, starlink


def recommend(conjunction: Mapping[str, Any], options_by_side: Mapping[str, Any],
              sat_a: Mapping[str, Any] | None = None, sat_b: Mapping[str, Any] | None = None) -> dict:
    """The mediator's decision, computed the same way as the live negotiation stream."""
    setup = build_setup(conjunction, sat_a, sat_b, options_by_side)
    opts = {"A": pick_option(setup.opts_a), "B": pick_option(setup.opts_b)}
    if opts["A"] is None or opts["B"] is None:
        raise ValueError("Both sides need a costed burn to compare")
    cand = {side: _candidate(side, setup.sat(side), opts[side]) for side in ("A", "B")}
    rows = criteria(cand["A"], cand["B"])
    dec = decide(cand["A"], cand["B"], rows)
    maneuver = dict(opts[dec.mover])
    a, b = setup.a, setup.b
    if sp := evaluate_split(opts["A"]["propellantKg"], opts["B"]["propellantKg"], a.fuel_kg, b.fuel_kg,
                            a.mission_impact, b.mission_impact, dec.mover):
        share = sp.share_a if dec.mover == "A" else 1 - sp.share_a  # same split rule as the stream
        maneuver = {**maneuver, "id": f"{maneuver['id']}-split", "dvMs": round(maneuver["dvMs"] * share, 3),
                    "propellantKg": round(maneuver["propellantKg"] * share, 4)}
    mover = setup.sat(dec.mover)
    return {"moverSide": dec.mover.lower(), "moverNoradId": int(mover.ref["noradId"]), "moverMassKg": mover.mass_kg,
            "maneuver": {**maneuver, "recommended": True}, "criteria": rows,
            "alternative": dict(opts["B" if dec.mover == "A" else "A"])}


def narrate(case: Mapping[str, Any], analysis: Mapping[str, Any], decision: Mapping[str, Any]) -> dict:
    """Presentation text grounded in the case facts and the computed numbers. Neutral, no quotes."""
    conj, reality = analysis["conjunction"], analysis["reality"]
    station, starlink = conj["primary"]["name"], conj["secondary"]["name"]
    picked, alt = decision["maneuver"], decision.get("alternative") or {}
    mover = station if decision["moverSide"] == "a" else starlink
    station_kg = reality["propellantKg"]
    starlink_kg = (alt if decision["moverSide"] == "a" else picked).get("propellantKg")
    ratio = station_kg / starlink_kg if starlink_kg else None

    reality_text = (
        f"On {date.fromisoformat(case['date']):%d %B %Y} the crewed {station} flew a collision-avoidance burn "
        f"because {starlink} came close. There was no shared channel to agree who should move, so the "
        f"station moved on its own. Our reconstruction puts that burn at "
        f"{fmt.dv(reality['dvMs']) if reality.get('dvMs') is not None else 'an unpublished delta-v'} and about "
        f"{fmt.kg(station_kg)} of propellant for a {reality['massKg'] / 1000:.0f} t station. "
        f"Months later, on 3 December 2021, China notified the UN; on 28 January 2022 the United States replied that "
        f"the encounters did not meet emergency-notification criteria."
    )
    if ratio:
        comparison = (f"The same avoidance flown by {starlink} costs {fmt.kg(starlink_kg)}, "
                      f"about {ratio:,.0f} times less propellant than the station's burn.")
    else:
        comparison = ""
    orbit_text = (
        f"OrbitSentinel screens the pair, costs a burn for each spacecraft and lets each operator's agent "
        f"state its case. {comparison} The mediator scores propellant reserve, maneuver cost, mission impact and "
        f"delta-v (35/25/20/20) and recommends that {mover} moves: {fmt.dv(picked['dvMs'])} {picked['direction']}, "
        f"{fmt.kg(picked['propellantKg'])}, giving {fmt.distance(picked['newMissM'])} separation. "
        f"This takes seconds, and a human operator on each side approves before any command is sent."
    )
    brief = (f"2021: the station moved alone and the dispute went to the UN. "
             f"With OrbitSentinel: {mover} moves" + (f", using {ratio:,.0f}x less propellant." if ratio else ".")
             + " A human operator must approve any maneuver.")
    return {"reality": reality_text, "orbitSentinel": orbit_text, "brief": brief}
