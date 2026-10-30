"""Breakup cascade simulation behind POST /api/cascade.

Returns a dict shaped exactly like `CascadeResult` (frontend/src/api/types.ts). Pipeline:

1. Breakup: NASA Standard Breakup Model (NSBM; Johnson et al. 2001, "NASA's new breakup model of
   EVOLVE 4.0") for fragments with characteristic length >= 10 cm, the UI's "tracked" size.
2. Orbits: each fragment's velocity kick is applied to the parent state, giving its perigee/apogee.
3. Decay: atmospheric drag with an exponential atmosphere and the King-Hele orbit-averaged density,
   integrated in 10-day steps.
4. Environment: catalog and fragments are binned into altitude shells by time-weighted Keplerian
   residence (the "particle-in-a-box" picture used by NASA/ESA long-term models). Over years, J2
   precession smears nodes, so a shell model is reasonable.
5. Secondary collisions: kinetic-gas collision rate between fragments and intact objects in each
   shell. New breakups feed back into the population (the cascade).

This is an approximate engineering model for an environmental-impact story, not a validated
long-term forecast like NASA LEGEND or ESA DELTA. Every constant below is labelled as a source
value or an assumption.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

MU_KM3_S2 = 398600.4418  # Earth GM, km^3/s^2
R_E_KM = 6378.137  # WGS-84 equatorial radius
SECONDS_PER_YEAR = 365.25 * 86400.0

MAX_YEARS = 25  # the frontend slider range (1-25)
STEPS_PER_YEAR = 36  # ~10-day drag steps; fine for decay over years, not for final-day re-entry timing

# --- NSBM parameters -----------------------------------------------------------------------------
LC_MIN_M = 0.10  # 10 cm: the "tracked fragments > 10 cm" the UI reports
LC_MAX_M = 2.0  # assumption: cap on sampled fragment size (largest pieces of an upper stage)
EXPLOSION_SCALING_S = 1.0  # NSBM S factor; 1.0 for rocket bodies, used for all parents (assumption)
CATASTROPHIC_EMR_J_PER_G = 40.0  # NSBM catastrophic threshold, energy-to-target-mass ratio
IMPACT_SPEED_KMS = 10.0  # typical mean LEO collision speed (assumption, widely quoted ~10 km/s)
IMPACTOR_ON_INTACT_KG = 10.0  # assumption: an intact parent is struck by a 10 kg fragment
INTACT_TARGET_KG = 800.0  # assumption: a debris parent (or a secondary event) strikes an 800 kg satellite
CD_FRAGMENT = 2.2  # flat-plate free-molecular drag coefficient commonly used for debris

# --- Drag decay ----------------------------------------------------------------------------------
REENTRY_PERIGEE_KM = 120.0  # below this, decay takes days; drop the object from the census

# Vallado, "Fundamentals of Astrodynamics and Applications", Table 8-4: exponential atmosphere
# (base altitude km, base density kg/m^3, scale height km). Represents mean solar activity.
_ATMOS = np.array([
    (0, 1.225, 7.249), (25, 3.899e-2, 6.349), (30, 1.774e-2, 6.682), (40, 3.972e-3, 7.554),
    (50, 1.057e-3, 8.382), (60, 3.206e-4, 7.714), (70, 8.770e-5, 6.549), (80, 1.905e-5, 5.799),
    (90, 3.396e-6, 5.382), (100, 5.297e-7, 5.877), (110, 9.661e-8, 7.263), (120, 2.438e-8, 9.473),
    (130, 8.484e-9, 12.636), (140, 3.845e-9, 16.149), (150, 2.070e-9, 22.523), (180, 5.464e-10, 29.740),
    (200, 2.789e-10, 37.105), (250, 7.248e-11, 45.546), (300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298),
    (400, 3.725e-12, 58.515), (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822), (600, 1.454e-13, 71.835),
    (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64), (900, 5.245e-15, 181.05), (1000, 3.019e-15, 268.00),
])

# --- Environment / risk --------------------------------------------------------------------------
# Assumption: mean cross-section between a >= 10 cm fragment and an intact object (radius ~1.8 m).
COLLISION_CROSS_SECTION_KM2 = 10.0e-6
# Satellite counted "at higher risk" when fragments raise its local conjunction rate by >= 10 %.
AT_RISK_RATE_INCREASE = 0.10
# Assumption: net growth of the tracked catalog from new launches. Recent years have added
# roughly 2-3 thousand tracked objects per year (ESA Space Environment Reports). Launched objects
# are not decayed or added to the collision targets.
LAUNCH_RATE_PER_YEAR = 2500
MAX_SECONDARY_EVENTS = 100  # compute guard against runaway feedback; never reached in tests

# Mass assumptions (kg). Breakup yield scales with mass, and OMM carries none.
_MASS_BY_NORAD: dict[int, float] = {
    22285: 8900.0,  # SL-16 R/B (Zenit-2 second stage), ~8.9 t dry
    25544: 420000.0,  # ISS
}
_MASS_BY_TYPE: dict[str, float] = {"PAYLOAD": 800.0, "ROCKET_BODY": 1400.0, "DEBRIS": 1.0, "UNKNOWN": 100.0}
# Ballistic coefficient Cd*A/m (m^2/kg) when BSTAR is missing or non-positive. Assumptions.
_B_BY_TYPE: dict[str, float] = {"PAYLOAD": 0.01, "ROCKET_BODY": 0.005, "DEBRIS": 0.05, "UNKNOWN": 0.02}
# SGP4 reference: B* = B * rho0 * R_E / 2 with rho0 * R_E = 0.15696615 kg/m^2 (Vallado / Spacetrack #3).
_BSTAR_TO_B = 2.0 / 0.15696615

Event = Literal["collision", "explosion"]


# --- Small helpers -------------------------------------------------------------------------------
def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Read a contract field from a dict or a Pydantic/attribute object."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _num(omm: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(omm.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def assumed_mass_kg(norad_id: int, object_type: str) -> float:
    return _MASS_BY_NORAD.get(int(norad_id), _MASS_BY_TYPE.get(object_type, _MASS_BY_TYPE["UNKNOWN"]))


def atmosphere(h_km: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Density (kg/m^3) and scale height (km). Above 1000 km the last layer is extended."""
    h = np.asarray(h_km, float)
    idx = np.clip(np.searchsorted(_ATMOS[:, 0], h, side="right") - 1, 0, len(_ATMOS) - 1)
    base, rho0, scale = _ATMOS[idx, 0], _ATMOS[idx, 1], _ATMOS[idx, 2]
    return rho0 * np.exp(-(h - base) / scale), scale


