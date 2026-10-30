# Screening module handoff

Owner: `be-screening`. Runtime: Python 3.11+, NumPy and python-sgp4.
Only `app/physics/screening.py` and this test area belong to Screening;
Lead owns routing, shared models, deployment, and integration.

## Integration

```python
from datetime import datetime, timezone
import numpy as np
from app.physics.screening import EncounterUncertainty, screen_catalog

# EXAMPLE ONLY: per-object 1-sigma RTN errors 100/300/100 m and combined
# radius 10 m. These are illustrative, not values derived from public GP.
# Supply real TCA covariance/size from a CDM or an explicit assumed model.
def risk_model(primary, secondary, tca):
    return EncounterUncertainty(
        primary_covariance_rtn_m2=np.diag([100**2, 300**2, 100**2]),
        secondary_covariance_rtn_m2=np.diag([100**2, 300**2, 100**2]),
        hard_body_radius_m=10,
        source="Demo: assumed RTN sigmas 100/300/100 m for each object; combined radius 10 m",
        illustrative=True,
    )

run = screen_catalog(
    cached_catalog, 25544, risk_model=risk_model,
    start=datetime.now(timezone.utc), days=7, min_pc=1e-6,
)
# Log/surface run.issues; do not present an incomplete run as a clean result.
if not run.complete:
    handle_incomplete_run(run.issues)
list_response = run.conjunctions  # Exact Conjunction[]; not the run container.
# Pass Physics' options and AI's assessment when available; options default [].
detail_response = run.get_detail(event_id, options=physics_options, brief=ai_brief)
```

