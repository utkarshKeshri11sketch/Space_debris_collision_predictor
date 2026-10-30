"""OWNER: Physics agent. Reconstruct a past incident and cost both ways of resolving it.

The two 2021 China Space Station (CSS / Tianhe) x Starlink encounters are real, but their TCA,
miss distance, covariance and the station's burn were never published (facts.py has what was). This
module therefore builds a *reconstruction* from the published orbit altitudes and inclinations and
states every modelled number in the returned "assumptions" list. Costs come from app.physics.maneuver,
the same planner as live events, so the comparison with what happened is like for like.

No historical element sets (Space-Track GP_HISTORY needs an account) are used. If they become available,
only `_geometry()` has to change; the costing below takes any `Encounter`.

Method, in order:
1. Two circular orbits from the published altitudes/inclinations. Their relative RAAN is unpublished,
   so the crossing used is the one with the median relative speed over all relative RAANs.
2. A per-object RTN position covariance (assumption) is rotated into the encounter plane and summed.
3. The miss vector is set along the covariance major axis at the distance where Pc equals EVENT_PC,
   i.e. the mildest event the planner itself would act on (so every burn below is a floor, not a worst
   case, and the OrbitSentinel-vs-reality comparison is not flattered).
4. maneuver.plan_maneuvers costs a burn by the station and a burn by the Starlink.
5. "reality" = the cheapest station burn that reaches the planner's safety target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from .maneuver import (
    MAX_DV_MS,
    MIN_MISS_TARGET_M,
    MU_KM3_S2,
    PC_MANEUVER_THRESHOLD,
    PC_TARGET,
    Encounter,
    Propulsion,
    collision_probability,
    encounter_plane_basis,
    plan_maneuvers,
    propellant_kg,
    rtn_basis,
)

EARTH_RADIUS_KM = 6378.137  # WGS-84 equatorial radius

# Pc of the reconstructed event. Just above the planner's 1e-4 "critical/burn" threshold, so the event is
# the mildest one that would trigger a burn. The real Pc was never published (the US said its own estimate
# was not significant), so this is a modelling choice, not a measurement.
EVENT_PC = 2e-4
# Planning epoch: 26 h before TCA, so the planner's 24 h maximum lead is available. Assumption.
PLANNING_LEAD_S = 26 * 3600.0
# TCA time of day on the case date (only the date is published). Assumption.
TCA_TIME_UTC = (12, 0, 0)
RANGE_SERIES_S = np.linspace(-60.0, 60.0, 81)  # frontend window: +-60 s, 81 points
CRITICAL_PC, HIGH_PC = 1e-4, 1e-5  # same risk bands as screening.ScreeningConfig

# --- Spacecraft ------------------------------------------------------------------------------------
# Station propulsion: chemical (storable bipropellant, assumed ~300 s, the same value the live planner uses
# for the ISS). Tianhe also carries electric thrusters, but avoidance needs a prompt burn; the contract asks
# for chemical Isp. Assumption.
STATION_ISP_S = 300.0
# Public launch masses (kg): Tianhe core 22,500 (Wikipedia "Tianhe core module", CMSA); Tianzhou-2 13,640
# (Wikipedia "Tianzhou 2": launch 13,640, dry 6,640); Tianzhou-3 ~13,500 (Chinese state media, "13.5 t");
# Shenzhou crewed ship ~7,840 (Wikipedia / spacefacts: 7.8-8.1 t).
TIANHE_KG, TIANZHOU_2_KG, TIANZHOU_3_KG, SHENZHOU_KG = 22_500.0, 13_640.0, 13_500.0, 7_840.0
TIANZHOU_DRY_KG = 6_640.0  # Tianzhou-2 dry mass; assumed for Tianzhou-3 too
# Starlink v1.x: ~260 kg (SpaceX; space.skyrocket.de), krypton Hall thruster, Isp not published (assumption).
STARLINK_KG, STARLINK_ISP_S = 260.0, 1500.0


@dataclass(frozen=True)
class _Scenario:
    station_alt_km: float
    starlink_alt_km: float
    starlink_inc_deg: float
    station_sigma_rtn_m: tuple[float, float, float]
    starlink_sigma_rtn_m: tuple[float, float, float]
    station_mass_kg: float
    station_mass_low_kg: float
    docked: str
    starlink_notes: tuple[str, ...]


STATION_INC_DEG = 41.5  # UN note A/AC.105/1262 ("~41.5 deg", via facts.CSS)
STATION_HBR_M = 30.0  # bounding sphere of the docked station (assumption)
STARLINK_HBR_M = 5.0  # bounding sphere of a v1.x bus + ~8 m array (array length: orbitcodex / skyrocket)
_SIGMA_BASE = (30.0, 300.0, 50.0)  # 1-sigma R, T, N position error, ~1-2 day old orbit (assumption)

_SCENARIOS: dict[str, _Scenario] = {
    "case-2021-07-01-css-starlink-1095": _Scenario(
        station_alt_km=390.0,  # UN note: "~390 km"
        starlink_alt_km=382.0,  # UN note: Starlink-1095 stayed at ~382 km after 16 May-24 Jun 2021
        starlink_inc_deg=53.0,  # Starlink shell 1 inclination (assumption; not in the UN note)
        station_sigma_rtn_m=_SIGMA_BASE, starlink_sigma_rtn_m=_SIGMA_BASE,
        station_mass_kg=TIANHE_KG + TIANZHOU_2_KG + SHENZHOU_KG,
        station_mass_low_kg=TIANHE_KG + TIANZHOU_DRY_KG + SHENZHOU_KG,
        docked="Tianhe + Tianzhou-2 (aft port) + Shenzhou-12 (crewed, docked 17 Jun-16 Sep 2021)",
        starlink_notes=("Starlink-1095 was holding station at ~382 km, so its orbit is modelled with the base covariance.",),
    ),
    "case-2021-10-21-css-starlink-2305": _Scenario(
        station_alt_km=390.0,
        # Altitude on 21 Oct is not published. A crossing needs equal radii, so the Starlink is taken at the
        # station's altitude while it passes through it (assumption).
        starlink_alt_km=390.0,
        starlink_inc_deg=53.0,
        station_sigma_rtn_m=_SIGMA_BASE,
        # "Maneuvering continuously, strategy unknown, orbital errors hard to assess" (UN note): inflate its
        # covariance x3 (assumption) because its future thrust is unmodelled.
        starlink_sigma_rtn_m=tuple(3.0 * s for s in _SIGMA_BASE),
        station_mass_kg=TIANHE_KG + TIANZHOU_2_KG + TIANZHOU_3_KG + SHENZHOU_KG,
        station_mass_low_kg=TIANHE_KG + 2 * TIANZHOU_DRY_KG + SHENZHOU_KG,
        docked="Tianhe + Tianzhou-2 (forward port) + Tianzhou-3 (aft port) + Shenzhou-13 (crewed, docked 16 Oct 2021)",
        starlink_notes=("Starlink-2305 was thrusting continuously, so its covariance is inflated x3 (assumption).",),
    ),
}


# --- Geometry ------------------------------------------------------------------------------------------
def _plane_normal(inc_deg: float, raan_deg: float) -> np.ndarray:
    i, o = math.radians(inc_deg), math.radians(raan_deg)
    return np.array([math.sin(i) * math.sin(o), -math.sin(i) * math.cos(o), math.cos(i)])


def _crossings(inc1: float, inc2: float, r1: float, r2: float, step_deg: float = 0.25):
    """Yield (rel_speed, d_raan, r1, v1, r2, v2) for both crossing points of two circular orbits, for every
    relative RAAN. Velocities are prograde circular speeds at each radius; positions share a direction."""
    n1 = _plane_normal(inc1, 0.0)
    v1m, v2m = math.sqrt(MU_KM3_S2 / r1), math.sqrt(MU_KM3_S2 / r2)
    for d_raan in np.arange(step_deg, 360.0, step_deg):
        n2 = _plane_normal(inc2, d_raan)
        line = np.cross(n1, n2)
        norm = np.linalg.norm(line)
        if norm < 1e-9:
            continue
        for u in (line / norm, -line / norm):
            va, vb = v1m * np.cross(n1, u), v2m * np.cross(n2, u)
            yield float(np.linalg.norm(vb - va)), float(d_raan), r1 * u, va, r2 * u, vb


def _typical_crossing(inc1: float, inc2: float, r1: float, r2: float):
    """The crossing whose relative speed is the median over all relative RAANs (deterministic)."""
    items = list(_crossings(inc1, inc2, r1, r2))
    median = float(np.median([it[0] for it in items]))
    return min(items, key=lambda it: (abs(it[0] - median), it[1]))


def _plane_covariance(basis_xy: np.ndarray, rows: list[tuple[np.ndarray, tuple[float, float, float]]]):
    total = np.zeros((3, 3))
    for rtn, sigma in rows:
        total += rtn.T @ np.diag(np.square(sigma)) @ rtn
    return basis_xy @ total @ basis_xy.T


def _ellipse(cov2: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    """(sigma_major, sigma_minor, angle_deg, major_axis) in screening's convention."""
    values, axes = np.linalg.eigh(cov2)
    major = axes[:, 1]
    return (math.sqrt(values[1]), math.sqrt(values[0]),
            math.degrees(math.atan2(major[1], major[0])) % 180.0, major)