def _i0e(x: np.ndarray) -> np.ndarray:
    """exp(-x) * I0(x) for x >= 0 (Abramowitz & Stegun 9.8.1/9.8.2, relative error < 1e-6).
    Much faster than np.i0, which dominated the decay loop."""
    x = np.asarray(x, float)
    t = x / 3.75
    small = np.exp(-x) * (1 + t**2 * (3.5156229 + t**2 * (3.0899424 + t**2 * (1.2067492 + t**2 * (
        0.2659732 + t**2 * (0.0360768 + t**2 * 0.0045813))))))
    u = 3.75 / np.maximum(x, 3.75)
    large = (0.39894228 + u * (0.01328592 + u * (0.00225319 + u * (-0.00157565 + u * (0.00916281 + u * (
        -0.02057706 + u * (0.02635537 + u * (-0.01647633 + u * 0.00392377)))))))) / np.sqrt(np.maximum(x, 3.75))
    return np.where(x <= 3.75, small, large)


def _ballistic_from_omm(omm: Mapping[str, Any], object_type: str) -> float:
    bstar = _num(omm, "BSTAR", 0.0)
    if bstar <= 0:
        return _B_BY_TYPE.get(object_type, _B_BY_TYPE["UNKNOWN"])
    # Clip to physical bounds: dense intact bodies ~1e-4, light fragments ~1 m^2/kg.
    return float(np.clip(bstar * _BSTAR_TO_B, 1e-4, 1.0))


def _perigee_apogee_from_omm(omm: Mapping[str, Any]) -> tuple[float, float]:
    n = _num(omm, "MEAN_MOTION") * 2 * math.pi / 86400.0
    if n <= 0:
        return math.nan, math.nan
    a = (MU_KM3_S2 / n**2) ** (1 / 3)
    e = min(max(_num(omm, "ECCENTRICITY"), 0.0), 0.99)
    return a * (1 - e), a * (1 + e)


