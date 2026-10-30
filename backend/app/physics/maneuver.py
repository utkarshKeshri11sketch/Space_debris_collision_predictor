"""Collision-avoidance maneuver planning.

Produces the `options` (ManeuverOption[]) and `afterSeries` fields of `ConjunctionDetail`
(frontend/src/api/types.ts). Output dicts use the contract's camelCase keys and units:
metres for miss distance, m/s for delta-v, kg for propellant, ISO 8601 UTC for burn time.

Model summary (each assumption is commented where it is used):
- Pc: 2-D Gaussian integrated over the hard-body disk in the encounter plane. This is the
  standard short-encounter (Foster/Chan) assumption, valid for the ~10 km/s LEO encounters we screen.
- Burn effect: Clohessy-Wiltshire (Hill) impulsive response of the mover from the burn time to TCA,
  linearised about the mover's unperturbed orbit (near-circular, small delta-v).
- Encounter geometry: straight-line relative motion over the few seconds around TCA.

Options offered (per the role brief): along-track burns, prograde and retrograde, at different lead
times, plus "No action". Along-track burns are what LEO operators normally use: they are the cheapest
way to shift the arrival time at the conjunction point. Radial and normal burns are still modelled by
`cw_displacement_km` but not offered.

Entry points:
- `options(detail)` / `options_for(detail, mover_norad_id)`: work from a contract ConjunctionDetail
  alone (see `encounter_from_detail` for the geometry this reconstructs).
- `plan_maneuvers(encounter)`: exact geometry when screening supplies state vectors at TCA.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal

import numpy as np

MU_KM3_S2 = 398600.4418  # Earth GM (WGS-84/EGM-96), km^3/s^2
G0_MS2 = 9.80665  # standard gravity, used in the rocket equation

# --- Operational policy defaults (all overridable per call) -----------------------------------
# Pc at or above which a burn is recommended. 1e-4 is the common "red" threshold used by NASA CARA
# and ESA's Space Debris Office. Below it, burns are still listed but "No action" is recommended.
PC_MANEUVER_THRESHOLD = 1e-4
# Post-maneuver goal: two orders of magnitude below the 1e-5 "yellow" level, leaving margin for
# covariance growth before the burn. Assumption, not a regulatory number.
PC_TARGET = 1e-7
# Also require at least 1 km of miss distance, so a tiny covariance cannot produce a "safe" 50 m miss.
MIN_MISS_TARGET_M = 1000.0
# Upper bound on a single avoidance burn. Typical LEO avoidance burns are 0.1-1 m/s; 5 m/s is generous.
MAX_DV_MS = 5.0
# Lead-time profiles (time of the burn before TCA). The trade-off: an earlier burn needs less delta-v
# (along-track drift grows ~3*dv*t), but it acts on a less mature prediction, because covariance
# shrinks as TCA approaches. Mock fixtures use 4-6 h. All three values are assumptions.
NOMINAL_LEAD_S = 6 * 3600.0  # recommended balance
EARLY_LEAD_S = 18 * 3600.0  # cheapest, least certain
LATE_LEAD_S = 2 * 3600.0  # last practical opportunity, most expensive
# Time needed to plan, approve and uplink a burn. Assumption.
MIN_COMMAND_MARGIN_S = 2 * 3600.0
# Burns earlier than this are not planned, because predictions this far out are usually re-screened.
MAX_LEAD_S = 24 * 3600.0

Direction = Literal["prograde", "retrograde", "radial", "normal", "none"]
Mover = Literal["primary", "secondary"]


# --- Spacecraft propulsion assumptions ---------------------------------------------------------
@dataclass(frozen=True)
class Propulsion:
    mass_kg: float
    isp_s: float
    note: str


# Public order-of-magnitude figures, used only to turn delta-v into propellant. Not operator data.
# Kept identical to the mass/Isp in app/ai/profiles.py so negotiator text and option costs agree.
_PROPULSION_BY_NORAD: dict[int, Propulsion] = {
    25544: Propulsion(420_000.0, 300.0, "ISS: ~420 t stack, Zvezda/Progress bipropellant thrusters (~300 s)"),
}
_PROPULSION_BY_NAME_PREFIX: tuple[tuple[str, Propulsion], ...] = (
    ("ISS", Propulsion(420_000.0, 300.0, "ISS: ~420 t stack, Zvezda/Progress bipropellant thrusters (~300 s)")),
    ("STARLINK", Propulsion(800.0, 1500.0, "Starlink v2-mini class: ~800 kg, Hall-effect thrusters (Isp ~1500 s assumed)")),
    ("ONEWEB", Propulsion(150.0, 1600.0, "OneWeb: ~150 kg, xenon Hall-effect thrusters (Isp ~1600 s assumed)")),
    *((prefix, Propulsion(1000.0, 220.0, "Single Earth-observation satellite: ~1 t, hydrazine (~220 s)"))
      for prefix in ("CARTOSAT", "OCEANSAT", "NOAA", "SENTINEL", "LANDSAT", "FENGYUN", "METOP")),
)
DEFAULT_PROPULSION = Propulsion(500.0, 220.0, "Default: 500 kg spacecraft, hydrazine monopropellant (~220 s)")


def propulsion_for(norad_id: int | None, name: str | None) -> Propulsion:
    if norad_id is not None and norad_id in _PROPULSION_BY_NORAD:
        return _PROPULSION_BY_NORAD[norad_id]
    upper = (name or "").upper()
    for prefix, propulsion in _PROPULSION_BY_NAME_PREFIX:
        if upper.startswith(prefix):
            return propulsion
    return DEFAULT_PROPULSION


def propellant_kg(dv_ms: float, propulsion: Propulsion) -> float:
    """Tsiolkovsky: m_prop = m0 * (1 - exp(-dv / (Isp * g0))). Treats the burn as impulsive, which
    understates low-thrust (electric) burns that take minutes to hours."""
    return propulsion.mass_kg * (1.0 - math.exp(-dv_ms / (propulsion.isp_s * G0_MS2)))


# --- Encounter description (filled by screening; see docs/CONTRACT_REQUESTS.md PHYS-1) ---------
@dataclass(frozen=True)
class Encounter:
    """States of both objects at TCA in one inertial frame (TEME from SGP4 is fine).

    Covariance is the combined 2-D covariance in the encounter plane, in contract form. The angle
    runs counter-clockwise from the plane's radial axis; the frontend plots it with R horizontal
    and N vertical.
    """

    tca: datetime
    r_primary_km: Sequence[float]
    v_primary_kms: Sequence[float]
    r_secondary_km: Sequence[float]
    v_secondary_kms: Sequence[float]
    sigma_major_m: float
    sigma_minor_m: float
    angle_deg: float
    hard_body_radius_m: float
    primary_norad_id: int | None = None
    primary_name: str | None = None
    secondary_norad_id: int | None = None
    secondary_name: str | None = None
    range_t_sec: Sequence[float] | None = None  # rangeSeries grid; default -60..60 s step 1.5 s


@dataclass
class ManeuverPlan:
    options: list[dict]
    after_series: list[dict] | None
    current_miss_m: float
    current_pc: float
    mover: Mover
    # Extra context for the AI brief/negotiator, not part of the HTTP contract.
    notes: list[str] = field(default_factory=list)

    def to_contract(self) -> dict:
        out: dict = {"options": self.options}
        if self.after_series is not None:
            out["afterSeries"] = self.after_series
        return out


# --- Geometry helpers ----------------------------------------------------------------------------
def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def rtn_basis(r_km: np.ndarray, v_kms: np.ndarray) -> np.ndarray:
    """Rows are the radial, transverse (along-track) and normal unit vectors."""
    r_hat = _unit(r_km)
    n_hat = _unit(np.cross(r_km, v_kms))
    t_hat = np.cross(n_hat, r_hat)
    return np.vstack([r_hat, t_hat, n_hat])


def encounter_plane_basis(radial_hat: np.ndarray, v_rel_kms: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x = primary radial projected perpendicular to v_rel; y = v_rel_hat cross x.

    Same convention as app/physics/screening.py, which defines `covariance.angleDeg`. For LEO
    crossings the relative velocity always has a negative along-track part
    (v_s - v_p = v (cos(theta) - 1, sin(theta)) in T/N), so y lies close to +N, as the frontend's
    encounter plot assumes.
    """
    w = _unit(v_rel_kms)
    x = radial_hat - np.dot(radial_hat, w) * w
    if np.linalg.norm(x) < 1e-9:  # v_rel parallel to radial: pick any perpendicular axis
        x = np.cross(w, [0.0, 0.0, 1.0]) if abs(w[2]) < 0.9 else np.cross(w, [1.0, 0.0, 0.0])
    x = _unit(x)
    return x, np.cross(w, x)


