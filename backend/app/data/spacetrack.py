"""Space-Track.org GP catalog: the refresh source that does not touch CelesTrak.

Space-Track (USSPACECOM) publishes the public GP catalog that CelesTrak mirrors, in the same OMM
fields as our bundled archive. It needs a free account: SPACETRACK_USERNAME / SPACETRACK_PASSWORD
come from the environment (backend/.env), never from code.

Usage policy (https://www.space-track.org/documentation): under 30 requests/minute and 300/hour,
GP at most once per hour. One refresh is login + one GP query + logout, behind refresh.py's
two-hour floor. GP is basic SSA data, approved for redistribution with citation, so the snapshot
source names Space-Track.

ASSUMPTION (Lead): Space-Track has no operational-status field (CelesTrak's SATCAT OPS_STATUS_CODE
is not available here). Payloads of the propulsive fleets are taken as active, as the catalog's
maneuverability rule already does; every other payload's status is unknown and is NOT marked active.
The source text says so, and the frontend then shows active-satellite counts as unknown.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .catalog import normalize_omm, parse_record, propulsive_fleets, utc_datetime
from .storage import MAX_SNAPSHOT_BYTES, Snapshot

BASE = "https://www.space-track.org"
LOGIN_URL = BASE + "/ajaxauth/login"
LOGOUT_URL = BASE + "/ajaxauth/logout"
# On-orbit objects with propagable elements: Space-Track's documented decay_date/epoch filter.
GP_URL = (BASE + "/basicspacedata/query/class/gp/decay_date/null-val/epoch/%3Enow-10"
          "/orderby/norad_cat_id/format/json")
SOURCE = ("Space-Track.org GP OMM JSON (USSPACECOM), on-orbit objects; "
          "operational status unknown outside propulsive fleets")
# Same OMM fields the bundled archive keeps; TLE lines and Space-Track bookkeeping are dropped.
OMM_FIELDS = ("OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
              "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE",
              "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO", "REV_AT_EPOCH", "BSTAR",
              "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")


class SpaceTrackLoginError(ValueError):
    """Missing or rejected credentials: an operator must fix .env, retrying will not help."""


def credentials() -> tuple[str, str] | None:
    user = os.environ.get("SPACETRACK_USERNAME", "").strip()
    password = os.environ.get("SPACETRACK_PASSWORD", "")
    return (user, password) if user and password else None


def _fetch(opener, url: str, data: bytes | None = None, timeout: float = 45) -> bytes:
    """One bounded request through the logged-in session."""
    request = Request(url, data=data, headers={"User-Agent": "OrbitSentinel/1.0 (cached orbit catalog)"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"Unexpected Space-Track HTTP {response.status}")
        payload = response.read(MAX_SNAPSHOT_BYTES + 1)
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Space-Track response too large")
    return payload


def download_gp() -> list[dict]:
    creds = credentials()
    if creds is None:
        raise SpaceTrackLoginError("Set SPACETRACK_USERNAME and SPACETRACK_PASSWORD in backend/.env")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    body = _fetch(opener, LOGIN_URL, urlencode({"identity": creds[0], "password": creds[1]}).encode())
    # Success returns an empty JSON string; a rejected login returns {"Login": "Failed"}.
    if b"Failed" in body:
        raise SpaceTrackLoginError("Space-Track rejected the login; check SPACETRACK_USERNAME/PASSWORD")
    try:
        rows = json.loads(_fetch(opener, GP_URL, timeout=180))
    finally:
        try:
            _fetch(opener, LOGOUT_URL)
        except Exception:  # noqa: BLE001 - the session expires on its own
            pass
    if not isinstance(rows, list) or not rows:
        raise ValueError("Space-Track GP response is not a nonempty OMM array")
    return rows


def snapshot_from_gp(rows: list[dict], now: float) -> Snapshot:
    fleets = propulsive_fleets()
    records: dict[int, dict] = {}
    satcat: dict[str, dict] = {}
    for raw in rows:
        try:
            fields = normalize_omm({key: raw[key] for key in OMM_FIELDS if key in raw})
            parse_record(fields, {}, frozenset(), frozenset())  # SGP4 must accept it at epoch
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
        identifier = int(fields["NORAD_CAT_ID"])
        previous = records.get(identifier)
        if previous is None or utc_datetime(str(fields["EPOCH"])) > utc_datetime(str(previous["EPOCH"])):
            records[identifier] = fields
            satcat[str(identifier)] = {key: value for key, value in (
                ("OBJECT_TYPE", raw.get("OBJECT_TYPE")), ("COUNTRY", raw.get("COUNTRY_CODE"))) if value}
    if not records:
        raise ValueError("Space-Track GP feed contained no usable records")
    active = frozenset(identifier for identifier, fields in records.items()
                       if satcat[str(identifier)].get("OBJECT_TYPE") == "PAYLOAD"
                       and str(fields["OBJECT_NAME"]).upper().startswith(fleets))
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    return Snapshot(stamp, SOURCE, tuple(records[key] for key in sorted(records)), active, satcat, stamp)


def download_snapshot(now: float) -> Snapshot:
    return snapshot_from_gp(download_gp(), now)
