"""Selected-object SGP4 screening; no downloads, API routes, or synthetic events.

Contract: frontend/src/api/types.ts. TEME states are km and km/s internally;
public distances/covariances are m/m^2. Call ``screen_catalog`` on a cached
CatalogObject sequence, supplying an explicit ``risk_model`` at each TCA.
Public GP elements contain neither covariance nor hard-body size, so this
module deliberately has no default Pc model. See tests/screening/README.md.

Physics assumptions: Earth-centred UTC/TEME SGP4 with WGS72; independent
Gaussian position errors specified in each object's RTN frame *at TCA*;
short, rectilinear encounters for 2-D Pc. Correlated errors and long-duration
co-orbital encounters require a different risk model. No orbit manoeuvres
are assumed. The broad-phase acceleration bound is explicit in settings.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sgp4 import omm
from sgp4.api import SGP4_ERRORS, Satrec, SatrecArray, jday

UTC = timezone.utc
DAY_S = 86400.0
FloatArray = NDArray[np.float64]
OBJECT_TYPES = {"PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN"}


class ScreeningError(ValueError):
    """Invalid input or physics outside this screening model's domain."""


def _positive(value: float, name: str, *, zero: bool = False) -> None:
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ScreeningError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


@dataclass(frozen=True)
class ScreeningConfig:
    # Demo search envelope, NOT an operational safety threshold.
    max_miss_distance_m: float = 10000.0
    step_seconds: float = 60.0
    time_chunk_intervals: int = 128
    satellite_batch_size: int = 128
    tca_tolerance_seconds: float = 0.001
    # 0.03 km/s^2 exceeds twice surface gravity (~0.0196). Assume this
    # bounds relative acceleration for non-decayed Earth orbits. Chord
    # interpolation error <= a_rel * dt^2 / 8; this pads the broad phase.
    max_relative_acceleration_km_s2: float = 0.03
    # Quality policy, not a GP covariance estimate. Entire requested window
    # must be within this distance of each element epoch.
    max_epoch_age_days: float = 14.0
    # Reject slow encounters rather than apply short-encounter Pc silently.
    minimum_relative_speed_km_s: float = 0.01
    # Product categories (matches mock ordering); not flight rules.
    critical_pc: float = 1e-4
    high_pc: float = 1e-5

    def __post_init__(self) -> None:
        for name in ("max_miss_distance_m", "step_seconds", "tca_tolerance_seconds",
                     "max_relative_acceleration_km_s2", "max_epoch_age_days",
                     "minimum_relative_speed_km_s"):
            _positive(getattr(self, name), name)
        if not 0 < self.high_pc < self.critical_pc <= 1:
            raise ScreeningError("require 0 < high_pc < critical_pc <= 1")
        if self.step_seconds > 60 or self.tca_tolerance_seconds >= self.step_seconds:
            raise ScreeningError("step_seconds must be <= 60 and greater than TCA tolerance")
        for name in ("time_chunk_intervals", "satellite_batch_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ScreeningError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class EncounterUncertainty:
    """Covariances in each spacecraft's RTN frame at this encounter's TCA.

    ``hard_body_radius_m`` is the SUM of both bounding radii. ``source`` must
    describe covariance/size provenance. Set ``illustrative=True`` for all
    guessed, calibrated, or demonstration inputs; the detail brief retains
    this label. These covariance matrices are not propagated from OMM epochs.
    """

    primary_covariance_rtn_m2: ArrayLike
    secondary_covariance_rtn_m2: ArrayLike
    hard_body_radius_m: float
    source: str
    illustrative: bool

    def __post_init__(self) -> None:
        for name in ("primary_covariance_rtn_m2", "secondary_covariance_rtn_m2"):
            matrix = _covariance(getattr(self, name), 3)
            matrix.setflags(write=False)
            object.__setattr__(self, name, matrix)
        _positive(self.hard_body_radius_m, "hard_body_radius_m")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ScreeningError("uncertainty source is required")
        if not isinstance(self.illustrative, bool):
            raise ScreeningError("illustrative must explicitly be True or False")


RiskModel = Callable[[Mapping[str, Any], Mapping[str, Any], datetime], EncounterUncertainty]


def _covariance(value: ArrayLike, size: int) -> FloatArray:
    matrix = np.array(value, dtype=float, copy=True)
    if matrix.shape != (size, size) or not np.isfinite(matrix).all():
        raise ScreeningError(f"covariance must be a finite {size}x{size} matrix in m^2")
    if not np.allclose(matrix, matrix.T, rtol=1e-10, atol=1e-10):
        raise ScreeningError("covariance must be symmetric")
    matrix = (matrix + matrix.T) / 2
    if np.linalg.eigvalsh(matrix)[0] <= 0:
        raise ScreeningError("covariance must be positive definite")
    return matrix


def _utc(value: datetime | str, *, omm_epoch: bool = False) -> datetime:
    date = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(date, datetime):
        raise ScreeningError("time must be an ISO string or datetime")
    if date.tzinfo is None or date.utcoffset() is None:
        if not omm_epoch:
            raise ScreeningError("screening times must include a UTC offset")
        # CCSDS/CelesTrak GP epochs without an offset are UTC.
        date = date.replace(tzinfo=UTC)
    return date.astimezone(UTC)


def _iso(date: datetime) -> str:
    return date.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, Mapping):
        raise ScreeningError("catalog entries must be CatalogObject mappings or Pydantic models")
    return dict(value)