def _parent_state(omm: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Perifocal position/velocity at the OMM epoch from mean elements.

    SGP4 mean elements differ from osculating ones by a few km; that is negligible against
    breakup kicks of ~100 m/s. Orientation does not matter, because kicks are isotropic and the
    shell model is orientation-free.
    """
    n = _num(omm, "MEAN_MOTION") * 2 * math.pi / 86400.0
    a = (MU_KM3_S2 / n**2) ** (1 / 3)
    e = min(max(_num(omm, "ECCENTRICITY"), 0.0), 0.99)
    M = math.radians(_num(omm, "MEAN_ANOMALY"))
    E = M if e < 0.8 else math.pi
    for _ in range(30):  # Newton iteration on Kepler's equation
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))
    p = a * (1 - e * e)
    r = p / (1 + e * math.cos(nu))
    k = math.sqrt(MU_KM3_S2 / p)
    return (np.array([r * math.cos(nu), r * math.sin(nu), 0.0]),
            np.array([-k * math.sin(nu), k * (e + math.cos(nu)), 0.0]))


# --- NSBM ----------------------------------------------------------------------------------------
def collision_fragment_yield(projectile_kg, target_kg, speed_kms: float = IMPACT_SPEED_KMS):
    """NSBM collision: N(>=Lc) = 0.1 * M^0.75 * Lc^-1.71. Accepts scalars or arrays.

    Catastrophic (EMR >= 40 J/g): M is the sum of both masses. Otherwise M = m_projectile * v^2,
    with v in km/s.
    """
    projectile = np.asarray(projectile_kg, float)
    emr = 0.5 * projectile * (speed_kms * 1000.0) ** 2 / (target_kg * 1000.0)
    M = np.where(emr >= CATASTROPHIC_EMR_J_PER_G, projectile + target_kg, projectile * speed_kms**2)
    result = 0.1 * M**0.75 * LC_MIN_M**-1.71
    return float(result) if result.ndim == 0 else result


def explosion_fragment_yield(scaling: float = EXPLOSION_SCALING_S) -> float:
    """NSBM explosion: N(>=Lc) = 6 * S * Lc^-1.6 (independent of mass)."""
    return 6.0 * scaling * LC_MIN_M**-1.6


def _area_to_mass_log10(rng: np.random.Generator, lam: np.ndarray, rocket_body: bool) -> np.ndarray:
    """NSBM bimodal A/M distribution (log10 m^2/kg) for Lc > 11 cm. Piecewise-linear parameters in
    lambda = log10(Lc) are written as clamped np.interp breakpoints."""
    if rocket_body:
        alpha = np.interp(lam, [-1.4, 0.0], [1.0, 0.5])
        mu1, s1 = np.interp(lam, [-0.5, 0.0], [-0.45, -0.9]), np.full_like(lam, 0.55)
        mu2, s2 = np.full_like(lam, -0.9), np.interp(lam, [-1.0, 0.1], [0.28, 0.1])
    else:
        alpha = np.interp(lam, [-1.95, 0.55], [0.0, 1.0])
        mu1, s1 = np.interp(lam, [-1.1, 0.0], [-0.6, -0.95]), np.interp(lam, [-1.3, -0.3], [0.1, 0.3])
        mu2, s2 = np.interp(lam, [-0.7, -0.1], [-1.2, -2.0]), np.interp(lam, [-0.5, -0.3], [0.5, 0.3])
    first = rng.random(lam.size) < alpha
    return np.where(first, rng.normal(mu1, s1), rng.normal(mu2, s2))


@dataclass
class Fragments:
    lc_m: np.ndarray
    mass_kg: np.ndarray
    ballistic: np.ndarray  # Cd*A/m, m^2/kg
    dv_ms: np.ndarray


def sample_fragments(rng: np.random.Generator, count: int, event: Event, rocket_body: bool, mass_budget_kg: float) -> Fragments:
    """Sample NSBM fragments (size, A/M, delta-v), keeping total mass <= the colliding mass."""
    beta = 1.71 if event == "collision" else 1.6
    u = rng.random(count)
    k = (LC_MIN_M / LC_MAX_M) ** beta
    lc = LC_MIN_M * (1 - u * (1 - k)) ** (-1 / beta)  # truncated power law, inverse CDF
    chi = _area_to_mass_log10(rng, np.log10(lc), rocket_body)
    area = 0.556945 * lc**2.0047077  # NSBM average cross-section for Lc > 1.67 mm
    mass = area / 10**chi
    # NSBM delta-v: log10(dv m/s) ~ N(mu, 0.4), mu = 0.9 chi + 2.9 (collision) or 0.2 chi + 1.85 (explosion).
    mu = 0.9 * chi + 2.9 if event == "collision" else 0.2 * chi + 1.85
    dv = 10 ** rng.normal(mu, 0.4)
    # Mass conservation: the NSBM count does not depend on mass for explosions, so a 1 kg parent
    # would otherwise produce ~240 fragments weighing more than itself.
    keep = np.cumsum(mass) <= mass_budget_kg
    keep[0] = True
    return Fragments(lc[keep], mass[keep], CD_FRAGMENT * area[keep] / mass[keep], dv[keep])


def _kick_to_orbits(rng: np.random.Generator, r: np.ndarray, v: np.ndarray, dv_ms: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Isotropic kicks (NSBM assumption). Returns perigee radius, apogee radius and a bound mask."""
    d = rng.normal(size=(dv_ms.size, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    vel = v + d * (dv_ms[:, None] / 1000.0)
    rmag = float(np.linalg.norm(r))
    energy = 0.5 * np.sum(vel**2, axis=1) - MU_KM3_S2 / rmag
    h2 = np.sum(np.cross(r, vel) ** 2, axis=1)
    bound = energy < 0
    a = np.where(bound, -MU_KM3_S2 / (2 * np.where(bound, energy, -1.0)), np.nan)
    e = np.sqrt(np.maximum(0.0, 1 + 2 * energy * h2 / MU_KM3_S2**2))
    return a * (1 - e), a * (1 + e), bound


# --- Drag decay ----------------------------------------------------------------------------------
def decay_step(rp: np.ndarray, ra: np.ndarray, ballistic: np.ndarray, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
    """One explicit step of drag decay, radii in km.

    da/dt = -B * rho_avg * sqrt(mu * a)
    rho_avg = rho(perigee) * exp(-x) * I0(x), x = a*e/H (King-Hele orbit-averaged density).
    Eccentric orbits lose apogee at fixed perigee (King-Hele's result for e >> H/a); near-circular
    orbits shrink uniformly.
    """
    a = 0.5 * (rp + ra)
    e = (ra - rp) / (ra + rp)
    rho, scale = atmosphere(rp - R_E_KM)
    factor = _i0e(a * e / scale)
    da_km = -ballistic * rho * factor * np.sqrt(MU_KM3_S2 * 1e9 * a * 1e3) * dt_s / 1000.0
    eccentric = e > 1e-3
    new_ra = np.where(eccentric, np.maximum(ra + 2 * da_km, rp), ra + da_km)
    new_rp = np.where(eccentric, rp, rp + da_km)
    return new_rp, new_ra


@dataclass
class _Population:
    rp: np.ndarray
    ra: np.ndarray
    ballistic: np.ndarray
    mass: np.ndarray

    def decay(self, years: float, steps_per_year: int = STEPS_PER_YEAR) -> None:
        steps = max(1, round(years * steps_per_year)) if years > 0 else 0
        if not steps:
            return
        dt = years * SECONDS_PER_YEAR / steps
        for _ in range(steps):
            self.rp, self.ra = decay_step(self.rp, self.ra, self.ballistic, dt)
            self._drop_reentered()

    def _drop_reentered(self) -> None:
        alive = (self.rp - R_E_KM) >= REENTRY_PERIGEE_KM
        if not alive.all():
            self.rp, self.ra, self.ballistic, self.mass = self.rp[alive], self.ra[alive], self.ballistic[alive], self.mass[alive]

    def extend(self, other: "_Population") -> None:
        self.rp = np.concatenate([self.rp, other.rp])
        self.ra = np.concatenate([self.ra, other.ra])
        self.ballistic = np.concatenate([self.ballistic, other.ballistic])
        self.mass = np.concatenate([self.mass, other.mass])


# --- Shell densities -----------------------------------------------------------------------------
def _shell_edges_r_km() -> np.ndarray:
    """20 km shells to 2000 km (LEO detail), then 250 km shells to above GEO."""
    alt = np.concatenate([np.arange(100.0, 2000.0, 20.0), np.arange(2000.0, 36500.0 + 1, 250.0)])
    return R_E_KM + alt


def _residence_weights(rp: np.ndarray, ra: np.ndarray, edges_r: np.ndarray, chunk: int = 4000) -> np.ndarray:
    """Fraction of each orbit's period spent in each shell, shape (n, shells).

    The time-in-radius CDF follows from Kepler's equation: F(r) = (E - e sin E) / pi with
    cos E = (1 - r/a) / e. Near-circular orbits degenerate to a step at r = a.
    """
    out = np.empty((rp.size, edges_r.size - 1), dtype=np.float32)
    edges32 = edges_r.astype(np.float32)[None, :]  # float32 halves the cost; shares are ~1e-7 accurate
    for start in range(0, rp.size, chunk):
        p, q = rp[start:start + chunk, None].astype(np.float32), ra[start:start + chunk, None].astype(np.float32)
        a = 0.5 * (p + q)
        e = np.maximum((q - p) / (q + p), np.float32(1e-7))
        E = np.arccos(np.clip((1 - edges32 / a) / e, -1.0, 1.0))
        cdf = (E - e * np.sin(E)) / np.pi
        out[start:start + chunk] = np.diff(cdf, axis=1)
    return out


def _shell_counts(rp: np.ndarray, ra: np.ndarray, edges_r: np.ndarray) -> np.ndarray:
    if rp.size == 0:
        return np.zeros(edges_r.size - 1)
    return _residence_weights(rp, ra, edges_r).sum(axis=0, dtype=np.float64)


@dataclass
class CatalogEnvironment:
    """Per-catalog precomputation. Independent of the cascade request; cache it per catalog sync."""

    object_count: int
    edges_r_km: np.ndarray
    volume_km3: np.ndarray
    density_all: np.ndarray  # objects / km^3 per shell, whole catalog
    density_intact: np.ndarray  # payloads + rocket bodies only (collision targets)
    active_weights: np.ndarray  # (active payloads, shells) residence fractions
    survivors_by_year: np.ndarray  # catalog objects still in orbit at year 0..MAX_YEARS (no launches)


def build_environment(catalog: Iterable[Any]) -> CatalogEnvironment:
    edges = _shell_edges_r_km()
    volume = 4.0 / 3.0 * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    rp, ra, ballistic, intact, active = [], [], [], [], []
    for obj in catalog:
        omm = _field(obj, "omm") or {}
        p, q = _perigee_apogee_from_omm(omm)
        if not math.isfinite(p):
            continue
        kind = str(_field(obj, "type", "UNKNOWN"))
        rp.append(p)
        ra.append(q)
        ballistic.append(_ballistic_from_omm(omm, kind))
        intact.append(kind in ("PAYLOAD", "ROCKET_BODY"))
        active.append(kind == "PAYLOAD" and bool(_field(obj, "active", False)))
    rp_a, ra_a = np.array(rp), np.array(ra)
    intact_a, active_a = np.array(intact, bool), np.array(active, bool)
    weights = _residence_weights(rp_a, ra_a, edges) if rp_a.size else np.zeros((0, edges.size - 1), np.float32)
    density_all = weights.sum(axis=0, dtype=np.float64) / volume
    density_intact = weights[intact_a].sum(axis=0, dtype=np.float64) / volume
    survivors = _catalog_survivors(rp_a, ra_a, np.array(ballistic))
    return CatalogEnvironment(len(rp), edges, volume, density_all, density_intact, weights[active_a], survivors)


def _catalog_survivors(rp: np.ndarray, ra: np.ndarray, ballistic: np.ndarray) -> np.ndarray:
    """Objects remaining each year with no new launches, under the same drag model."""
    counts = np.empty(MAX_YEARS + 1, dtype=np.int64)
    # Objects with perigee above ~2500 km see no measurable drag over 25 years.
    low = (rp - R_E_KM) < 2500.0
    high_count = int((~low).sum())
    pop = _Population(rp[low].copy(), ra[low].copy(), ballistic[low].copy(), np.zeros(int(low.sum())))
    pop._drop_reentered()
    counts[0] = pop.rp.size + high_count
    for year in range(1, MAX_YEARS + 1):
        # Monthly steps: the baseline is a count of ~30k objects, so 3x coarser steps keep the
        # request fast; the error only affects objects in their final months.
        pop.decay(1.0, steps_per_year=12)
        counts[year] = pop.rp.size + high_count
    return counts


# --- Cascade -------------------------------------------------------------------------------------
def _spread(dv_ms: np.ndarray) -> dict:
    return {"mean": round(float(dv_ms.mean()), 1), "sd": round(float(dv_ms.std()), 1)}


def _seed(norad_id: int, event: Event) -> int:
    """Deterministic per request, so identical requests return identical (cacheable) results."""
    return (int(norad_id) * 1_000_003 + (17 if event == "collision" else 29)) % 2_147_483_647


def _breakup_population(rng: np.random.Generator, r: np.ndarray, v: np.ndarray, count: int, event: Event,
                        rocket_body: bool, mass_budget_kg: float) -> tuple[_Population, Fragments, np.ndarray]:
    """Returns the orbiting population, all sampled fragments, and the mask of those left in orbit."""
    frags = sample_fragments(rng, count, event, rocket_body, mass_budget_kg)
    rp, ra, bound = _kick_to_orbits(rng, r, v, frags.dv_ms)
    keep = bound & ((rp - R_E_KM) >= REENTRY_PERIGEE_KM)
    pop = _Population(rp[keep], ra[keep], frags.ballistic[keep], frags.mass_kg[keep])
    return pop, frags, keep


def simulate_cascade(
    parent: Any,
    catalog: Iterable[Any] | None = None,
    *,
    event: Event,
    years: float,
    include_launches: bool,
    environment: CatalogEnvironment | None = None,
) -> dict:
    """Run the breakup scenario. `parent` and catalog items are `CatalogObject`s (dicts or models).

    Pass a cached `environment` (from `build_environment`) to skip the ~1 s catalog precomputation.
    Raises ValueError for an unknown event or a parent without usable orbital elements.
    """
    if event not in ("collision", "explosion"):
        raise ValueError("event must be 'collision' or 'explosion'")
    horizon = int(max(1, min(MAX_YEARS, round(float(years)))))  # same clamp as the mock handler
    if environment is None:
        if catalog is None:
            raise ValueError("catalog or environment is required")
        environment = build_environment(catalog)

    norad_id = int(_field(parent, "noradId"))
    kind = str(_field(parent, "type", "UNKNOWN"))
    omm = dict(_field(parent, "omm") or {})
    if _num(omm, "MEAN_MOTION") <= 0:
        raise ValueError("Parent object has no usable MEAN_MOTION")
    seed = _seed(norad_id, event)
    rng = np.random.default_rng(seed)
    r0, v0 = _parent_state(omm)
    inclination = math.radians(_num(omm, "INCLINATION"))

    mass = assumed_mass_kg(norad_id, kind)
    if event == "explosion":
        count, budget = explosion_fragment_yield(), mass
    elif kind == "DEBRIS":
        # A debris parent cannot break up much by itself; model it striking an intact satellite.
        count, budget = collision_fragment_yield(mass, INTACT_TARGET_KG), mass + INTACT_TARGET_KG
    else:
        count = collision_fragment_yield(IMPACTOR_ON_INTACT_KG, mass)
        budget = mass + IMPACTOR_ON_INTACT_KG
    pop, primary, in_orbit = _breakup_population(rng, r0, v0, int(round(count)), event, kind == "ROCKET_BODY", budget)
    fragment_count = int(primary.dv_ms.size)

    env = environment
    sigma_v_vol = COLLISION_CROSS_SECTION_KM2 * IMPACT_SPEED_KMS * SECONDS_PER_YEAR * env.volume_km3
    weights = env.active_weights

    def baseline_total(year: int) -> int:
        return int(env.survivors_by_year[year] + (LAUNCH_RATE_PER_YEAR * year if include_launches else 0))

    def scale(year: int) -> float:
        # Assumption: baseline density changes uniformly with total object count.
        return baseline_total(year) / max(1, env.object_count)

    def fragment_density() -> np.ndarray:
        return _shell_counts(pop.rp, pop.ra, env.edges_r_km) / env.volume_km3

    def shell_rates(year: int, density_f: np.ndarray) -> np.ndarray:
        return density_f * env.density_intact * scale(year) * sigma_v_vol  # collisions / year / shell

    def stats(year: int, density_f: np.ndarray) -> dict:
        exposure_f = weights @ density_f.astype(np.float32)
        exposure_b = weights @ (env.density_all * scale(year)).astype(np.float32)
        total_b = float(exposure_b.sum())
        extra = 100.0 * float(exposure_f.sum()) / total_b if total_b > 0 else 0.0
        at_risk = int(np.count_nonzero((exposure_f > 0) & (exposure_f >= AT_RISK_RATE_INCREASE * exposure_b)))
        base = baseline_total(year)
        return {
            "year": year,
            "trackedTotal": base + int(pop.rp.size),
            "baselineTotal": base,
            "extraConjunctionsPct": round(extra, 1),
            "satellitesAtRisk": at_risk,
        }

    density = fragment_density()
    rows = [stats(0, density)]
    secondary: list[dict] = []
    rate_prev = shell_rates(0, density)
    cumulative = 0.0
    for year in range(1, horizon + 1):
        pop.decay(1.0)
        density = fragment_density()
        rate_now = shell_rates(year, density)
        total_prev, total_now = float(rate_prev.sum()), float(rate_now.sum())
        # Trapezoidal integral of the expected number of collisions over the year. An event is
        # placed each time the expected cumulative count crosses an integer (expected-value
        # timeline, which keeps the demo stable rather than sampling Poisson noise).
        next_cumulative = cumulative + 0.5 * (total_prev + total_now)
        events_before = len(secondary)
        k = math.floor(cumulative) + 1
        while k <= next_cumulative and len(secondary) < MAX_SECONDARY_EVENTS:
            frac = (k - cumulative) / (next_cumulative - cumulative)
            when = year - 1 + frac
            shell = int(np.argmax(rate_now)) if total_now > 0 else int(np.argmax(rate_prev))
            alt_km = 0.5 * (env.edges_r_km[shell] + env.edges_r_km[shell + 1]) - R_E_KM
            # Expected NSBM yield when a random surviving fragment strikes an intact satellite.
            n_new = int(round(float(collision_fragment_yield(pop.mass, INTACT_TARGET_KG).mean()))) if pop.mass.size else 0
            r_c = R_E_KM + alt_km
            new_pop, new_frags, _ = _breakup_population(
                rng, np.array([r_c, 0.0, 0.0]), np.array([0.0, math.sqrt(MU_KM3_S2 / r_c), 0.0]),
                n_new, "collision", False, INTACT_TARGET_KG + float(pop.mass.max(initial=0.0)))
            new_pop.decay(year - when)
            u = rng.uniform(0, 2 * math.pi)
            secondary.append({
                "year": round(when, 1),
                # Latitude of a point on an orbit with the parent's inclination (J2 spreads nodes,
                # so the longitude is effectively random).
                "latDeg": round(math.degrees(math.asin(math.sin(inclination) * math.sin(u))), 1),
                "lonDeg": round(float(rng.uniform(-180.0, 180.0)), 1),
                "altKm": round(alt_km),
                "fragments": int(new_frags.dv_ms.size),
            })
            pop.extend(new_pop)
            k += 1
        cumulative = next_cumulative
        if len(secondary) > events_before:  # new fragments joined this year
            density = fragment_density()
        rows.append(stats(year, density))
        rate_prev = shell_rates(year, density)

    return {
        "parent": {
            "noradId": norad_id,
            "name": _field(parent, "name", ""),
            "type": kind,
            "maneuverable": bool(_field(parent, "maneuverable", False)),
            "omm": omm,
        },
        "fragmentCount": fragment_count,
        # Spread of the fragments that stay in orbit, i.e. the cloud the globe draws. NSBM's log-normal
        # tail (kicks of km/s) mostly escapes or re-enters at once and would dominate the raw sd.
        "spreadDvMs": _spread(primary.dv_ms[in_orbit] if in_orbit.any() else primary.dv_ms),
        "seed": seed,
        "years": rows,
        "secondaryCollisions": secondary,
    }
