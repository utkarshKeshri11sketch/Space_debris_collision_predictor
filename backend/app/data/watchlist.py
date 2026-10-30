"""Screening watch-list: which objects Screening propagates against the full catalog.

Screening every object against every other is too slow for a request, so we screen a short
watch-list: the ISS plus the primaries of the closest *real* conjunctions between two
maneuverable spacecraft of different operators, as published by CelesTrak SOCRATES
(https://celestrak.org/SOCRATES/). SOCRATES only chooses WHAT we screen; every number shown
in the UI is still computed by our own SGP4 screening.

The SOCRATES report is downloaded by the scheduled refresh (at most once per 2 hours), never
on a user request. SCREENING_TARGET_IDS overrides the whole list.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .storage import Settings, atomic_write

LOG = logging.getLogger(__name__)
SOCRATES_URL = "https://celestrak.org/SOCRATES/sort-minRange.csv"
ISS = 25544
MIN_DOWNLOAD_INTERVAL_S = 7200
KEEP_ROWS = 500  # closest payload-payload rows kept from the ~200k-row report


def _path() -> Path:
    return Settings.from_env().cache_path.with_name("socrates_candidates.json")


def _operator(name: str) -> str:
    return name.split("-")[0].split(" ")[0].upper()


def candidates_from_csv(text: str, now: datetime | None = None) -> list[dict]:
    """Future SOCRATES events between two active ([+]) maneuverable payloads of different operators,
    closest first.

    Same-operator pairs (e.g. Starlink x Starlink) are left out: the operator coordinates those
    internally, so there is nothing to negotiate.
    """
    from .catalog import propulsive_fleets  # same maneuverability rule as the catalog
    fleets = propulsive_fleets()
    now = now or datetime.now(timezone.utc)
    rows = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        names = row["OBJECT_NAME_1"], row["OBJECT_NAME_2"]
        if not all("[+]" in name for name in names) or any(t in n for n in names for t in ("DEB", "R/B")):
            continue
        clean = [n.replace("[+]", "").strip().upper() for n in names]
        if _operator(names[0]) == _operator(names[1]) or not all(n.startswith(fleets) for n in clean):
            continue
        tca = datetime.fromisoformat(row["TCA"]).replace(tzinfo=timezone.utc)
        if tca <= now:
            continue
        rows.append({"id1": int(row["NORAD_CAT_ID_1"]), "id2": int(row["NORAD_CAT_ID_2"]),
                     "name1": names[0].replace("[+]", "").strip(), "name2": names[1].replace("[+]", "").strip(),
                     "tca": tca.isoformat(), "rangeKm": float(row["TCA_RANGE"])})
    rows.sort(key=lambda r: r["rangeKm"])
    return rows[:KEEP_ROWS]


def refresh_socrates() -> int:
    """Download SOCRATES (rate-limited) and keep the closest candidate rows. Returns row count."""
    path = _path()
    if path.exists() and time.time() - path.stat().st_mtime < MIN_DOWNLOAD_INTERVAL_S:
        return len(json.loads(path.read_text()).get("rows", []))
    request = Request(SOCRATES_URL, headers={"User-Agent": "OrbitSentinel/1.0 (cached orbit catalog)"})
    with urlopen(request, timeout=60) as response:
        text = response.read().decode("utf-8")
    rows = candidates_from_csv(text)
    atomic_write(path, json.dumps({"downloadedAt": datetime.now(timezone.utc).isoformat(),
                                   "source": SOCRATES_URL, "rows": rows}).encode())
    return len(rows)


def targets(maneuverable_ids: set[int], available_ids: set[int], pairs: int | None = None) -> list[int]:
    """ISS + one primary from each of the `pairs` closest cross-operator maneuverable pairs.

    Each target costs roughly a minute of SGP4 screening on the full catalog, so the default is
    one pair (WATCHLIST_PAIRS).
    """
    override = os.getenv("SCREENING_TARGET_IDS", "").strip()
    if override:
        return [int(part) for part in override.split(",") if part.strip()]
    pairs = int(os.getenv("WATCHLIST_PAIRS", "1")) if pairs is None else pairs
    chosen = [ISS] if ISS in available_ids else []
    try:
        rows = json.loads(_path().read_text()).get("rows", [])
    except (OSError, ValueError) as exc:
        LOG.info("No SOCRATES candidates cached (%s); watch-list is ISS only", exc)
        rows = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if len(chosen) >= 1 + pairs:
            break
        if datetime.fromisoformat(row["tca"]) <= now or _operator(row["name1"]) == _operator(row["name2"]):
            continue
        if row["id1"] in maneuverable_ids and row["id2"] in maneuverable_ids and row["id1"] not in chosen:
            chosen.append(row["id1"])
    return chosen
