"""Explicit CelesTrak refresh and EventBridge Lambda entry point.

Never imported or called by the catalog router. An attempt (including failure)
consumes the two-hour window. A conditional S3 lease coordinates cold starts.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import storage
from .catalog import normalize_omm, parse_record, utc_datetime
from .storage import MAX_SNAPSHOT_BYTES, Settings, Snapshot, atomic_write, parse_snapshot, read_snapshot

LOG = logging.getLogger(__name__)
BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"
DEFAULT_URLS = (BASE_URL + "?GROUP=active&FORMAT=JSON",
                BASE_URL + "?NAME=DEB&FORMAT=JSON",
                BASE_URL + "?NAME=R%2FB&FORMAT=JSON")
SATCAT_URL = "https://celestrak.org/pub/satcat.csv"


@dataclass(frozen=True)
class RefreshResult:
    status: str
    object_count: int = 0
    synced_at: str | None = None
    message: str = ""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # CelesTrak explicitly treats redirects as an incorrect query to fix.
        return None


def _download(url: str) -> bytes:
    """One bounded request, no retries or redirected requests."""
    request = Request(url, headers={"User-Agent": "OrbitSentinel/1.0 (cached orbit catalog)",
                                    "Accept": "application/json,text/csv"})
    with build_opener(NoRedirect()).open(request, timeout=45) as response:
        if response.status != 200:
            raise ValueError(f"Unexpected CelesTrak HTTP {response.status}")
        payload = response.read(MAX_SNAPSHOT_BYTES + 1)
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("CelesTrak response too large")
    return payload


def _urls() -> tuple[str, ...]:
    override = os.environ.get("CELESTRAK_URL", "").strip()
    # The Lead's original env example selects only active. Keep that selection
    # AND add the two debris/body queries; never silently serve active-only data.
    urls = (override, *DEFAULT_URLS[1:]) if override else DEFAULT_URLS
    for url in urls:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.scheme != "https" or parsed.hostname != "celestrak.org":
            raise ValueError("CELESTRAK_URL must use https://celestrak.org")
        if query.get("FORMAT", [""])[0].upper() != "JSON":
            raise ValueError("CELESTRAK_URL must request OMM FORMAT=JSON")
    return tuple(dict.fromkeys(urls))


def _download_catalog(now: float, cached: Snapshot | None = None) -> Snapshot:
    rows: dict[int, dict] = {}
    active_ids: set[int] = set()
    for url in _urls():
        incoming = json.loads(_download(url))
        if not isinstance(incoming, list) or not incoming:
            raise ValueError("CelesTrak GP response is not a nonempty OMM array")
        is_active_feed = parse_qs(urlparse(url).query).get("GROUP", [""])[0].lower() == "active"
        valid_count = 0
        for raw in incoming:
            try:
                fields = normalize_omm(raw)
                # Validate native SGP4 initialization before publishing anything.
                parse_record(fields, {}, frozenset(), frozenset())
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                LOG.warning("Invalid upstream OMM row skipped: %s", exc)
                continue
            valid_count += 1
            identifier = int(fields["NORAD_CAT_ID"])
            if is_active_feed:
                active_ids.add(identifier)
            previous = rows.get(identifier)
            if previous is None or utc_datetime(str(fields["EPOCH"])) > utc_datetime(str(previous["EPOCH"])):
                rows[identifier] = fields
        if not valid_count:
            raise ValueError("CelesTrak GP feed contained no usable records")
    # GP has no owner, object type or operational status. Join the authoritative
    # SATCAT rather than assuming every payload has propulsion or is operational.
    timestamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    # SATCAT updates only once/twice daily; retain it for 24h across refreshes.
    if (cached is not None and cached.satcat and cached.satcat_synced_at is not None
            and now - utc_datetime(cached.satcat_synced_at).timestamp() < 86400):
        metadata, metadata_stamp = cached.satcat, cached.satcat_synced_at
    else:
        metadata = {}
        text = _download(SATCAT_URL).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        required = {"NORAD_CAT_ID", "OBJECT_TYPE", "OPS_STATUS_CODE", "OWNER"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Unexpected SATCAT CSV header")
        for item in reader:
            if str(item.get("NORAD_CAT_ID", "")).isdigit() and int(item["NORAD_CAT_ID"]) in rows:
                metadata[item["NORAD_CAT_ID"]] = {key: item[key] for key in
                    ("OBJECT_TYPE", "OPS_STATUS_CODE", "OWNER", "COUNTRY") if item.get(key)}
        if not metadata:
            raise ValueError("SATCAT response did not match any GP objects")
        metadata_stamp = timestamp
    return Snapshot(timestamp, "CelesTrak GP OMM JSON: active + named debris/rocket bodies; SATCAT metadata",
                    tuple(rows[key] for key in sorted(rows)), frozenset(active_ids), metadata, metadata_stamp)


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    state = json.loads(path.read_bytes())
    if (not isinstance(state, dict) or isinstance(state.get("nextAllowedAt"), bool)
            or not isinstance(state.get("nextAllowedAt"), (int, float))
            or not math.isfinite(state["nextAllowedAt"])):
        raise ValueError("Invalid refresh state; repair it before retrying upstream")
    return state


def _save_state(path: Path, state: dict) -> None:
    atomic_write(path, json.dumps(state, allow_nan=False).encode("utf-8"))


def _s3_state(client, settings: Settings) -> tuple[dict, str | None]:
    try:
        response = client.get_object(Bucket=settings.bucket, Key=settings.key + ".refresh.json")
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        # AccessDenied/credential/network errors MUST NOT be treated as no lease.
        if code == "NoSuchKey":
            return {}, None
        raise
    body = response["Body"]
    try:
        state = json.loads(body.read(16385))
    finally:
        body.close()
    if (not isinstance(state, dict) or isinstance(state.get("nextAllowedAt"), bool)
            or not isinstance(state.get("nextAllowedAt"), (int, float))
            or not math.isfinite(state["nextAllowedAt"])):
        raise ValueError("Invalid S3 refresh state")
    return state, response["ETag"]


def _put_s3_state(client, settings: Settings, state: dict, etag: str | None):
    condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    return client.put_object(Bucket=settings.bucket, Key=settings.key + ".refresh.json",
                             Body=json.dumps(state).encode(), ContentType="application/json", **condition)


def _retry_after(error: HTTPError, now: float) -> float:
    header = error.headers.get("Retry-After", "") if error.headers else ""
    try:
        return now + max(0, int(header))
    except ValueError:
        try:
            return parsedate_to_datetime(header).timestamp()
        except (ValueError, TypeError, OverflowError):
            return now


def fetch_catalog() -> RefreshResult:
    """Refresh once, or return cached status without violating the two-hour floor.

    No force switch exists. With S3 configured, losing the distributed lease or
    access to S3 prevents all upstream calls. HTTP 403/404 blocks future attempts
    until an operator fixes the query and clears the refresh state in both stores.
    """
    settings = Settings.from_env()
    now = time.time()
    settings.lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(settings.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # A crashed process may leave a lock. No real attempt can still be alive
        # after the two-hour window (each request has a 45-second timeout).
        try:
            if now - settings.lock_path.stat().st_mtime >= max(7200, settings.min_refresh_seconds):
                settings.lock_path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass  # The other process finished between open() and stat().
        return RefreshResult("skipped", message="Another refresh holds the local lock; retry on next schedule")
    os.close(descriptor)
    client = None
    remote_etag = None
    state = {}
    attempted = False
    try:
        state = _read_state(settings.state_path)
        if state.get("blocked") or now < state.get("nextAllowedAt", 0):
            return RefreshResult("skipped", message="Refresh cooldown or upstream block is active")
        # A restored snapshot also guards against an absent/deleted state file.
        try:
            cached = read_snapshot(settings)
        except RuntimeError:
            cached = None  # Explicit refresh can bootstrap/repair an empty cache.
        if cached is not None and now < utc_datetime(cached.synced_at).timestamp() + max(7200, settings.min_refresh_seconds):
            return RefreshResult("skipped", len(cached.records), cached.synced_at, "Snapshot is under two hours old")
        if settings.bucket:
            client = storage.s3_client()
            remote, remote_etag = _s3_state(client, settings)
            if remote.get("blocked") or now < remote.get("nextAllowedAt", 0):
                _save_state(settings.state_path, remote)
                return RefreshResult("skipped", message="Shared S3 cooldown or upstream block is active")
        state = {"attemptedAt": now, "nextAllowedAt": now + max(7200, settings.min_refresh_seconds)}
        # Save locally before the conditional claim. Competing writers that lose
        # the S3 condition do not fall back to an uncoordinated HTTP request.
        _save_state(settings.state_path, state)
        if client is not None:
            response = _put_s3_state(client, settings, state, remote_etag)
            remote_etag = response["ETag"]
        attempted = True
        snapshot = _download_catalog(now, cached)
        payload = snapshot.to_bytes()
        # Validate the serialized artifact too, before replacing either cache.
        parse_snapshot(payload)
        atomic_write(settings.cache_path, payload)
        if client is not None:
            client.put_object(Bucket=settings.bucket, Key=settings.key, Body=payload,
                              ContentType="application/json")
            with storage._remote_lock:
                storage._remote_cache[(settings.bucket, settings.key)] = (time.monotonic(), snapshot)
        return RefreshResult("updated", len(snapshot.records), snapshot.synced_at)
    except Exception as exc:
        if isinstance(exc, HTTPError):
            state["nextAllowedAt"] = max(state.get("nextAllowedAt", now + 7200), _retry_after(exc, now))
            state["blocked"] = exc.code in (301, 302, 307, 308, 403, 404)
        if attempted:
            state["lastError"] = type(exc).__name__
            try:
                _save_state(settings.state_path, state)
                if client is not None:
                    _put_s3_state(client, settings, state, remote_etag)
            except Exception:
                LOG.exception("Cannot persist refresh failure; original cooldown lease remains")
        LOG.warning("Catalog refresh failed; last good caches retained: %s", exc)
        return RefreshResult("error", message=f"Catalog refresh failed: {type(exc).__name__}; consult logs")
    finally:
        settings.lock_path.unlink(missing_ok=True)


def refresh_handler(event, context) -> dict:
    """AWS handler app.data.refresh.refresh_handler, EventBridge rate(6 hours)."""
    result = fetch_catalog()
    LOG.info("Catalog refresh: %s", asdict(result))
    _refresh_watchlist()
    return asdict(result)


def _refresh_watchlist() -> None:
    """SOCRATES candidates for the screening watch-list; failure keeps the previous list."""
    from .watchlist import refresh_socrates
    try:
        LOG.info("SOCRATES watch-list candidates: %s", refresh_socrates())
    except Exception as exc:  # noqa: BLE001 - a stale watch-list must not fail the catalog refresh
        LOG.warning("SOCRATES refresh failed; keeping previous watch-list: %s", exc)


if __name__ == "__main__":
    result = fetch_catalog()
    _refresh_watchlist()
    print(json.dumps(asdict(result)))
    raise SystemExit(1 if result.status == "error" else 0)
