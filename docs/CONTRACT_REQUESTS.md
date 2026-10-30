# Contract requests

Add requests at the bottom. Say who asks, who answers, and the status.

## PHYS-1 · Physics → Screening: encounter state at TCA (open)

`maneuver.plan_maneuvers()` needs one `Encounter` per conjunction. Please expose for each conjunction:

- `tca` (UTC datetime)
- `r_primary_km`, `v_primary_kms`, `r_secondary_km`, `v_secondary_kms` at TCA, in one inertial frame
  (TEME straight from SGP4 is fine)
- the combined covariance, as the contract `covariance` object: `sigmaMajorM`, `sigmaMinorM`, `angleDeg`.
  It lives in the encounter plane perpendicular to v_rel. The angle runs counter-clockwise from the
  radial axis, matching the frontend's R-horizontal / N-vertical EncounterPlane.
- `hardBodyRadiusM` and the `rangeSeries` `tSec` grid

Proposal: compute the list `pc` with `app.physics.maneuver.collision_probability()` so that `pc` and
each option's `newPc` use the same formula.

## PHYS-2 · Physics → Lead: backend root and wiring (open)

- I assumed the package is at `backend/app/`. Tell me if it is elsewhere and I'll `git mv`.
- `GET /api/conjunctions/:id`: `plan = plan_maneuvers(encounter, now=now)`, then
  `detail["options"], detail["afterSeries"] = plan.options, plan.after_series` (via `plan.to_contract()`).
- `POST /api/cascade`: validate `CascadeRequest` and look up the parent (404 if missing), then call
  `simulate_cascade(parent, catalog, event=…, years=…, include_launches=…)`. It returns a dict shaped
  exactly like `CascadeResult`. Cache `baseline_survival(catalog)` per catalog sync.
- Both functions accept catalog objects as dicts or as Pydantic models with the contract field names.

## PHYS-3 · Physics → Lead (frontend owner): cascade visual scale (FYI)

NSBM fragment Δv for collisions has a standard deviation of about 100–200 m/s, against 38 m/s in the
mock. `cascade.vert.glsl` scales kicks by `sd/100`, so the real cloud will look much wider. If it looks
wrong in the demo, the shader scale should be clamped. The API values stay physical.
