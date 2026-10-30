"""Read-only catalog API and native OMM records for the physics agents.

No function in this module downloads CelesTrak data. Refresh explicitly with
app.data.refresh.fetch_catalog(), normally from the EventBridge handler.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sgp4 import omm
from sgp4.api import Satrec

from ..models import CatalogMeta, CatalogObject
from .storage import Settings, Snapshot, read_snapshot

LOG = logging.getLogger(__name__)
OBJECT_TYPES = ("PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN")
TYPE_MAP = {"PAY": "PAYLOAD", "PAYLOAD": "PAYLOAD", "DEB": "DEBRIS",
            "DEBRIS": "DEBRIS", "R/B": "ROCKET_BODY", "ROCKET BODY": "ROCKET_BODY",
            "ROCKET_BODY": "ROCKET_BODY", "UNK": "UNKNOWN", "UNKNOWN": "UNKNOWN"}
ACTIVE_STATUSES = frozenset({"+", "P", "B", "S", "X"})
REQUIRED_NUMBERS = ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
                    "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR",
                    "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")


def utc_datetime(value: str) -> datetime:
    """OMM omits a UTC suffix; explicit offsets are also accepted."""
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def normalize_omm(raw: dict[str, Any]) -> dict[str, str | int | float]:
    """Validate OMM, preserving precision and integer catalog IDs.

    Defaults are only redundant CelesTrak convention fields, not orbital elements.
    Missing dynamics fields invalidate the record rather than inventing an orbit.
    sgp4.omm.initialize requires naive fractional-second UTC text.
    """
    if not isinstance(raw, dict):
        raise ValueError("OMM record must be an object")
    fields = {key: value for key, value in raw.items()
              if isinstance(value, (str, int, float)) and not isinstance(value, bool)}
    identifier = fields.get("NORAD_CAT_ID")
    if isinstance(identifier, float) and not identifier.is_integer():
        raise ValueError("NORAD_CAT_ID must be integral")
    norad_id = int(identifier)
    if not 1 <= norad_id <= 999999999:
        raise ValueError("NORAD_CAT_ID outside the 1-9 digit range")
    fields["NORAD_CAT_ID"] = norad_id
    fields["OBJECT_NAME"] = str(fields.get("OBJECT_NAME") or f"NORAD {norad_id}")
    fields.setdefault("OBJECT_ID", "")
    for key, expected in {"CENTER_NAME": "EARTH", "REF_FRAME": "TEME",
                          "TIME_SYSTEM": "UTC", "MEAN_ELEMENT_THEORY": "SGP4"}.items():
        if str(fields.get(key, expected)).upper() != expected:
            raise ValueError(f"Unsupported OMM {key}")
    fields["EPOCH"] = utc_datetime(str(fields["EPOCH"])).replace(tzinfo=None).isoformat(timespec="microseconds")
    for key in REQUIRED_NUMBERS:
        value = float(fields[key])
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite OMM {key}")
        fields[key] = value
    if not 0 < fields["MEAN_MOTION"]:
        raise ValueError("Invalid mean motion (rev/day)")
    if not 0 <= fields["ECCENTRICITY"] < 1 or not 0 <= fields["INCLINATION"] <= 180:
        raise ValueError("Invalid eccentricity or inclination")
    for key in ("RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"):
        if not 0 <= fields[key] < 360:
            raise ValueError(f"Invalid angle {key}")
    for key, default in (("EPHEMERIS_TYPE", 0), ("ELEMENT_SET_NO", 0), ("REV_AT_EPOCH", 0)):
        value = float(fields.get(key, default))
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError(f"Invalid OMM {key}")
        fields[key] = int(value)
    if fields["EPHEMERIS_TYPE"] != 0:
        raise ValueError("Only SGP4 GP ephemeris type 0 is supported")
    fields.setdefault("CLASSIFICATION_TYPE", "U")
    if any(isinstance(value, float) and not math.isfinite(value) for value in fields.values()):
        raise ValueError("Nonfinite OMM extension value")
    return fields


def object_type(fields: dict, metadata: dict, active: bool) -> str:
    """SATCAT wins. Name inference is a fallback for incomplete metadata."""
    code = str(metadata.get("OBJECT_TYPE") or fields.get("OBJECT_TYPE") or "").upper()
    if code in TYPE_MAP:
        return TYPE_MAP[code]
    name = str(fields["OBJECT_NAME"]).upper()
    if re.search(r"\bDEB\b", name):
        return "DEBRIS"
    if "R/B" in name:
        return "ROCKET_BODY"
    return "PAYLOAD" if active else "UNKNOWN"


@dataclass(frozen=True)
class OrbitRecord:
    """Internal interface: km, UTC element epoch, native TEME SGP4 propagator.

    owner is an upstream SATCAT ownership code, not a verified operator identity.
    country is populated only when upstream explicitly provides COUNTRY.
    altitude_km is mean semimajor-axis altitude, not instantaneous height.
    """
    catalog: CatalogObject
    satrec: Satrec
    owner: str | None
    country: str | None
    altitude_km: float
    epoch: datetime

    @property
    def norad_id(self) -> int:
        return self.catalog.noradId

    @property
    def name(self) -> str:
        return self.catalog.name

    @property
    def type(self) -> str:
        return self.catalog.type

    @property
    def omm(self) -> dict:
        return self.catalog.omm


def parse_record(raw: dict, metadata: dict, active_ids: frozenset[int],
                 maneuverable_ids: frozenset[int]) -> OrbitRecord:
    fields = normalize_omm(raw)
    norad_id = int(fields["NORAD_CAT_ID"])
    status = str(metadata.get("OPS_STATUS_CODE") or "").strip()
    active = status in ACTIVE_STATUSES if status else norad_id in active_ids
    kind = object_type(fields, metadata, active)
    active = active and kind == "PAYLOAD"
    sat = Satrec()
    # OMM initialization uses WGS72, matching the source GP fit. No TLE path.
    omm.initialize(sat, fields)
    error, _, _ = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF)
    if error:
        raise ValueError(f"SGP4 rejected {norad_id} at element epoch (code {error})")
    record = CatalogObject(noradId=norad_id, name=str(fields["OBJECT_NAME"]), type=kind,
                           active=active, maneuverable=active and norad_id in maneuverable_ids,
                           omm=fields)
    # Match the inspector's two-body mean-altitude convention, NOT a propagated
    # WGS84 geodetic altitude. mu in km^3/s^2, equatorial radius in km.
    n = float(fields["MEAN_MOTION"]) * 2 * math.pi / 86400
    altitude = (398600.4418 / n**2)**(1 / 3) - 6378.137
    return OrbitRecord(record, sat, metadata.get("OWNER") or None,
                       metadata.get("COUNTRY") or None, altitude,
                       utc_datetime(str(fields["EPOCH"])))


@lru_cache(maxsize=2)
def _parse_snapshot(snapshot: Snapshot, maneuverable_ids: frozenset[int]) -> dict[int, OrbitRecord]:
    records: dict[int, OrbitRecord] = {}
    for raw in snapshot.records:
        try:
            identifier = int(raw["NORAD_CAT_ID"])
            entry = parse_record(raw, snapshot.satcat.get(str(identifier), {}),
                                 snapshot.active_ids, maneuverable_ids)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            LOG.warning("Skipping invalid cached OMM record: %s", exc)
            continue
        previous = records.get(identifier)
        if previous is None or entry.epoch > previous.epoch:
            records[identifier] = entry
    if not records:
        raise ValueError("Snapshot contains no usable SGP4 records")
    return dict(sorted(records.items()))


def load_catalog() -> list[CatalogObject]:
    """EXACT frontend contract. Satrec/owner/altitude stay out of API JSON."""
    return [entry.catalog for entry in load_orbit_catalog().values()]


def load_orbit_catalog() -> dict[int, OrbitRecord]:
    """NORAD-keyed metadata + Satrec objects for Screening/Physics (cache reads only)."""
    settings = Settings.from_env()
    return dict(_parse_snapshot(read_snapshot(settings), settings.maneuverable_ids))


def catalog_meta() -> CatalogMeta:
    settings = Settings.from_env()
    snapshot = read_snapshot(settings)
    records = _parse_snapshot(snapshot, settings.maneuverable_ids)
    counts = dict.fromkeys(OBJECT_TYPES, 0)
    for record in records.values():
        counts[record.type] += 1
    return CatalogMeta(objectCount=len(records), byType=counts,
                       syncedAt=snapshot.synced_at, source=snapshot.source)
