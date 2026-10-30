"""Versioned, atomic snapshots and optional S3 cache; never an upstream fetch."""
from __future__ import annotations

import json
import gzip
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)
BUNDLED_SNAPSHOT = Path(__file__).parent / "snapshots" / "catalog.json.gz"
MAX_SNAPSHOT_BYTES = 96 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    cache_path: Path
    bucket: str = ""
    key: str = "orbitsentinel/catalog.json"
    min_refresh_seconds: int = 7200
    maneuverable_ids: frozenset[int] = frozenset()

    @classmethod
    def from_env(cls) -> Settings:
        # Lambda's deployment package is read-only: runtime writes belong in /tmp.
        default = Path(tempfile.gettempdir()) / "orbitsentinel" / "catalog.json"
        return cls(Path(os.environ.get("CATALOG_CACHE_PATH", str(default))),
                   os.environ.get("S3_BUCKET", ""),
                   os.environ.get("CATALOG_S3_KEY", "orbitsentinel/catalog.json"),
                   max(7200, int(os.environ.get("CATALOG_MIN_REFRESH_SECONDS", "7200"))),
                   frozenset(int(value.strip()) for value in
                             os.environ.get("CATALOG_MANEUVERABLE_IDS", "").split(",") if value.strip()))

    @property
    def state_path(self) -> Path:
        return self.cache_path.with_suffix(self.cache_path.suffix + ".refresh.json")

    @property
    def lock_path(self) -> Path:
        return self.cache_path.with_suffix(self.cache_path.suffix + ".lock")


@dataclass(eq=False, frozen=True)
class Snapshot:
    """Identity-hashable envelope; contents are private to the data module."""
    synced_at: str
    source: str
    records: tuple[dict[str, Any], ...]
    active_ids: frozenset[int] = frozenset()
    satcat: dict[str, dict] = field(default_factory=dict)
    satcat_synced_at: str | None = None

    def to_bytes(self) -> bytes:
        return json.dumps({"schemaVersion": 1, "syncedAt": self.synced_at,
                           "source": self.source, "records": self.records,
                           "activeIds": sorted(self.active_ids), "satcat": self.satcat,
                           "satcatSyncedAt": self.satcat_synced_at},
                          separators=(",", ":"), allow_nan=False).encode("utf-8")


def parse_snapshot(payload: bytes) -> Snapshot:
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds configured size bound")
    data = json.loads(payload)
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("Unsupported catalog snapshot format")
    stamp = datetime.fromisoformat(data["syncedAt"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or not isinstance(data.get("source"), str):
        raise ValueError("Snapshot requires UTC sync provenance")
    records = data["records"]
    if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
        raise ValueError("Snapshot records must be a nonempty OMM array")
    from .catalog import parse_record  # Delayed import avoids the module cycle.
    satcat = data.get("satcat", {})
    if not isinstance(satcat, dict) or not all(isinstance(v, dict) for v in satcat.values()):
        raise ValueError("Invalid SATCAT metadata mapping")
    active_ids = frozenset(int(value) for value in data.get("activeIds", []))
    valid = []
    for raw in records:
        try:
            identifier = int(raw["NORAD_CAT_ID"])
            parse_record(raw, satcat.get(str(identifier), {}), active_ids, frozenset())
            valid.append(raw)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            LOG.warning("Invalid snapshot row discarded: %s", exc)
    if not valid:
        raise ValueError("Snapshot has no usable orbital records")
    satcat_stamp = data.get("satcatSyncedAt")
    if satcat_stamp is not None:
        parsed = datetime.fromisoformat(satcat_stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("SATCAT timestamp must include a timezone")
    return Snapshot(stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    data["source"], tuple(valid), active_ids, satcat, satcat_stamp)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def s3_client():
    # Lazy: local/offline usage never resolves AWS credentials or imports boto3.
    import boto3
    from botocore.config import Config
    return boto3.client("s3", config=Config(connect_timeout=5, read_timeout=10,
                                          retries={"max_attempts": 1}))


@lru_cache(maxsize=4)
def _local_snapshot(path: Path, modified: int, size: int) -> Snapshot:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        return parse_snapshot(stream.read(MAX_SNAPSHOT_BYTES + 1))


_remote_cache: dict[tuple[str, str], tuple[float, Snapshot | None]] = {}
_remote_lock = threading.Lock()


def read_snapshot(settings: Settings) -> Snapshot:
    """Newest valid local/S3/bundled snapshot. S3 GET: at most once/5min/process.

    No CelesTrak access or disk writes happen on a user request. When S3 is
    unavailable, keep the last valid remote value and fall back to disk/bundle.
    """
    candidates = []
    for path in (settings.cache_path, BUNDLED_SNAPSHOT):
        try:
            stat = path.stat()
            if stat.st_size > MAX_SNAPSHOT_BYTES:
                raise ValueError("Oversized local snapshot")
            candidates.append(_local_snapshot(path, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError) as exc:
            LOG.warning("Cannot read catalog cache %s: %s", path, exc)
    if settings.bucket:
        key = (settings.bucket, settings.key)
        with _remote_lock:
            now = time.monotonic()
            checked, remote = _remote_cache.get(key, (float("-inf"), None))
            if now - checked >= 300:
                try:
                    response = s3_client().get_object(Bucket=settings.bucket, Key=settings.key)
                    body = response["Body"]
                    try:
                        remote = parse_snapshot(body.read(MAX_SNAPSHOT_BYTES + 1))
                    finally:
                        body.close()
                except Exception as exc:
                    LOG.warning("S3 catalog unavailable; keeping cached data: %s", exc)
                _remote_cache[key] = (now, remote)
            if remote is not None:
                candidates.append(remote)
    if not candidates:
        raise RuntimeError("No usable catalog snapshot; run the scheduled refresh first")
    return max(candidates, key=lambda snapshot:
               datetime.fromisoformat(snapshot.synced_at.replace("Z", "+00:00")).timestamp())