def _miss_for_pc(major_m: float, minor_m: float, angle_deg: float, hbr_m: float, target_pc: float) -> float:
    """Distance along the major axis at which Pc falls to `target_pc` (Pc decreases monotonically there)."""
    lo, hi = 0.0, 40.0 * major_m
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        theta = math.radians(angle_deg)
        pc = collision_probability(mid * math.cos(theta), mid * math.sin(theta), major_m, minor_m, angle_deg, hbr_m)
        lo, hi = (mid, hi) if pc > target_pc else (lo, mid)
    return 0.5 * (lo + hi)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _geometry(case: dict, sc: _Scenario) -> tuple[Encounter, dict]:
    year, month, day = map(int, case["date"].split("-"))
    tca = datetime(year, month, day, *TCA_TIME_UTC, tzinfo=timezone.utc)
    r1, r2 = EARTH_RADIUS_KM + sc.station_alt_km, EARTH_RADIUS_KM + sc.starlink_alt_km
    _, d_raan, rp, vp, rs, vs = _typical_crossing(STATION_INC_DEG, sc.starlink_inc_deg, r1, r2)
    v_rel = vs - vp
    x_hat, y_hat = encounter_plane_basis(rp / np.linalg.norm(rp), v_rel)
    plane = np.vstack([x_hat, y_hat])
    cov2 = _plane_covariance(plane, [(rtn_basis(rp, vp), sc.station_sigma_rtn_m),
                                     (rtn_basis(rs, vs), sc.starlink_sigma_rtn_m)])
    major, minor, angle, axis = _ellipse(cov2)
    hbr = STATION_HBR_M + STARLINK_HBR_M
    miss_m = _miss_for_pc(major, minor, angle, hbr, EVENT_PC)
    # Re-place the secondary at the miss vector (perpendicular to v_rel by construction).
    rs = rp + (miss_m / 1000.0) * (axis[0] * x_hat + axis[1] * y_hat)
    crossing_deg = math.degrees(math.acos(float(np.clip(np.dot(vp, vs) / (np.linalg.norm(vp) * np.linalg.norm(vs)), -1, 1))))
    enc = Encounter(
        tca=tca, r_primary_km=rp, v_primary_kms=vp, r_secondary_km=rs, v_secondary_kms=vs,
        sigma_major_m=major, sigma_minor_m=minor, angle_deg=angle, hard_body_radius_m=hbr,
        primary_norad_id=case["station"]["noradId"], primary_name=case["station"]["name"],
        secondary_norad_id=case["starlink"]["noradId"], secondary_name=case["starlink"]["name"],
        range_t_sec=[float(t) for t in RANGE_SERIES_S],
    )
    return enc, {"relSpeedKms": float(np.linalg.norm(v_rel)), "dRaanDeg": d_raan, "crossingDeg": crossing_deg,
                 "missM": miss_m}


