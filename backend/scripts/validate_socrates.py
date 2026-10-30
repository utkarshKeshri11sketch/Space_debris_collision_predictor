"""Compare computed geometry with CelesTrak SOCRATES for the same target.

From backend/: python scripts/validate_socrates.py --download --catalog snapshot.json --norad-id 25544
Offline: add --catalog snapshot.json --socrates report.csv (no network).
Downloads are explicit, cached at least two hours, and never retried within
that period even after failure. GP is native OMM JSON, never TLE. No AWS calls.
SOCRATES MAX_PROB optimizes covariance; it is NOT our assumed-covariance Pc.
Source: https://celestrak.org/SOCRATES/socrates-format.php
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
from time import time
from typing import Any
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.physics.screening import (  # noqa: E402
    ScreeningRun, catalog_objects_from_omm, screen_catalog,
)

UTC = timezone.utc
SOCRATES_URL = "https://celestrak.org/SOCRATES/sort-minRange.csv"
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "tests" / "screening" / ".cache"
LOG = logging.getLogger("validate_socrates")


def cached_download(url: str, cache_dir: Path) -> Path:
    """One attempt per URL per two hours, cross-process lock, atomic output."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    suffix = ".json" if "format=json" in url.lower() or url.lower().split("?", 1)[0].endswith(".json") else ".csv"
    path = cache_dir / (key + suffix)
    attempted = cache_dir / (key + ".attempt.json")
    lock = cache_dir / (key + ".lock")
    if path.exists() and time() - path.stat().st_mtime < 7200:
        return path
    # An existing lock is not deleted automatically: simultaneous devices
    # must not bypass the provider's refresh policy after a slow request.
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        if path.exists() and time() - path.stat().st_mtime < 7200:
            return path
        if attempted.exists() and time() - attempted.stat().st_mtime < 7200:
            raise RuntimeError(f"Fetch already attempted within two hours: {url}; reuse a supplied snapshot")
        attempted.write_text(json.dumps({"url": url, "attemptedAt": datetime.now(UTC).isoformat()}), encoding="utf-8")
        request = Request(url, headers={"User-Agent": "OrbitSentinel/0.1 (cached hackathon validation)"})
        with urlopen(request, timeout=45) as response:
            content = response.read(128 * 1024 * 1024 + 1)
        if len(content) > 128 * 1024 * 1024:
            raise ValueError("response exceeded 128 MiB")
        text = content.decode("utf-8-sig")
        if suffix == ".json":
            try:
                payload = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"GP response was not JSON: {text[:160]!r}") from exc
            if not isinstance(payload, list) or not payload or "NORAD_CAT_ID" not in payload[0]:
                raise ValueError("GP response was not a nonempty OMM array")
        elif not {"NORAD_CAT_ID_1", "NORAD_CAT_ID_2", "TCA", "TCA_RANGE"}.issubset(
            csv.DictReader(io.StringIO(text)).fieldnames or []
        ):
            raise ValueError("SOCRATES response did not contain the documented CSV header")
        temporary.write_bytes(content)
        temporary.replace(path)
        return path
    finally:
        if temporary.exists():
            temporary.unlink()
        lock.unlink()


@dataclass(frozen=True)
class SocratesEvent:
    primary_id: int
    secondary_id: int
    tca: datetime
    miss_m: float
    relative_speed_km_s: float
    primary_epoch: datetime | None
    secondary_epoch: datetime | None