The example's undefined names are supplied by Lead's catalog/cache/router.
`get_detail` raises `KeyError` for an unknown ID (map to the contract's 404).
`ScreeningError` is an invalid request or invalid primary orbit (map to an
appropriate error status with a `message` field). Secondary orbit/encounter
failures produce `ScreeningIssue` entries and `run.complete == False`.
Unexpected exceptions in the supplied risk provider propagate to the caller;
missing risk inputs must never be silently replaced with zero Pc.

`RiskModel(primary_catalog_object, secondary_catalog_object, tca_datetime)`
returns `EncounterUncertainty`. It must supply **position covariance at TCA**,
expressed in each object's own RTN frame in square metres, combined bounding
radius in metres, a provenance string and an explicit illustrative flag.
The model may vary by spacecraft, epoch, age, or encounter. The screening
module does not infer covariance or spacecraft dimensions from OMM.

`Encounter` retains primary/secondary `CatalogRecord` and TEME position/velocity
at TCA for the Physics agent. `record_from_catalog`, `state_at`, `rtn_basis`,
and `collision_probability` are reusable by Physics. The latter takes a 2D
encounter-plane mean in metres, covariance in square metres, combined radius
in metres. `rtn_basis` rows map TEME into RTN; the inverse is its transpose.
`Encounter.as_detail()` propagates 81 real ranges over +/-60 seconds.
It appends uncertainty provenance to the brief even when an AI brief is given.
No fake manoeuvres, post-burn curves, or conjunctions are inserted.

## Contract and caching

- List output exactly matches `frontend/src/api/types.ts` `Conjunction`.
- Detail adds `rangeSeries`, `covariance`, `hardBodyRadiusM`, `options`, `brief`.
  Optional `afterSeries` is omitted until Physics supplies a propagated curve.
- Times are UTC ISO strings with `Z`; IDs are deterministic for the snapshot,
  pair, TCA, and numerical configuration. Retain a run in the cache so detail
  requests resolve the same encounter IDs as the list.
- Results sort by descending Pc, then TCA and secondary ID. Default filters
  are `days=7`, `min_pc=1e-6`; days=0 yields an empty list, matching the mock.
- `run.encounters` contains only events passing `min_pc` and the configured
  distance envelope. Cache at the lowest required Pc threshold, then filter
  in the router for narrower requests; filtering cannot recover omitted events.
- Run one selected primary per screening call. There is no all-pairs catalog
  scan and no automatic choice of protected satellites. The frontend's list
  API has no selected-satellite parameter: Lead must choose the protected IDs
  and aggregate runs or approve an optional query parameter.
- This function performs no network I/O. Data owns catalog refresh throttling,
  S3 and local snapshots. Reuse that snapshot. Do not screen all 30k objects
  on every API request; precompute on refresh/a worker and cache the results.
  No 30k-by-seven-day state history is retained: default batch 128 satellites
  by 129 dates bounds the main NumPy arrays to a few MB per batch. Runtime
  still scales with catalog size and horizon. AWS runtime is unbenchmarked.

## Explicit assumptions and limits

- Native OMM -> WGS72 SGP4/SDP4 in TEME, no TLE conversion. GP's omitted
  centre/frame/time/theory metadata are Earth/TEME/UTC/SGP4. Conflicting
  metadata, missing dynamic fields, ID mismatch and nonfinite values fail
  validation. Metadata-only defaults are documented in code.
- Full external NORAD IDs up to nine digits survive. python-sgp4's internal
  legacy Alpha-5 ID field cannot represent IDs above 339999, so only its
  unused identification field uses 0 for those IDs. Key records by
  `CatalogRecord.norad_id`, never `record.satellite.satnum`.
- Coarse interval default 60 s, capped at 60 s. Candidates are selected by
  closest point on the **relative swept chord**, padded by a relative
  acceleration bound of 0.03 km/s^2 times dt^2/8. This exceeds twice surface
  gravity and assumes non-decayed, non-manoeuvring Earth orbits. It catches
  fast crossings between endpoint samples. It is not a certified guarantee
  for arbitrary accelerations, drag transients, or unresolved orbital events.
- Candidate intervals are subdivided into eight brackets and SGP4 `r dot v`
  zeros are bisected to 1 ms. Assumption: no unresolved pair of extrema in
  a 7.5 s subinterval. Distinct orbital passes are retained and duplicate
  bracket/chunk-boundary roots are removed. Closed-window boundary minima
  are included, even when the unconstrained TCA lies outside the window.
- Search envelope 10 km, element age policy 14 days across the full window,
  and risk categories critical >=1e-4 / high >=1e-5 / watch otherwise are
  configurable demo policies, not flight safety rules. No scenario is
  forced to be dangerous: the frontend's sample pairs may have no live event.
- Pc assumes independent Gaussian position errors. Per-object RTN
  covariances rotate to TEME, combine, and project perpendicular to relative
  velocity. A Gaussian disk integral uses converging quadrature and stable
  Gaussian tail functions. Correlated errors are not handled.
- `covariance.angleDeg` is measured from primary radial projected onto the
  encounter plane, with the second axis completing that plane. The frontend
  draws an R/N schematic that is only an approximation for general geometry.
  `rtnM` always holds actual primary RTN miss components.
- Encounters slower than 0.01 km/s are explicitly flagged as unsupported for
  this short-encounter 2D Pc model. Such events are not assigned zero risk.
- Sources: [python-sgp4 documentation](https://github.com/brandon-rhodes/python-sgp4)
  and [NASA CARA risk assessment](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/).

## Local verification

From the repository root, use an isolated Python environment:

```powershell
python -m venv tests/screening/.venv
tests/screening/.venv/Scripts/python.exe -m pip install -r tests/screening/requirements.txt
$env:PYTHONDONTWRITEBYTECODE = '1'
tests/screening/.venv/Scripts/python.exe -m pytest tests/screening -q -p no:cacheprovider
```

Tests use synthetic OMM fixtures, analytic Gaussian probabilities, and the
published SGP4 ISS reference example. They never fetch CelesTrak data or
consume AWS credits. Comparison against a timestamp-matched SOCRATES report
and a 30k-object Lambda runtime measurement still require integration data.

Verified locally: 46 tests passed using Python 3.14.3, NumPy 2.5.4,
sgp4 2.27 (accelerated wheel), and pytest 9.2.0. Python 3.11 syntax parsing
passed; execution on the intended Python 3.11 Lambda runtime is still pending.