def cw_displacement_km(n_rad_s: float, t_s: float, dv_rtn_kms: np.ndarray) -> np.ndarray:
    """Clohessy-Wiltshire position offset (R, T, N) at time t after an impulse dv from zero offset.

    Assumes a circular reference orbit; the error grows with eccentricity and with t over many orbits
    (it ignores drag and J2). A prograde impulse gives the classic secular drift of -3*dv*t along-track.
    """
    vx, vy, vz = dv_rtn_kms
    nt = n_rad_s * t_s
    s, c = math.sin(nt), math.cos(nt)
    x = vx / n_rad_s * s + 2.0 * vy / n_rad_s * (1.0 - c)
    y = 2.0 * vx / n_rad_s * (c - 1.0) + vy * (4.0 * s - 3.0 * nt) / n_rad_s
    z = vz / n_rad_s * s
    return np.array([x, y, z])


def mean_motion_rad_s(r_km: np.ndarray, v_kms: np.ndarray) -> float:
    a = 1.0 / (2.0 / np.linalg.norm(r_km) - np.dot(v_kms, v_kms) / MU_KM3_S2)
    return math.sqrt(MU_KM3_S2 / a**3)


# --- Collision probability -----------------------------------------------------------------------
_SQRT2 = math.sqrt(2.0)