# --- Costing -----------------------------------------------------------------------------------------
def _risk(pc: float) -> str:
    return "critical" if pc >= CRITICAL_PC else "high" if pc >= HIGH_PC else "watch"


def _r4(value: float) -> float:
    return float(f"{value:.4g}")


def analyse(case: dict) -> dict:
    """Return {"conjunction", "optionsBySide", "reality", "assumptions"} for one case from
    app/casestudy/facts.py. See docs/case_studies/CONTRACT.md for every field and unit."""
    sc = _SCENARIOS.get(case["id"])
    if sc is None:
        raise ValueError(f"no reconstruction defined for case {case['id']!r}")
    enc, geo = _geometry(case, sc)
    station = Propulsion(sc.station_mass_kg, STATION_ISP_S, f"CSS: {sc.docked}, chemical thrusters")
    starlink = Propulsion(STARLINK_KG, STARLINK_ISP_S, "Starlink v1.x: ~260 kg, krypton Hall thrusters")
    now = enc.tca - timedelta(seconds=PLANNING_LEAD_S)
    plan_a = plan_maneuvers(enc, now=now, mover="primary", propulsion=station)
    plan_b = plan_maneuvers(enc, now=now, mover="secondary", propulsion=starlink)
    burns_a = [o for o in plan_a.options if o["direction"] != "none"]
    if not burns_a or not [o for o in plan_b.options if o["direction"] != "none"]:
        raise ValueError(f"planner found no burn within {MAX_DV_MS} m/s for {case['id']}")

    # Reality: cheapest station burn meeting the planner's target (see module docstring, step 5).
    cheapest = min(burns_a, key=lambda o: o["dvMs"])
    reality = {
        "moverNoradId": case["station"]["noradId"],
        "dvMs": cheapest["dvMs"],
        "propellantKg": _r4(propellant_kg(cheapest["dvMs"], station)),
        "massKg": sc.station_mass_kg,
        "ispS": STATION_ISP_S,
        "basis": (f"Reconstructed, not published: the cheapest station burn ({cheapest['direction']}, about "
                  f"{(enc.tca - datetime.fromisoformat(cheapest['burnAt'].replace('Z', '+00:00'))).total_seconds() / 3600:.0f} h "
                  f"before TCA) that reaches Pc <= {PC_TARGET:g} and a {MIN_MISS_TARGET_M:g} m miss, the same target the "
                  "planner uses, so it is (up to the planner's 0.01 m/s rounding) a lower bound on what the station spent."),
    }
    low_prop = _r4(propellant_kg(cheapest["dvMs"], Propulsion(sc.station_mass_low_kg, STATION_ISP_S, "")))

    pc0 = plan_a.current_pc
    cov_angle = enc.angle_deg
    rel = np.asarray(enc.r_secondary_km) - np.asarray(enc.r_primary_km)
    rtn = rtn_basis(np.asarray(enc.r_primary_km), np.asarray(enc.v_primary_kms)) @ rel * 1000.0
    detail = {
        "id": case["id"],
        "primary": {"noradId": case["station"]["noradId"], "name": case["station"]["name"],
                    "type": "PAYLOAD", "maneuverable": True},
        "secondary": {"noradId": case["starlink"]["noradId"], "name": case["starlink"]["name"],
                      "type": "PAYLOAD", "maneuverable": True},
        "tca": _iso(enc.tca),
        "missDistanceM": round(plan_a.current_miss_m, 1),
        "rtnM": {"r": round(float(rtn[0]), 1) + 0.0, "t": round(float(rtn[1]), 1) + 0.0, "n": round(float(rtn[2]), 1) + 0.0},
        "relSpeedKms": round(geo["relSpeedKms"], 3),
        "pc": float(f"{pc0:.3g}"),
        "risk": _risk(pc0),
        "rangeSeries": [
            {"tSec": float(t), "rangeKm": round(float(np.linalg.norm(rel + (np.asarray(enc.v_secondary_kms) - np.asarray(enc.v_primary_kms)) * t)), 4)}
            for t in RANGE_SERIES_S
        ],
        "afterSeries": plan_a.after_series,
        "covariance": {"sigmaMajorM": round(enc.sigma_major_m, 1), "sigmaMinorM": round(enc.sigma_minor_m, 1),
                       "angleDeg": round(cov_angle, 1)},
        "hardBodyRadiusM": enc.hard_body_radius_m,
        "options": plan_a.options,
        "brief": "",
    }
    tca_s = f"{enc.tca:%Y-%m-%d %H:%M} UTC"
    assumptions = [
        f"Method: reconstruction from published altitudes/inclinations; no historical element sets were used "
        f"(Space-Track GP_HISTORY needs an account). TCA, miss, Pc and covariance were never published.",
        f"TCA: {tca_s}. Only the date ({case['date']}) is published; the time of day is an assumption.",
        f"Station orbit: circular, {sc.station_alt_km:g} km, i = {STATION_INC_DEG} deg (UN note A/AC.105/1262).",
        f"Starlink orbit: circular, {sc.starlink_alt_km:g} km, i = {sc.starlink_inc_deg:g} deg. "
        + ("Altitude: UN note (~382 km); inclination: Starlink shell-1 value, assumption." if "1095" in case["id"]
           else "Altitude at TCA and inclination are assumptions (Starlink shell-1 inclination)."),
        f"Crossing geometry: relative RAAN is unpublished, so the crossing with the median relative speed over all "
        f"RAANs is used (RAAN offset {geo['dRaanDeg']:g} deg, orbit-plane crossing angle {geo['crossingDeg']:.0f} deg, "
        f"relative speed {geo['relSpeedKms']:.2f} km/s). Assumption.",
        f"Covariance (1-sigma R/T/N position, metres): station {sc.station_sigma_rtn_m}, Starlink "
        f"{tuple(round(s, 1) for s in sc.starlink_sigma_rtn_m)}; order of magnitude for 1-2 day old orbits, assumption. "
        f"Rotated into the encounter plane and summed: {enc.sigma_major_m:.0f} x {enc.sigma_minor_m:.0f} m, "
        f"angle {cov_angle:.0f} deg.",
        *sc.starlink_notes,
        f"Hard-body radius: {STATION_HBR_M:g} m station + {STARLINK_HBR_M:g} m Starlink = {enc.hard_body_radius_m:g} m "
        "(bounding spheres; assumption).",
        f"Miss distance: {geo['missM']:.0f} m along the covariance major axis, chosen so Pc = {EVENT_PC:g} (just above "
        f"the planner's {PC_MANEUVER_THRESHOLD:g} burn threshold). The real value was not published and the US said "
        "its own Pc estimate was not significant, so this is the mildest event the planner would act on; burns "
        "below are floors, not worst cases.",
        f"Planning epoch {PLANNING_LEAD_S / 3600:.0f} h before TCA (assumption); policy: Pc <= {PC_TARGET:g}, "
        f"miss >= {MIN_MISS_TARGET_M:g} m, burn <= {MAX_DV_MS:g} m/s, as in app.physics.maneuver.",
        f"Station mass {sc.station_mass_kg:,.0f} kg = {sc.docked}, using launch masses: Tianhe 22,500 kg, "
        "Tianzhou-2 13,640 kg (Wikipedia), Tianzhou-3 ~13,500 kg (state media), Shenzhou 7,840 kg (Wikipedia/spacefacts). "
        "Propellant and cargo used since launch are not subtracted.",
        f"Mass sensitivity: with Tianzhou at its 6,640 kg dry mass ({sc.station_mass_low_kg:,.0f} kg total) the same burn "
        f"would use {low_prop:g} kg instead of {reality['propellantKg']:g} kg.",
        f"Station Isp {STATION_ISP_S:g} s: typical storable bipropellant (assumption; same value as the ISS in the live planner).",
        f"Starlink: {STARLINK_KG:g} kg (SpaceX v1.x figure, space.skyrocket.de), krypton Hall thrusters, Isp {STARLINK_ISP_S:g} s "
        "(not published; assumption). Burns are treated as impulsive, which understates a low-thrust electric burn "
        "that takes tens of minutes.",
        "Costs: Tsiolkovsky equation via maneuver.propellant_kg, Clohessy-Wiltshire burn effects via maneuver.plan_maneuvers; "
        "propellant shown to 4 significant figures.",
        "Burn sizes are rounded up to the planner's 0.01 m/s grid, so the smallest burn it can report is 0.01 m/s; "
        "the true minimum may be lower, and propellant for the cheapest options moves in steps of that size.",
        *(([f"Published altitudes are approximate (\"~\"). The circular orbits are {abs(sc.station_alt_km - sc.starlink_alt_km):g} km "
            "apart in radius, which alone would give a miss of at least that much, so the miss is imposed (see above) "
            "rather than derived from the elements."]) if sc.station_alt_km != sc.starlink_alt_km else ()),
        "Reality: the real station burn is not public. Modelled as the cheapest station burn that meets the planner's "
        "target (a lower bound, up to rounding). The real burn used an unknown lead time and margin.",
    ]
    return {"conjunction": detail, "optionsBySide": {"a": plan_a.options, "b": plan_b.options},
            "reality": reality, "assumptions": assumptions}