def _catalog_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ScreeningError("NORAD ID must be an integer from 1 through 999999999")
    try:
        number = int(value)
        if number != float(value) or not 1 <= number <= 999999999:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScreeningError("NORAD ID must be an integer from 1 through 999999999") from exc
    return number


@dataclass(frozen=True)
class CatalogRecord:
    catalog: dict[str, Any]
    satellite: Satrec
    epoch: datetime

    @property
    def norad_id(self) -> int:
        return self.catalog["noradId"]

    def object_ref(self) -> dict[str, Any]:
        return {key: self.catalog[key] for key in ("noradId", "name", "type", "maneuverable")}


def record_from_catalog(value: Any) -> CatalogRecord:
    """Initialize directly from OMM, preserving 6-9 digit external identity.

    The sgp4 library uses a legacy Alpha-5 field for its inert identification
    metadata. For IDs above its 339999 limit, use internal satnum=0 and keep
    the full ID in CatalogRecord. No TLE is constructed and no dynamics are
    altered: satnum is unused by propagation. Never use Satrec.satnum as a
    catalog key; use CatalogRecord.norad_id.
    """
    catalog = _mapping(value)
    number = _catalog_id(catalog.get("noradId"))
    if not isinstance(catalog.get("name"), str) or not catalog["name"].strip():
        raise ScreeningError("catalog name is required")
    if catalog.get("type") not in OBJECT_TYPES:
        raise ScreeningError("invalid catalog object type")
    if not isinstance(catalog.get("maneuverable"), bool):
        raise ScreeningError("maneuverable must be boolean")
    fields = _mapping(catalog.get("omm"))
    if _catalog_id(fields.get("NORAD_CAT_ID")) != number:
        raise ScreeningError("catalog noradId disagrees with OMM NORAD_CAT_ID")
    for key, expected in (("CENTER_NAME", "EARTH"), ("REF_FRAME", "TEME"),
                          ("TIME_SYSTEM", "UTC"), ("MEAN_ELEMENT_THEORY", "SGP4")):
        # GP JSON omits these redundant standard metadata values.
        if fields.get(key, expected) != expected:
            raise ScreeningError(f"unsupported OMM {key}: expected {expected}")
    epoch = _utc(fields.get("EPOCH"), omm_epoch=True)
    required = ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
                "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")
    for key in required:
        try:
            numeric = float(fields[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ScreeningError(f"missing or invalid OMM {key}") from exc
        if not math.isfinite(numeric):
            raise ScreeningError(f"nonfinite OMM {key}")
        fields[key] = numeric
    if not (fields["MEAN_MOTION"] > 0 and 0 <= fields["ECCENTRICITY"] < 1
            and 0 <= fields["INCLINATION"] <= 180):
        raise ScreeningError("invalid OMM mean motion, eccentricity, or inclination")
    for key in ("RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"):
        if not 0 <= fields[key] <= 360:
            raise ScreeningError(f"OMM {key} must be between 0 and 360 degrees")
    fields["EPOCH"] = epoch.strftime("%Y-%m-%dT%H:%M:%S.%f")
    fields["NORAD_CAT_ID"] = number if number <= 339999 else 0
    # Non-dynamic metadata defaults permit the compact frontend GP shape.
    for key, default in (("OBJECT_ID", ""), ("CLASSIFICATION_TYPE", "U"), ("EPHEMERIS_TYPE", 0),
                         ("ELEMENT_SET_NO", 0), ("REV_AT_EPOCH", 0)):
        fields.setdefault(key, default)
    satellite = Satrec()
    omm.initialize(satellite, fields)
    if satellite.error:
        raise ScreeningError(f"OMM initialization: {SGP4_ERRORS.get(satellite.error, satellite.error)}")
    catalog["noradId"] = number
    return CatalogRecord(catalog, satellite, epoch)


def _dates(start: datetime, seconds: FloatArray) -> tuple[FloatArray, FloatArray]:
    jd, fraction = jday(start.year, start.month, start.day, start.hour,
                        start.minute, start.second + start.microsecond / 1e6)
    fractions = fraction + seconds / DAY_S
    days = np.floor(fractions)
    return np.full(seconds.shape, jd) + days, fractions - days


def state_at(record: CatalogRecord, at: datetime | str) -> tuple[FloatArray, FloatArray]:
    """TEME position km and velocity km/s; raises on every SGP4 error."""
    jd, fraction = _dates(_utc(at), np.array([0.0]))
    error, position, velocity = record.satellite.sgp4(float(jd[0]), float(fraction[0]))
    if error:
        raise ScreeningError(f"NORAD {record.norad_id}: {SGP4_ERRORS.get(error, error)}")
    result = np.asarray(position, dtype=float), np.asarray(velocity, dtype=float)
    if not all(np.isfinite(vector).all() for vector in result):
        raise ScreeningError(f"NORAD {record.norad_id}: nonfinite propagated state")
    return result


def rtn_basis(position_km: ArrayLike, velocity_km_s: ArrayLike) -> FloatArray:
    """Rows transform TEME vectors into primary RTN (T is transverse)."""
    position, velocity = np.asarray(position_km, dtype=float), np.asarray(velocity_km_s, dtype=float)
    if position.shape != (3,) or velocity.shape != (3,) or not np.isfinite([position, velocity]).all():
        raise ScreeningError("RTN requires finite 3D position and velocity")
    radial_norm = np.linalg.norm(position)
    normal = np.cross(position, velocity)
    normal_norm = np.linalg.norm(normal)
    if radial_norm == 0 or normal_norm == 0:
        raise ScreeningError("cannot define RTN for degenerate orbital state")
    radial, normal = position / radial_norm, normal / normal_norm
    return np.vstack((radial, np.cross(normal, radial), normal))


@lru_cache(maxsize=5)
def _quadrature(order: int) -> tuple[FloatArray, FloatArray]:
    return np.polynomial.legendre.leggauss(order)


def collision_probability(mean_m: ArrayLike, covariance_m2: ArrayLike, radius_m: float) -> float:
    """Integrate a 2D Gaussian over the combined hard-body circle.

    Rotate into covariance eigenaxes; analytically integrate the second axis
    with erfc (avoids tail cancellation), then use converging Gauss-Legendre
    quadrature on x=R*sin(theta). Clip only tails beyond 12 sigma (<4e-33).
    Reference: NASA CARA Spacecraft CA Best Practices Handbook, 2D Pc.
    """
    mean = np.asarray(mean_m, dtype=float)
    if mean.shape != (2,) or not np.isfinite(mean).all():
        raise ScreeningError("encounter-plane mean must be a finite 2-vector in metres")
    _positive(radius_m, "radius_m")
    eigenvalues, axes = np.linalg.eigh(_covariance(covariance_m2, 2))
    mx, my = axes.T @ mean
    sx, sy = np.sqrt(eigenvalues)
    lo, hi = max(-radius_m, mx - 12 * sx), min(radius_m, mx + 12 * sx)
    if lo >= hi:
        return 0.0
    theta_lo, theta_hi = math.asin(lo / radius_m), math.asin(hi / radius_m)
    midpoint, halfwidth = (theta_hi + theta_lo) / 2, (theta_hi - theta_lo) / 2
    previous = None
    for order in (32, 64, 128, 256, 512):
        nodes, weights = _quadrature(order)
        theta = midpoint + halfwidth * nodes
        x, y = radius_m * np.sin(theta), radius_m * np.cos(theta)
        lower, upper = (-y - my) / (sy * math.sqrt(2)), (y - my) / (sy * math.sqrt(2))
        mass = np.array([
            (math.erfc(a) - math.erfc(b)) / 2 if a >= 0 else
            (math.erfc(-b) - math.erfc(-a)) / 2 if b <= 0 else
            1 - (math.erfc(b) + math.erfc(-a)) / 2
            for a, b in zip(lower, upper)
        ])
        density = np.exp(-0.5 * ((x - mx) / sx) ** 2) / (math.sqrt(2 * math.pi) * sx)
        probability = float(halfwidth * np.dot(weights, density * mass * y))
        if previous is not None and abs(probability - previous) <= 1e-12 + 1e-6 * probability:
            return max(0.0, min(1.0, probability))
        previous = probability
    raise ScreeningError("Pc quadrature did not converge; inspect uncertainty/size inputs")


@dataclass(frozen=True)
class ScreeningIssue:
    norad_id: int | None
    code: str
    message: str


@dataclass(frozen=True)
class Encounter:
    primary: CatalogRecord
    secondary: CatalogRecord
    tca: datetime
    primary_position_km: FloatArray
    primary_velocity_km_s: FloatArray
    secondary_position_km: FloatArray
    secondary_velocity_km_s: FloatArray
    uncertainty: EncounterUncertainty
    covariance: dict[str, float]
    pc: float
    risk: str
    id: str

    def as_conjunction(self) -> dict[str, Any]:
        relative = self.secondary_position_km - self.primary_position_km
        rtn = rtn_basis(self.primary_position_km, self.primary_velocity_km_s) @ relative * 1000
        return {
            "id": self.id, "primary": self.primary.object_ref(), "secondary": self.secondary.object_ref(),
            "tca": _iso(self.tca), "missDistanceM": float(np.linalg.norm(relative) * 1000),
            "rtnM": dict(zip(("r", "t", "n"), map(float, rtn))),
            "relSpeedKms": float(np.linalg.norm(self.secondary_velocity_km_s - self.primary_velocity_km_s)),
            "pc": self.pc, "risk": self.risk,
        }

    def as_detail(self, *, options: Sequence[Mapping[str, Any]] = (), brief: str = "") -> dict[str, Any]:
        # Chart window matches the frontend +/-60 seconds, 81 points. These
        # ranges are propagated independently, not a straight-line fixture.
        seconds = np.linspace(-60.0, 60.0, 81)
        jd, fraction = _dates(self.tca, seconds)
        errors, positions, _ = SatrecArray([self.primary.satellite, self.secondary.satellite]).sgp4(jd, fraction)
        if np.any(errors) or not np.isfinite(positions).all():
            raise ScreeningError("cannot produce rangeSeries: SGP4 failed around TCA")
        ranges = np.linalg.norm(positions[1] - positions[0], axis=1)
        label = "ILLUSTRATIVE uncertainty/size inputs" if self.uncertainty.illustrative else "Supplied uncertainty/size inputs"
        provenance = (f"{label}: {self.uncertainty.source}. Pc assumes independent Gaussian errors at TCA "
                      "and a short rectilinear encounter. Orbital elements alone do not supply covariance or size.")
        return {
            **self.as_conjunction(),
            "rangeSeries": [{"tSec": float(t), "rangeKm": float(r)} for t, r in zip(seconds, ranges)],
            "covariance": dict(self.covariance), "hardBodyRadiusM": float(self.uncertainty.hard_body_radius_m),
            "options": [dict(option) for option in options], "brief": f"{brief.strip()} {provenance}".strip(),
        }


@dataclass(frozen=True)
class ScreeningRun:
    """Internal run container. Only ``conjunctions`` is the list API body.

    Lead must surface ``issues``/``complete`` in logs and an appropriate HTTP
    response/header; silently presenting an incomplete run as safe is invalid.
    ``get_detail`` raises KeyError for an ID absent from this snapshot.
    """

    primary_norad_id: int
    start: datetime
    end: datetime
    encounters: tuple[Encounter, ...]
    issues: tuple[ScreeningIssue, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.issues

    @property
    def conjunctions(self) -> list[dict[str, Any]]:
        return [encounter.as_conjunction() for encounter in self.encounters]

    def get_detail(self, conjunction_id: str, **kwargs: Any) -> dict[str, Any]:
        for encounter in self.encounters:
            if encounter.id == conjunction_id:
                return encounter.as_detail(**kwargs)
        raise KeyError(conjunction_id)


def _encounter(primary: CatalogRecord, secondary: CatalogRecord, at: datetime,
               risk_model: RiskModel, config: ScreeningConfig) -> Encounter:
    pr, pv = state_at(primary, at)
    sr, sv = state_at(secondary, at)
    relative_velocity = sv - pv
    speed = float(np.linalg.norm(relative_velocity))
    if speed < config.minimum_relative_speed_km_s:
        raise ScreeningError("relative speed is too low for short-encounter 2D Pc")
    rb_primary, rb_secondary = rtn_basis(pr, pv), rtn_basis(sr, sv)
    direction = relative_velocity / speed
    # Encounter X is primary radial projected perpendicular to relative
    # velocity; Y completes the plane. angleDeg is measured in this basis,
    # which is not generally the primary's literal R/N plane.
    axis = rb_primary[0] - direction * np.dot(rb_primary[0], direction)
    if np.linalg.norm(axis) < 1e-8:
        axis = rb_primary[1] - direction * np.dot(rb_primary[1], direction)
    axis /= np.linalg.norm(axis)
    plane = np.vstack((axis, np.cross(direction, axis)))
    uncertainty = risk_model(primary.catalog, secondary.catalog, at)
    if not isinstance(uncertainty, EncounterUncertainty):
        raise ScreeningError("risk_model must return EncounterUncertainty at TCA")
    combined = (rb_primary.T @ uncertainty.primary_covariance_rtn_m2 @ rb_primary
                + rb_secondary.T @ uncertainty.secondary_covariance_rtn_m2 @ rb_secondary)
    covariance = plane @ combined @ plane.T
    eigenvalues, axes = np.linalg.eigh(covariance)
    pc = collision_probability(plane @ (sr - pr) * 1000, covariance, uncertainty.hard_body_radius_m)
    risk = "critical" if pc >= config.critical_pc else "high" if pc >= config.high_pc else "watch"
    # Full orbital fields bind IDs to a catalog snapshot, not mutable globals.
    identity = json.dumps([primary.catalog["omm"], secondary.catalog["omm"], _iso(at)],
                          sort_keys=True, separators=(",", ":"))
    identifier = f"{primary.norad_id}-{secondary.norad_id}-{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
    return Encounter(primary, secondary, at, pr, pv, sr, sv, uncertainty,
                     {"sigmaMajorM": float(math.sqrt(eigenvalues[1])),
                      "sigmaMinorM": float(math.sqrt(eigenvalues[0])),
                      "angleDeg": float(math.degrees(math.atan2(axes[1, 1], axes[0, 1])) % 180)},
                     pc, risk, identifier)


def _refine(primary: CatalogRecord, secondary: CatalogRecord, start: datetime,
            lo: float, hi: float, tolerance: float) -> list[float]:
    """Bracket decreasing-to-increasing range roots, then bisect r dot v.

    Eight subdivisions per <=60s candidate interval assume no unresolved
    pair of radial extrema within 7.5s for non-decayed Earth orbits. This is
    a finite-resolution search, not a certified all-encounter guarantee.
    """
    def derivative(seconds: float) -> float:
        at = start + timedelta(seconds=float(seconds))
        pr, pv = state_at(primary, at)
        sr, sv = state_at(secondary, at)
        return float(np.dot(sr - pr, sv - pv))

    times = np.linspace(lo, hi, 9)
    slopes = [derivative(float(t)) for t in times]
    roots: list[float] = []
    for index in range(8):
        if slopes[index] <= 0 <= slopes[index + 1]:
            left, right = float(times[index]), float(times[index + 1])
            # A perfectly flat interval is a persistent approach. Keep one
            # point per interval; slow encounters are flagged by _encounter.
            if slopes[index] == slopes[index + 1] == 0:
                if not roots:
                    roots.append(left)
                continue
            while right - left > tolerance:
                middle = (left + right) / 2
                if derivative(middle) < 0:
                    left = middle
                else:
                    right = middle
            roots.append((left + right) / 2)
    return roots


def screen_catalog(catalog: Sequence[Any], primary_norad_id: int, *, risk_model: RiskModel,
                   start: datetime | str | None = None, days: float = 7,
                   min_pc: float = 1e-6, config: ScreeningConfig | None = None) -> ScreeningRun:
    """Screen one selected object against a cached catalog over 0..7 days.

    Memory is bounded by satellite_batch_size * (time_chunk_intervals+1),
    not catalog size * 7-day ephemerides. All epochs use split Julian dates.
    The swept relative chord plus explicit acceleration padding selects
    candidates between samples; SGP4 r dot v roots refine actual TCAs.

    Closed window: a decreasing range at the end or increasing range at the
    start is reported as a constrained boundary minimum if in the envelope.
    Each distinct pass is retained. Results sort by descending Pc, then TCA.
    Secondary failures are returned as issues, never turned into zero Pc.
    Invalid primary states or duplicate catalog identities fail the whole run.
    """
    config = config or ScreeningConfig()
    primary_norad_id = _catalog_id(primary_norad_id)
    _positive(days, "days", zero=True)
    if days > 7 or not math.isfinite(min_pc) or not 0 <= min_pc <= 1:
        raise ScreeningError("days must be 0..7 and min_pc must be 0..1")
    if not callable(risk_model):
        raise ScreeningError("an explicit risk_model is required")
    begin = datetime.now(UTC) if start is None else _utc(start)
    end = begin + timedelta(days=days)
    issues: dict[tuple[int | None, str], ScreeningIssue] = {}
    records: list[CatalogRecord] = []
    seen: set[int] = set()
    for value in catalog:
        number = None
        try:
            value = _mapping(value)
            number = _catalog_id(value.get("noradId"))
            if number in seen:
                raise ScreeningError(f"duplicate NORAD ID {number}")
            seen.add(number)
            record = record_from_catalog(value)
            age = max(abs((begin - record.epoch).total_seconds()), abs((end - record.epoch).total_seconds()))
            if age > config.max_epoch_age_days * DAY_S:
                raise ScreeningError("element epoch outside configured age limit for requested window")
            records.append(record)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            if number == primary_norad_id or (number is not None and str(exc).startswith("duplicate NORAD")):
                raise ScreeningError(str(exc)) from exc
            issues[number, "invalid_catalog"] = ScreeningIssue(number, "invalid_catalog", str(exc))
    primary = next((record for record in records if record.norad_id == primary_norad_id), None)
    if primary is None:
        raise ScreeningError(f"primary NORAD {primary_norad_id} not found in catalog")
    state_at(primary, begin)
    # Match the mock days=0 behaviour (empty horizon), while validating input.
    if days == 0:
        return ScreeningRun(primary_norad_id, begin, end, (), tuple(issues.values()))
    secondaries = [record for record in records if record is not primary]
    duration = days * DAY_S
    times = np.arange(0.0, duration, config.step_seconds)
    times = np.append(times, duration)
    results: list[Encounter] = []
    last_tca: dict[int, float] = {}
    dedup_seconds = max(4 * config.tca_tolerance_seconds, 0.01)
    envelope_km = config.max_miss_distance_m / 1000
    for offset in range(0, len(times) - 1, config.time_chunk_intervals):
        chunk = times[offset:offset + config.time_chunk_intervals + 1]
        jd, fraction = _dates(begin, chunk)
        primary_errors, primary_positions, primary_velocities = primary.satellite.sgp4_array(jd, fraction)
        if np.any(primary_errors) or not np.isfinite([primary_positions, primary_velocities]).all():
            raise ScreeningError("primary propagation failed inside requested window")
        widths = np.diff(chunk)
        for batch_start in range(0, len(secondaries), config.satellite_batch_size):
            batch = secondaries[batch_start:batch_start + config.satellite_batch_size]
            errors, positions, velocities = SatrecArray([record.satellite for record in batch]).sgp4(jd, fraction)
            valid = (errors == 0) & np.isfinite(positions).all(axis=2) & np.isfinite(velocities).all(axis=2)
            for row in np.flatnonzero(~valid.all(axis=1)):
                record = batch[int(row)]
                codes = sorted(set(map(int, errors[row][errors[row] != 0])))
                message = "; ".join(SGP4_ERRORS.get(code, str(code)) for code in codes) or "nonfinite state"
                issues[record.norad_id, "propagation"] = ScreeningIssue(record.norad_id, "propagation", message)
            relative = positions - primary_positions[None, :, :]
            delta = np.diff(relative, axis=1)
            norm2 = np.einsum("ijk,ijk->ij", delta, delta)
            projection = np.zeros_like(norm2)
            with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
                np.divide(-np.einsum("ijk,ijk->ij", relative[:, :-1], delta), norm2,
                          out=projection, where=norm2 > 0)
                projection = np.clip(projection, 0, 1)
                chord_min = np.linalg.norm(relative[:, :-1] + projection[:, :, None] * delta, axis=2)
            padded = envelope_km + config.max_relative_acceleration_km_s2 * widths**2 / 8
            candidates = (chord_min <= padded[None, :]) & valid[:, :-1] & valid[:, 1:]
            # Sort chronologically within each pair, including across chunks.
            for row, interval in np.argwhere(candidates):
                secondary = batch[int(row)]
                lo, hi = float(chunk[interval]), float(chunk[interval + 1])
                try:
                    roots = _refine(primary, secondary, begin, lo, hi, config.tca_tolerance_seconds)
                    if lo == 0 and np.dot(relative[row, 0], velocities[row, 0] - primary_velocities[0]) >= 0:
                        roots.insert(0, lo)
                    if hi == duration and np.dot(relative[row, -1], velocities[row, -1] - primary_velocities[-1]) <= 0:
                        roots.append(hi)
                    for seconds in roots:
                        if abs(seconds - last_tca.get(secondary.norad_id, -math.inf)) <= dedup_seconds:
                            continue
                        at = begin + timedelta(seconds=seconds)
                        pr, _ = state_at(primary, at)
                        sr, _ = state_at(secondary, at)
                        if np.linalg.norm(sr - pr) > envelope_km:
                            continue
                        last_tca[secondary.norad_id] = seconds
                        encounter = _encounter(primary, secondary, at, risk_model, config)
                        if encounter.pc >= min_pc:
                            results.append(encounter)
                except ScreeningError as exc:
                    issues[secondary.norad_id, "encounter"] = ScreeningIssue(secondary.norad_id, "encounter", str(exc))
    results.sort(key=lambda event: (-event.pc, event.tca, event.secondary.norad_id))
    return ScreeningRun(primary_norad_id, begin, end, tuple(results), tuple(issues.values()))
