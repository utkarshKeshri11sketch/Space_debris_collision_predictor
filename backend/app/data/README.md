# OrbitSentinel data pipeline

`catalog.load_catalog()` and `catalog.catalog_meta()` preserve the existing router
signatures and the exact frontend JSON. Neither fetches CelesTrak. A local file is
loaded first; the newest valid bundled, local or S3 snapshot is selected. S3 is
checked at most every five minutes in each warm API process. On errors the last
valid remote/local/bundled data remains available. `syncedAt` is stored provenance,
never the time of an API request.

## Physics interface

```python
from app.data.catalog import load_orbit_catalog

objects = load_orbit_catalog()  # dict[int, OrbitRecord], keyed by full NORAD ID
iss = objects[25544]
satrec = iss.satrec            # sgp4.api.Satrec, initialized from OMM, WGS72
error, position_km, velocity_kms = satrec.sgp4(julian_day, fractional_day)
# Native coordinates are TEME, not ECEF or latitude/longitude.
```

`OrbitRecord` also provides `catalog` (the Pydantic API record), `norad_id`, `name`,
`type`, `omm`, `epoch` (aware UTC datetime), `owner`, `country`, and `altitude_km`.
The altitude uses the inspector's mean semimajor-axis convention: mean motion in
rev/day, mu=398600.4418 km^3/s^2, radius=6378.137 km. It is not instantaneous
geodetic altitude. Treat returned propagators/API records as read-only.

All required dynamics must be present and finite. Epochs with `Z`, no timezone,
or an explicit offset are normalized to UTC for `sgp4.omm.initialize`. No TLE
parsing, synthetic orbit generation, or rewriting epochs to today takes place.
Malformed records are logged/skipped. The shipped archive includes real six-digit
IDs. Native propagation is checked at the actual element epoch, not today's date.

## Refresh and deployment

Source: with `SPACETRACK_USERNAME` and `SPACETRACK_PASSWORD` set (backend/.env or the
environment) the refresh uses Space-Track.org and never contacts CelesTrak; `CATALOG_SOURCE`
forces `spacetrack` or `celestrak`. Each source has its own cooldown/block state file.

From `backend/`, after installing the existing `requirements.txt`:

```sh
python -m app.data.refresh
python -m pytest tests/data -q
# Same data suite without pytest:
python -m unittest discover -s tests/data -t . -v
```

Lambda handler: **`app.data.refresh.refresh_handler`** with the `backend/` directory
as deployment root. Create a separate refresh Lambda and an EventBridge
**`rate(6 hours)`** rule. Use reserved concurrency 1 as an additional guard;
the S3 conditional lease also protects separate cold starts and duplicate events.
The handler returns a small JSON result with `status` (`updated`, `skipped`,
`error`), `object_count`, `synced_at`, and `message`. Errors are logged and returned
without EventBridge triggering an immediate retry storm.

Use environment settings in `.env.example` in this folder. No AWS secret is needed
in code; use the Lambda IAM role/default AWS credential chain. S3 is optional;
without it, the process/disk cooldown is only shared by processes using the same
local cache path. Configure S3 for a distributed Lambda deployment. The role needs
`s3:GetObject` and `s3:PutObject` on both the snapshot key and its `.refresh.json`
suffix. Do not lifecycle-delete the lease while refreshers run. Use a recent boto3
supporting conditional `PutObject` (`IfMatch` and `IfNoneMatch`).

Give refresh requests a 240-second Lambda timeout (up to four 45-second HTTP
requests plus parsing). Choose API/refresh memory after measuring the real catalog;
the parsed catalog and Satrec objects use more memory than the compressed bundle.
No cloud resources are created by these changes.

Each attempt records a durable next-allowed time before any upstream call, including
failed attempts. The minimum interval cannot be reduced below 7,200 seconds. Local
exclusive files prevent concurrent processes; conditional S3 writes implement a
cross-instance lease. A failed S3 read or lease claim prevents upstream access.
No immediate HTTP retries or redirects are followed. Any failed feed stops the
batch and preserves the old catalog. HTTP 429 honors `Retry-After`; HTTP redirects,
403 and 404 persist a block until an operator fixes the URL/block and clears both
local and S3 refresh-state files. Keep the existing cooldown until at least two
hours after the last attempt. Log alerts should be configured by the deploy owner.

