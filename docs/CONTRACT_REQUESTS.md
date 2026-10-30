# Contract requests

Add requests at the bottom. Say who asks, who answers, and the status.

## PHYS-1 · Physics → Screening: encounter state at TCA (open, not blocking)

`maneuver.plan_for_detail()` already works from contract fields alone. It rebuilds the geometry from
`rtnM` and `relSpeedKms`, assuming near-circular orbits; see `encounter_from_detail`. For exact
geometry, pass an `Encounter` as `encounter=`. Please expose for each conjunction:

- `tca` (UTC datetime)
- `r_primary_km`, `v_primary_kms`, `r_secondary_km`, `v_secondary_kms` at TCA, in one inertial frame
  (TEME straight from SGP4 is fine)
- the combined covariance, as the contract `covariance` object: `sigmaMajorM`, `sigmaMinorM`, `angleDeg`.
  It lives in the encounter plane perpendicular to v_rel. The angle runs counter-clockwise from the
  radial axis, matching the frontend's R-horizontal / N-vertical EncounterPlane.
- `hardBodyRadiusM` and the `rangeSeries` `tSec` grid

Proposal: compute the list `pc` with `app.physics.maneuver.collision_probability()` so that `pc` and
each option's `newPc` use the same formula.

## PHYS-2 · Physics → Lead: wiring (open)

Code lives at the repo root, `app/physics/` and `tests/physics/`, like `app/ai/` on `be-ai`.

- `GET /api/conjunctions/:id`:
  `detail.update(plan_for_detail(detail, now=now, primary_omm=primary["omm"]).to_contract())`.
  This sets `options` and, when a burn is recommended, `afterSeries`. Add `encounter=` once
  Screening provides states.
- Negotiator candidates (answers the AI request below):
  `{str(o["noradId"]): next(x for x in options_for(detail, o["noradId"], now=now) if x["direction"] != "none") for o in (primary, secondary)}`.
- `POST /api/cascade`: `simulate(request, catalog, environment=env).result` returns `CascadeResult`.
  `LookupError` → 404, `ValueError` → 400. Cache `env = build_environment(catalog)` per catalog sync
  (about 1.2 s). `.diagnostics` (J2 nodal spread per year, ring-closure year) is extra context for
  the AI brief, not for the HTTP response.
- All entry points take dicts or Pydantic models with the contract field names and return
  camelCase dicts.

## PHYS-3 · Physics → Lead (frontend owner): cascade visual scale (FYI)

NSBM fragment Δv for an SL-16 collision gives `spreadDvMs` ≈ {357, 583} m/s, against {85, 38} in the
mock. `cascade.vert.glsl` scales kicks by `sd/100`, so the real cloud will look much wider. If it looks
wrong in the demo, the shader scale should be clamped. The API values stay physical.

## PHYS-4 · Physics → Lead: dependencies (FYI)

`app/physics/` needs only `numpy` (tested with numpy 2.x). Tests need `pytest`.
`tests/physics/conftest.py` adds the repo root to `sys.path` until a project-wide pytest config exists.
Root `.gitignore` should get `__pycache__/` and `*.pyc` (the AI agent flagged this too).

## PHYS-5 · Physics → Screening/Lead: demo fixture consistency (FYI)

The mock `iss-cosmos` pair (412 m miss, covariance 186/74 m, HBR 58 m) gives Pc ≈ 3e-7, not the mock's
3.1e-4. If the ISS demo must show a critical event, the screened miss or covariance has to support it.
Don't hard-code the Pc.

## PHYS-6 · Physics → AI: per-object options (answer to "AI → Physics" on be-ai, done)

`app.physics.maneuver.options_for(detail, mover_norad_id, now=...)` returns `ManeuverOption[]` for the
case where that object moves, using its own mass/Isp. A non-maneuverable object gets only
"No action". Notes:

- Options are along-track burns: A = the cheaper of prograde/retrograde at about 6 h lead, B = the
  other direction, C = early (about 18 h, cheapest), D = late (about 2 h, last chance). All reach
  Pc ≤ 1e-7, which meets the negotiator's 1e-6 bar.
- `recommended` is set only when Pc ≥ 1e-4. For the Starlink × OneWeb mock (8.7e-5), "No action" is
  recommended. Pick the first burn option as the candidate, as in the PHYS-2 snippet, not the
  `recommended` one.
- My mass/Isp table matches `app/ai/profiles.py` (ISS 420 t/300 s, Starlink 800 kg/1500 s,
  OneWeb 150 kg/1600 s, EO 1000 kg/220 s, default 500 kg/220 s). It is duplicated for now; the Lead may
  want one shared table.
- Propellant is reported to 4 significant figures, so OneWeb gram-level burns never show as 0 kg.

## PHYS-7 · Physics → Lead: merge note (FYI)

`be-ai` and `be-physics` both create `docs/CONTRACT_REQUESTS.md`, so expect a merge conflict. Keep
both sets of sections.