def _gauss_interval_scalar(a: float, b: float) -> float:
    """P(a < Z < b) for standard normal Z, a <= b. Uses the tail-appropriate form, so tiny
    probabilities (1e-10 and below) keep full relative precision instead of cancelling."""
    if a >= 0:
        return 0.5 * (math.erfc(a / _SQRT2) - math.erfc(b / _SQRT2))
    if b <= 0:
        return 0.5 * (math.erfc(-b / _SQRT2) - math.erfc(-a / _SQRT2))
    return 0.5 * (math.erf(b / _SQRT2) - math.erf(a / _SQRT2))


_gauss_interval_ufunc = np.frompyfunc(_gauss_interval_scalar, 2, 1)


def _gauss_interval(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return _gauss_interval_ufunc(a, b).astype(float)


@lru_cache(maxsize=8)
def _legendre(nodes: int) -> tuple[np.ndarray, np.ndarray]:
    return np.polynomial.legendre.leggauss(nodes)


def collision_probability(
    miss_x_m: float,
    miss_y_m: float,
    sigma_major_m: float,
    sigma_minor_m: float,
    angle_deg: float,
    hard_body_radius_m: float,
    nodes: int = 64,
) -> float:
    """2-D Pc: Gaussian N(0, C) integrated over the disk of radius HBR centred at the miss vector.

    The miss vector is rotated into the covariance principal axes, the inner integral is done exactly
    with erfc, and the outer integral uses Gauss-Legendre with the substitution x = R sin(theta),
    which removes the square-root endpoint behaviour.
    """
    R = float(hard_body_radius_m)
    if R <= 0:
        return 0.0
    # Floor the sigmas at 1 cm to avoid dividing by zero; real covariances are metres to kilometres.
    sx, sy = max(float(sigma_major_m), 0.01), max(float(sigma_minor_m), 0.01)
    th = math.radians(angle_deg)
    u = miss_x_m * math.cos(th) + miss_y_m * math.sin(th)
    w = -miss_x_m * math.sin(th) + miss_y_m * math.cos(th)
    if min(sx, sy) < R / 10:
        nodes = max(nodes, 256)  # a narrow Gaussian inside the disk needs a finer grid
    t, wts = _legendre(nodes)
    theta = t * (math.pi / 2)
    x = R * np.sin(theta)
    h = R * np.cos(theta)
    jac = R * np.cos(theta) * (math.pi / 2)
    px = np.exp(-0.5 * ((u + x) / sx) ** 2) / (sx * math.sqrt(2 * math.pi))
    py = _gauss_interval((w - h) / sy, (w + h) / sy)
    return float(min(1.0, max(0.0, np.sum(wts * jac * px * py))))


# --- Planner -------------------------------------------------------------------------------------
_TANGENTIAL: tuple[tuple[Direction, tuple[float, float, float]], ...] = (
    ("prograde", (0.0, 1.0, 0.0)),
    ("retrograde", (0.0, -1.0, 0.0)),
)
_LEAD_PROFILES = (("nominal", NOMINAL_LEAD_S), ("early", EARLY_LEAD_S), ("late", LATE_LEAD_S))


def _iso(dt: datetime) -> str:
    """Same format as JavaScript's Date.toISOString(): millisecond precision with a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _leads_near(period_s: float, window_s: float, target_s: float, count: int = 5) -> list[float]:
    """Quarter-orbit multiples inside the burn window, closest to the target lead.

    The phase of the CW response matters, so searching a few neighbouring quarter orbits finds a
    cheaper burn than the exact target time.
    """
    step = period_s / 4.0
    if window_s < step:
        # Too close to TCA for a quarter orbit. Offer the latest burn possible if ≥ 10 min remain.
        return [window_s] if window_s >= 600.0 else []
    leads = [k * step for k in range(1, int(window_s // step) + 1)]
    target = min(target_s, window_s)
    return sorted(leads, key=lambda lead: abs(lead - target))[:count]


@dataclass
class _Candidate:
    direction: Direction
    profile: str
    dv_ms: float
    lead_s: float
    miss_xy_m: np.ndarray
    rel_new_km: np.ndarray


def plan_maneuvers(
    enc: Encounter,
    *,
    now: datetime | None = None,
    mover: Mover = "primary",
    current_pc: float | None = None,
    current_miss_m: float | None = None,
    pc_threshold: float = PC_MANEUVER_THRESHOLD,
    pc_target: float = PC_TARGET,
    min_miss_m: float = MIN_MISS_TARGET_M,
    max_dv_ms: float = MAX_DV_MS,
    propulsion: Propulsion | None = None,
) -> ManeuverPlan:
    """Up to four along-track burns plus the "No action" baseline. Options in order:

    A: the cheaper of prograde and retrograde at the nominal lead (recommended when Pc >= threshold)
    B: the other direction at the nominal lead
    C: A's direction, burned early (cheapest delta-v, least mature prediction)
    D: A's direction, burned late (last opportunity, most delta-v)
    Profiles that collapse onto the same burn time (TCA close) are dropped.

    `mover` selects which spacecraft burns, so the negotiator can cost a burn for each operator.
    `current_pc` / `current_miss_m` override the "No action" row with screening's own numbers.
    """
    now = now or datetime.now(timezone.utc)
    rp, vp = np.asarray(enc.r_primary_km, float), np.asarray(enc.v_primary_kms, float)
    rs, vs = np.asarray(enc.r_secondary_km, float), np.asarray(enc.v_secondary_kms, float)
    rel = rs - rp  # secondary relative to primary, km
    v_rel = vs - vp
    x_hat, y_hat = encounter_plane_basis(_unit(rp), v_rel)

    # At TCA the relative position is (to first order) perpendicular to v_rel, so its plane
    # projection is the miss vector.
    def miss_xy(r_rel_km: np.ndarray) -> np.ndarray:
        return np.array([np.dot(r_rel_km, x_hat), np.dot(r_rel_km, y_hat)]) * 1000.0

    def pc_of(m_xy: np.ndarray) -> float:
        return collision_probability(m_xy[0], m_xy[1], enc.sigma_major_m, enc.sigma_minor_m,
                                     enc.angle_deg, enc.hard_body_radius_m)

    m0 = miss_xy(rel)
    miss0 = float(np.linalg.norm(m0))
    pc0 = float(current_pc) if current_pc is not None else pc_of(m0)
    reported_miss0 = float(current_miss_m) if current_miss_m is not None else miss0

    r_m, v_m = (rp, vp) if mover == "primary" else (rs, vs)
    basis = rtn_basis(r_m, v_m)
    n = mean_motion_rad_s(r_m, v_m)
    period = 2 * math.pi / n
    # A burn by the primary moves it by +d, so secondary-minus-primary changes by -d.
    sign = -1.0 if mover == "primary" else 1.0
    tca = enc.tca if enc.tca.tzinfo else enc.tca.replace(tzinfo=timezone.utc)
    window = min(MAX_LEAD_S, (tca - now).total_seconds() - MIN_COMMAND_MARGIN_S)
    name = enc.primary_name if mover == "primary" else enc.secondary_name
    norad = enc.primary_norad_id if mover == "primary" else enc.secondary_norad_id
    propulsion = propulsion or propulsion_for(norad, name)
    if miss0 >= min_miss_m and pc0 <= pc_target:
        # Already safe: every "burn" would be 0 m/s. List the cost of doubling the miss distance
        # instead, so operators can still compare a margin-raising burn. Policy choice, not physics.
        min_miss_m = 2.0 * miss0

    def feasible(m_xy: np.ndarray) -> bool:
        # Check the cheap miss-distance condition first; Pc is only evaluated when it passes.
        return float(np.linalg.norm(m_xy)) >= min_miss_m and pc_of(m_xy) <= pc_target

    grid = np.geomspace(0.005, max_dv_ms, 48)

    def cheapest(axis: tuple[float, float, float], lead: float) -> tuple[float, np.ndarray] | None:
        # Relative-position change per 1 m/s of delta-v (CW takes km/s).
        per_ms = sign * (basis.T @ cw_displacement_km(n, lead, np.array(axis) * 1e-3))
        hit = next((k for k, s in enumerate(grid) if feasible(miss_xy(rel + s * per_ms))), None)
        if hit is None:
            return None
        lo, hi = (0.0 if hit == 0 else grid[hit - 1]), grid[hit]
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            lo, hi = (lo, mid) if feasible(miss_xy(rel + mid * per_ms)) else (mid, hi)
        # Round up to the 0.01 m/s the UI shows. Re-check, because Pc need not be monotonic in dv.
        dv = math.ceil(hi * 100.0 - 1e-9) / 100.0
        if not feasible(miss_xy(rel + dv * per_ms)):
            dv = hi
        return dv, rel + dv * per_ms

    best: dict[tuple[str, Direction], _Candidate] = {}
    for profile, target in _LEAD_PROFILES:
        for direction, axis in _TANGENTIAL:
            for lead in _leads_near(period, window, target):
                found = cheapest(axis, lead)
                key = (profile, direction)
                if found and (key not in best or found[0] < best[key].dv_ms):
                    best[key] = _Candidate(direction, profile, found[0], lead, miss_xy(found[1]), found[1])

    nominal = sorted((c for (p, _), c in best.items() if p == "nominal"), key=lambda c: (c.dv_ms, c.direction))
    chosen: list[_Candidate] = list(nominal)
    if nominal:
        for profile in ("early", "late"):
            c = best.get((profile, nominal[0].direction))
            # Skip a profile whose burn falls within an hour of one already offered.
            if c and all(abs(c.lead_s - o.lead_s) > 3600 or c.direction != o.direction for o in chosen):
                chosen.append(c)

    recommend_burn = pc0 >= pc_threshold and bool(chosen)
    options: list[dict] = []
    notes = [
        f"Mover: {mover} ({name or 'unknown'}). {propulsion.note}.",
        f"Targets: Pc <= {pc_target:g} and miss >= {min_miss_m:g} m; burn recommended when Pc >= {pc_threshold:g}.",
    ]
    for index, c in enumerate(chosen):
        label = "ABCD"[index]
        options.append({
            "id": f"option-{label.lower()}",
            "label": label,
            "direction": c.direction,
            "dvMs": c.dv_ms,
            "burnAt": _iso(tca - timedelta(seconds=c.lead_s)),
            "newMissM": round(float(np.linalg.norm(c.miss_xy_m)), 1),
            "newPc": float(f"{pc_of(c.miss_xy_m):.3g}"),
            # 4 significant figures: electric-propulsion burns use grams, and 0.0 would break comparisons.
            "propellantKg": float(f"{propellant_kg(c.dv_ms, propulsion):.4g}"),
            "recommended": recommend_burn and index == 0,
        })
        notes.append(f"Option {label} ({c.profile} burn): {c.dv_ms:.2f} m/s {c.direction}, "
                     f"{c.lead_s / 3600:.1f} h before TCA.")
    options.append(_no_action(reported_miss0, pc0, recommended=not recommend_burn))
    if window < 600.0:
        notes.append("TCA is too close for a commanded burn; only 'No action' is available.")

    after_series = None
    if recommend_burn:
        t_grid = enc.range_t_sec if enc.range_t_sec is not None else [(i - 40) * 1.5 for i in range(81)]
        rel_new = chosen[0].rel_new_km
        # Straight-line relative motion is accurate to metres over +-60 s at LEO encounter speeds.
        after_series = [
            {"tSec": float(t), "rangeKm": round(float(np.linalg.norm(rel_new + v_rel * t)), 4)}
            for t in t_grid
        ]
    return ManeuverPlan(options, after_series, reported_miss0, pc0, mover, notes)


def _no_action(miss_m: float, pc: float, *, recommended: bool) -> dict:
    return {
        "id": "no-action",
        "label": "No action",
        "direction": "none",
        "dvMs": 0.0,
        "burnAt": None,
        "newMissM": round(float(miss_m), 1),
        "newPc": float(f"{float(pc):.3g}"),
        "propellantKg": 0.0,
        "recommended": recommended,
    }


# --- Adapters from the HTTP contract -------------------------------------------------------------
DEFAULT_ORBIT_RADIUS_KM = 6378.137 + 400.0  # used only when no primary OMM is given (assumption)


def _parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def encounter_from_detail(detail: Mapping[str, Any], *, primary_omm: Mapping[str, Any] | None = None) -> Encounter:
    """Rebuild encounter geometry from contract fields alone (tca, rtnM, relSpeedKms, covariance, HBR).

    The contract omits state vectors, so this assumes:
    - The primary is on a circular orbit. Its radius comes from `primary_omm` MEAN_MOTION when given,
      otherwise a 400 km altitude.
    - Both objects fly horizontally at the same speed, which is true for near-circular LEO orbits
      meeting at one altitude. So v_rel lies in the local T-N plane, and the crossing angle follows
      from |v_rel| = 2 v sin(theta / 2).
    - The sign of v_rel's N component is the one most perpendicular to rtnM, because the miss vector
      at TCA is perpendicular to v_rel.
    When screening supplies real states at TCA, build an `Encounter` directly instead.
    """
    radius = DEFAULT_ORBIT_RADIUS_KM
    if primary_omm and float(primary_omm.get("MEAN_MOTION") or 0) > 0:
        n = float(primary_omm["MEAN_MOTION"]) * 2 * math.pi / 86400.0
        radius = (MU_KM3_S2 / n**2) ** (1 / 3)
    speed = math.sqrt(MU_KM3_S2 / radius)
    # Local frame: x = R, y = T, z = N of the primary at TCA.
    rp, vp = np.array([radius, 0.0, 0.0]), np.array([0.0, speed, 0.0])
    rtn = detail["rtnM"]
    miss_km = np.array([float(rtn["r"]), float(rtn["t"]), float(rtn["n"])]) / 1000.0
    theta = 2 * math.asin(min(1.0, float(detail["relSpeedKms"]) / (2 * speed)))
    candidates = [speed * np.array([0.0, math.cos(theta), s * math.sin(theta)]) for s in (1.0, -1.0)]
    vs = min(candidates, key=lambda v: abs(np.dot(v - vp, miss_km)))
    cov = detail["covariance"]
    series = detail.get("rangeSeries") or []
    return Encounter(
        tca=_parse_iso(detail["tca"]),
        r_primary_km=rp, v_primary_kms=vp, r_secondary_km=rp + miss_km, v_secondary_kms=vs,
        sigma_major_m=float(cov["sigmaMajorM"]), sigma_minor_m=float(cov["sigmaMinorM"]),
        angle_deg=float(cov["angleDeg"]), hard_body_radius_m=float(detail["hardBodyRadiusM"]),
        primary_norad_id=int(detail["primary"]["noradId"]), primary_name=detail["primary"].get("name"),
        secondary_norad_id=int(detail["secondary"]["noradId"]), secondary_name=detail["secondary"].get("name"),
        range_t_sec=[float(p["tSec"]) for p in series] or None,
    )


def encounter_from_screening(screened: Any) -> Encounter:
    """Exact geometry from an `app.physics.screening.Encounter` (duck-typed, so this module does not
    import sgp4): TEME states at TCA, combined covariance in the shared encounter-plane convention,
    and the combined hard-body radius."""
    cov = screened.covariance
    return Encounter(
        tca=screened.tca,
        r_primary_km=screened.primary_position_km, v_primary_kms=screened.primary_velocity_km_s,
        r_secondary_km=screened.secondary_position_km, v_secondary_kms=screened.secondary_velocity_km_s,
        sigma_major_m=float(cov["sigmaMajorM"]), sigma_minor_m=float(cov["sigmaMinorM"]),
        angle_deg=float(cov["angleDeg"]), hard_body_radius_m=float(screened.uncertainty.hard_body_radius_m),
        primary_norad_id=int(screened.primary.norad_id), primary_name=screened.primary.catalog.get("name"),
        secondary_norad_id=int(screened.secondary.norad_id), secondary_name=screened.secondary.catalog.get("name"),
        range_t_sec=[(i - 40) * 1.5 for i in range(81)],  # screening's rangeSeries grid
    )


def plan_for_detail(
    detail: Mapping[str, Any],
    mover_norad_id: int | None = None,
    *,
    now: datetime | None = None,
    encounter: Encounter | None = None,
    primary_omm: Mapping[str, Any] | None = None,
    **policy: Any,
) -> ManeuverPlan:
    """Plan for one conjunction. `plan.to_contract()` gives the `options` and `afterSeries` fields.

    The mover defaults to the primary if it can maneuver, otherwise the secondary. If the chosen
    object cannot maneuver (debris, rocket body), only "No action" is returned.
    """
    primary, secondary = detail["primary"], detail["secondary"]
    if mover_norad_id is None:
        mover_norad_id = primary["noradId"] if primary.get("maneuverable") or not secondary.get("maneuverable") else secondary["noradId"]
    if int(mover_norad_id) == int(primary["noradId"]):
        mover, ref = "primary", primary
    elif int(mover_norad_id) == int(secondary["noradId"]):
        mover, ref = "secondary", secondary
    else:
        raise ValueError(f"NORAD {mover_norad_id} is not part of conjunction {detail.get('id')}")
    miss, pc = float(detail["missDistanceM"]), float(detail["pc"])
    if not ref.get("maneuverable"):
        return ManeuverPlan([_no_action(miss, pc, recommended=True)], None, miss, pc, mover,
                            [f"{ref.get('name')} cannot maneuver; only 'No action' applies."])
    enc = encounter or encounter_from_detail(detail, primary_omm=primary_omm)
    return plan_maneuvers(enc, now=now, mover=mover, current_pc=pc, current_miss_m=miss, **policy)


def options_for(detail: Mapping[str, Any], mover_norad_id: int, **kwargs: Any) -> list[dict]:
    """ManeuverOption[] if `mover_norad_id` is the object that moves (used by the AI negotiator)."""
    return plan_for_detail(detail, mover_norad_id, **kwargs).options


def options(detail: Mapping[str, Any], **kwargs: Any) -> list[dict]:
    """ManeuverOption[] for the default mover (primary if maneuverable, else the secondary)."""
    return plan_for_detail(detail, **kwargs).options


