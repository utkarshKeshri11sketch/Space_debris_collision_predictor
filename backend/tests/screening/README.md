# Screening handoff

Branch `be-screening`; runtime target Python 3.11. Core is
`backend/app/physics/screening.py`, API wiring is
`backend/app/routers/conjunctions.py`, and the external check is
`backend/scripts/validate_socrates.py`.

## Calls and API

```python
from app.physics.screening import screen_catalog, screen, get_conjunction, get_encounter

run = screen_catalog(cached_catalog_objects, 25544, days=7, min_pc=1e-6)
assert run.complete or run.issues  # surface partial coverage
events = run.conjunctions       # frontend Conjunction dictionaries
detail = run.get_detail(events[0]["id"])

api_events = screen(target_id=25544, days=7, min_pc=1e-6)
api_detail = get_conjunction(api_events[0].id)
physics_state = get_encounter(api_events[0].id)
```

`GET /api/conjunctions?noradId=25544&days=7&minPc=0.000001` returns the
frontend `Conjunction[]` contract. `noradId` is optional; omitted uses the
first ID in `SCREENING_TARGET_IDS` (default ISS 25544). Detail is
`GET /api/conjunctions/{id}`. IDs encode pair, full UTC TCA and an
orbital-element hash, allowing cold Lambda detail reconstruction from the
same snapshot. No mock event is inserted when current elements yield none.

The list has `X-Screening-Complete`, `X-Screening-Issues` and
`X-Screening-As-Of` headers. Partial runs retain computed events while
flagging invalid elements, propagation failures and unsupported slow pairs.
`SCREENING_CATALOG_PATH` points to a local raw OMM JSON array or a `catalog`
envelope; otherwise Data's `load_catalog()` supplies the snapshot. API runs
are cached 15 minutes and details 2 hours, keyed to a full snapshot hash.
Neither performs remote catalog refresh. Data must keep the same snapshot
across Lambda instances for cold detail requests.

`Encounter` exposes TEME TCA positions/velocities, primary/secondary IDs
and names, plane sigmas and angle, combined hard-body radius, and
`range_t_sec` for Physics Device 4. If `plan_for_detail` is installed, detail
attaches its burns; until that module lands under `backend/`, detail offers a
computed do-nothing option only. `rangeSeries` is 81 propagated ranges over
TCA ±60 seconds. Optional `afterSeries` needs a propagated maneuver curve.

## Search and risk assumptions

- Native OMM uses UTC/TEME/WGS72 SGP4. Required dynamics and epoch are
  validated. Full public catalog IDs remain integers even when sgp4's
  legacy internal identification field cannot encode them.
- The target perigee/apogee band is extended by 10 km once. This assumes no
  drag or maneuver shifts beyond the margin.
- `SatrecArray` propagates at 60-second intervals, in batches of 128 and
  chunks of 128 intervals. A swept relative chord with 0.03 km/s² relative
  acceleration padding selects intervals. Each is subdivided into eight;
  `r·v = 0` roots refine to 1 ms. No two unresolved extrema within 7.5 s
  is assumed. This is a numerical search, not a certified continuous bound.
- Search envelope is 10 km. The entire requested window must lie within
  14 days of each element epoch. These are demo policies.
- The **assumed**, illustrative 1-sigma RTN position errors at TCA are
  payload (100,300,100)m, debris (300,1000,300)m, rocket body
  (200,600,200)m, unknown (500,1500,500)m. Bounding radii are 5m, 1m,
  5m, 5m; ISS uses an illustrative 58m enclosing radius. OMM supplies
  neither covariance nor dimensions. The detail brief preserves the
  `ASSUMED` provenance. Pass a custom `risk_model` with CDM inputs later.
- Pc integrates an independent Gaussian over the 2D encounter-plane
  hard-body disk. The plane is perpendicular to relative velocity; RTN
  miss values use the primary's real radial, transverse, normal axes. The
  frontend R/N ellipse is schematic. Correlated errors and long-duration
  co-orbital encounters require another model.
- Speeds under 0.01 km/s are `slow_encounter` issues. Formation pairs below
  that speed throughout a 128-minute chunk skip TCA refinement, assuming
  smooth SGP4 motion without an impulsive burn. They are never assigned
  zero risk. Display thresholds critical Pc ≥1e-4 and high ≥1e-5 are demo
  categories, not flight rules.

## SOCRATES comparison

From `backend/`, use a real cached OMM snapshot and timestamp-matched CSV:

```powershell
python scripts/validate_socrates.py --catalog snapshot.json --socrates report.csv --norad-id 25544 --days 7 --strict
```

`--download` fetches SOCRATES once per two hours; `--gp-url` can point to
an explicit OMM JSON URL for a limited catalog check. Failed fetches also
record an attempt. The JSON report records pair/TCA matches, time/range/
speed errors, element-epoch compatibility, exclusions, object issues,
runtime and `validationPassed`. Without `--strict`, a zero exit only means
the comparison ran. Strict mode requires eligible matches and a complete run.
SOCRATES `MAX_PROB` uses a different covariance choice than our Pc.

On 2026-10-30, an **active-only** GP snapshot held 16,846 objects and 362
ISS band candidates. Three days took 1.02 s locally and produced 5 fast
encounters. The SOCRATES report had 96 ISS references in that window: 94
slow formation/docking events outside this Pc model, and 2 computed pairs
with different element epochs. Their TCA differences were 0.639 s and
0.649 s; miss differences were 7,256 m and 1,386 m. **External validation
has not passed.** This catalog also excludes debris and rocket bodies. A
full Data snapshot with matched element sets is needed for the requested
real ISS check. The raw GP/CSV files are ignored by Git.

## Local verification

```powershell
cd backend
python -m venv tests/screening/.venv
tests/screening/.venv/Scripts/python.exe -m pip install -r requirements.txt
tests/screening/.venv/Scripts/python.exe -B -m pytest tests/screening -q -p no:cacheprovider
```

63 focused tests pass locally on Python 3.14.3. A synthetic 33,482-object,
7-day screen took 7.1 s with 525 band candidates. The active-only 3-day
run above took 1.02 s after slow-pair pruning. Neither establishes Lambda
timing with the full catalog. Python 3.11 syntax parses; runtime execution
on AWS Python 3.11 remains an integration check.