def parse_socrates(text: str, target_id: int) -> list[SocratesEvent]:
    """RFC4180 CSV; either catalog column may contain the selected object."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    required = {"NORAD_CAT_ID_1", "NORAD_CAT_ID_2", "TCA", "TCA_RANGE", "TCA_RELATIVE_SPEED"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Not a SOCRATES CSV: required columns missing")
    result = []
    for row in reader:
        first, second = int(row["NORAD_CAT_ID_1"]), int(row["NORAD_CAT_ID_2"])
        if target_id not in (first, second):
            continue
        tca = datetime.fromisoformat(row["TCA"].strip().replace("Z", "+00:00"))
        tca = tca.replace(tzinfo=UTC) if tca.tzinfo is None else tca.astimezone(UTC)
        epochs = [tca - timedelta(days=float(row[f"DSE_{i}"])) if row.get(f"DSE_{i}") else None for i in (1, 2)]
        if first != target_id:
            first, second = second, first
            epochs.reverse()
        result.append(SocratesEvent(first, second, tca, float(row["TCA_RANGE"]) * 1000,
                                    float(row["TCA_RELATIVE_SPEED"]), epochs[0], epochs[1]))
    return result


def compare(run: ScreeningRun, references: Sequence[SocratesEvent], *,
            catalog_ids: set[int] | None = None,
            time_tolerance_s: float = 2, range_tolerance_m: float = 100,
            speed_tolerance_km_s: float = 0.01) -> dict[str, Any]:
    """One-to-one nearest-TCA matches with explicit element-epoch checks.

    DSE values are rounded to 0.001 day (~86 s); allow 120 s when checking
    that both inputs use the same elements. This checks epoch compatibility,
    not a guarantee that every other element is identical.
    """
    used: set[str] = set()
    rows = []
    slow_ids = {issue.norad_id for issue in run.issues if issue.code == "slow_encounter"}
    references = [ref for ref in references if ref.primary_id == run.primary_norad_id
                  and run.start <= ref.tca <= run.end]
    for reference in references:
        if catalog_ids is not None and reference.secondary_id not in catalog_ids:
            rows.append({"secondaryId": reference.secondary_id, "tca": reference.tca.isoformat(),
                         "status": "OUTSIDE_CATALOG"})
            continue
        if reference.secondary_id in slow_ids and reference.relative_speed_km_s < 0.01:
            rows.append({"secondaryId": reference.secondary_id, "tca": reference.tca.isoformat(),
                         "status": "UNSUPPORTED_SLOW_ENCOUNTER"})
            continue
        candidates = [event for event in run.encounters if event.secondary_norad_id == reference.secondary_id
                      and event.id not in used]
        candidate = min(candidates, key=lambda event: abs((event.tca - reference.tca).total_seconds())) if candidates else None
        if candidate is None or abs((candidate.tca - reference.tca).total_seconds()) > 120:
            rows.append({"secondaryId": reference.secondary_id, "tca": reference.tca.isoformat(), "status": "UNMATCHED_REFERENCE"})
            LOG.warning("UNMATCHED reference target=%s secondary=%s TCA=%s", run.primary_norad_id, reference.secondary_id, reference.tca)
            continue
        used.add(candidate.id)
        data = candidate.as_conjunction()
        dt = abs((candidate.tca - reference.tca).total_seconds())
        dr = abs(data["missDistanceM"] - reference.miss_m)
        dv = abs(data["relSpeedKms"] - reference.relative_speed_km_s)
        epoch_match = (None if reference.primary_epoch is None or reference.secondary_epoch is None else
                       abs((candidate.primary.epoch - reference.primary_epoch).total_seconds()) <= 120 and
                       abs((candidate.secondary.epoch - reference.secondary_epoch).total_seconds()) <= 120)
        geometry_match = dt <= time_tolerance_s and dr <= range_tolerance_m and dv <= speed_tolerance_km_s
        status = "MATCH" if geometry_match and epoch_match else "DIFFERENT_ELEMENTS" if epoch_match is False else "GEOMETRY_MISMATCH" if not geometry_match else "EPOCH_UNVERIFIED"
        rows.append({"secondaryId": reference.secondary_id, "eventId": candidate.id,
                     "status": status, "timeErrorS": dt, "rangeErrorM": dr, "speedErrorKms": dv,
                     "geometryMatch": geometry_match, "epochCompatible": epoch_match,
                     "computedMissM": data["missDistanceM"], "referenceMissM": reference.miss_m,
                     "computedPcAssumed": candidate.pc})
        LOG.info("%s target=%s secondary=%s dt=%.3fs dr=%.2fm dv=%.5fkm/s", status,
                 run.primary_norad_id, reference.secondary_id, dt, dr, dv)
    matched = sum(row["status"] == "MATCH" for row in rows)
    eligible = sum(row["status"] not in {"OUTSIDE_CATALOG", "UNSUPPORTED_SLOW_ENCOUNTER"} for row in rows)
    status_counts = {status: sum(row["status"] == status for row in rows)
                     for status in sorted({row["status"] for row in rows})}
    return {"targetId": run.primary_norad_id, "start": run.start.isoformat(), "end": run.end.isoformat(),
            "statistics": run.statistics, "referenceEvents": len(references), "computedEvents": len(run.encounters),
            "matched": matched, "eligibleReferenceEvents": eligible, "statusCounts": status_counts,
            "validationPassed": bool(eligible) and matched == eligible and run.complete,
            "rows": rows, "unmatchedComputedIds": [event.id for event in run.encounters if event.id not in used],
            "complete": run.complete, "issues": [issue.__dict__ for issue in run.issues],
            "pcNote": "Assumed per-type covariance Pc; SOCRATES MAX_PROB is a different metric and is not compared."}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--norad-id", type=int, default=25544)
    parser.add_argument("--catalog", type=Path, help="Native OMM JSON or CatalogObject snapshot")
    parser.add_argument("--socrates", type=Path, help="Existing SOCRATES CSV; no download")
    parser.add_argument("--download", action="store_true", help="Fetch missing inputs at most once per 2 hours")
    parser.add_argument("--gp-url", help="Explicit OMM JSON URL if not using Data's cached catalog; no implicit partial catalog")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--start", help="UTC screening start; default current time")
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Nonzero exit unless all reference events match with compatible epochs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    output = args.output or args.cache_dir / f"validation-{args.norad_id}.json"
    try:
        catalog_path, reference_path = args.catalog, args.socrates
        if args.download:
            reference_path = reference_path or cached_download(SOCRATES_URL, args.cache_dir)
            if catalog_path is None and args.gp_url:
                catalog_path = cached_download(args.gp_url, args.cache_dir)
        if reference_path is None:
            parser.error("supply --socrates report.csv or --download")
        if catalog_path is not None:
            payload = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
            entries = payload.get("catalog", payload.get("objects")) if isinstance(payload, Mapping) else payload
            catalog = catalog_objects_from_omm(entries)
        else:
            from app.data.catalog import load_catalog, catalog_meta
            if "synthetic" in catalog_meta().source.lower():
                raise ValueError("Data still serves a synthetic catalog; supply a real --catalog snapshot")
            catalog = load_catalog()
        references = parse_socrates(reference_path.read_text(encoding="utf-8-sig"), args.norad_id)
        run = screen_catalog(catalog, args.norad_id, start=args.start, days=args.days, min_pc=0)
        result = compare(run, references, catalog_ids={entry["noradId"] for entry in catalog})
        result["catalogPath"] = str(catalog_path) if catalog_path else "Data.load_catalog"
        result["referencePath"] = str(reference_path)
        result["under10Seconds"] = float(run.statistics.get("elapsedSeconds", float("inf"))) < 10
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        LOG.info("Result matched=%d/%d computed=%d bandCandidates=%s runtime=%.3fs report=%s",
                 result["matched"], result["referenceEvents"], result["computedEvents"],
                 run.statistics.get("bandCandidates"), run.statistics.get("elapsedSeconds", 0), output)
        return 1 if args.strict and not result["validationPassed"] else 0
    except (OSError, ValueError, RuntimeError) as exc:
        LOG.error("Validation unavailable: %s", exc)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"validationPassed": False, "error": str(exc),
                                      "checkedAt": datetime.now(UTC).isoformat()}), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