Snapshot writes use fsync + atomic replacement. If a successful local write is
followed by a failed S3 upload, `status=error` is returned and the new valid local
copy remains; the old S3 copy is still available. There is no claimed atomic
transaction across disk and S3. A process crash leaves the cooldown in place; an
abandoned local lock can be cleared after the two-hour window, then the next run
rechecks all cooldowns. Never invoke refresh from an API route or a browser timer.

## Feeds, metadata, and coverage

One refresh downloads these documented OMM JSON queries sequentially:

- `https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=JSON`
- `https://celestrak.org/NORAD/elements/gp.php?NAME=DEB&FORMAT=JSON`
- `https://celestrak.org/NORAD/elements/gp.php?NAME=R%2FB&FORMAT=JSON`

It joins `https://celestrak.org/pub/satcat.csv` for authoritative types, operational
status, and owner codes. SATCAT is reused for 24 hours across scheduled refreshes.
Duplicate NORAD records use the newest epoch. The source queries cover active
satellites and named debris/rocket bodies; they **do not guarantee the entire
public catalog**, especially inactive payloads and unnamed/unclassified objects.
There is no invented `GROUP=all` or an A-Z query crawl. A full current public OMM
source is an open integration request in `docs/CONTRACT_REQUESTS.md`.

SATCAT `PAY`, `DEB`, `R/B`, `UNK` map to `PAYLOAD`, `DEBRIS`, `ROCKET_BODY`,
`UNKNOWN`. Names containing the token `DEB` or `R/B` are a documented fallback,
with active-feed membership identifying payloads when metadata is absent. Other
unclassified objects remain `UNKNOWN`. Active statuses are `+`, `P`, `B`, `S`, `X`;
an explicit inactive status overrides active-feed membership. Owner is the
published ownership code, not a verified operator account. Country is null unless
provided explicitly; the historical archive provides country codes.

GP/SATCAT do not establish propulsion capability. `maneuverable` defaults to false
and becomes true only for an active payload whose ID is in the operator-verified
`CATALOG_MANEUVERABLE_IDS` setting. The offline archive has no operational-status
data, so its `active` flags are conservatively false as well. These flags are not
evidence that all historical payloads were inactive.

## Offline archive and test scope

`snapshots/catalog.json.gz` contains **28,124 real Space-Track OMM records** from the
satellite.js test archive (July 2025), compressed to about 1.84 MB. It contains
14,468 payloads, 10,419 debris objects, 2,173 rocket bodies, and 1,064 unknowns,
including ISS and SL-16 R/B. Data, metadata and original epochs are retained;
unused source TLE strings are excluded without parsing. Source blob hashes,
transformations and the upstream license are committed beside the archive.

This is a historical offline catalog, not current ephemerides. `syncedAt` for this
archive is the latest original `CREATION_DATE` (2025-07-10T18:06:17Z), because its
original download timestamp is unknown; `source` explicitly marks it historical.
Do not use it for present-day collision predictions. Current public GP data can
omit decayed demo fragments, and real NORAD/name associations may differ from the
frontend mocks. No missing demo orbit is fabricated or renamed.

The data tests exercise real native OMM initialization/propagation, contract keys,
metadata counts, six-digit IDs, cache corruption/fallback/invalidation, new epochs,
HTTP failures, cooldown boundaries, local concurrency, S3 conditional leases, and
EventBridge results. HTTP and S3 are substituted in refresh tests; these are not
claims that live CelesTrak or AWS were exercised. See the analysis and contract
requests for remaining deployment checks and the shell's synthetic-count test.

References: [CelesTrak GP formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php),
[usage policy](https://celestrak.org/usage-policy.php),
[SATCAT fields](https://celestrak.org/satcat/satcat-format.php),
[sgp4 OMM support](https://pypi.org/project/sgp4/),
[upstream data blob](https://api.github.com/repos/shashwatak/satellite-js/git/blobs/715c11f79e35282e5b1735968761db0a8edaaffc).
