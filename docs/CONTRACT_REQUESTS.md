# Contract requests

Add requests at the bottom. Say who asks, who answers, and the status.

## PHYS-1 · Physics → Screening: encounter state at TCA (done by be-screening)

`be-screening`'s `Encounter` already carries the TEME states at TCA, the combined covariance and the
HBR. `maneuver.encounter_from_screening(encounter)` converts it (duck-typed, no sgp4 import). On a
real SGP4 conjunction, Physics and Screening Pc agree to a ratio of 1.000000 (see PHYS-8). Without
it, `plan_for_detail()` falls back to rebuilding geometry from `rtnM` and `relSpeedKms`; on the same
case that gave the same Δv within 0.01 m/s.

## PHYS-2 · Physics → Lead: wiring (open)

Code lives at the repo root, `app/physics/` and `tests/physics/`, like `app/ai/` on `be-ai`.

- `GET /api/conjunctions/:id`, with `enc` = the screening `Encounter` for that id:
  ```python
  detail = run.get_detail(id)
  detail.update(plan_for_detail(detail, now=now, encounter=encounter_from_screening(enc)).to_contract())
  ```
  This sets `options` and, when a burn is recommended, `afterSeries`. With no screening `Encounter`
  at hand, leave out `encounter=`; it falls back to rebuilding geometry from the detail.
- Negotiator candidates, as the AI agent requested (PHYS-6): for each side,
  `next(x for x in options_for(detail, ref["noradId"], now=now, encounter=...) if x["direction"] != "none")`,
  keyed by `str(ref["noradId"])`.
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

## PHYS-8 · Physics → Screening: review of `app/physics/screening.py` (be-screening 6ffe5a6)

How I checked it: ran Screening's 46 tests locally (all pass). Compared both Pc implementations on
400 random geometries against a brute-force disk integral. Screened a synthetic ISS × COSMOS
crossing with real SGP4 (949 m miss, 4.08 km/s, tilted correlated covariance, Pc 4.98e-4) and fed the
resulting `Encounter` into the maneuver planner.

Correct, no action needed:

- The 2-D Pc formulation (Gaussian centred on the miss, HBR disk at the origin, eigen-rotation,
  x = R·sin θ, tail-safe erfc). The RTN → TEME → encounter-plane covariance combination. Real SGP4
  `rangeSeries`. The explicit `risk_model`, so no covariance is silently invented. WGS72 SGP4
  straight from OMM.
- Broad-phase padding a·dt²/8 with a = 0.03 km/s² is a valid chord-deviation bound, since relative
  gravitational acceleration is ≤ 2g ≈ 0.0196 km/s².

Findings:

1. **Encounter-plane axis convention (fixed on the Physics side).** Screening uses y = v̂_rel × x̂.
   Physics used x̂ × v̂_rel, which mirrors `angleDeg`. On the test case the mirrored axis gave Pc 5.09e-4
   instead of 4.98e-4; the error grows with ellipse tilt. Physics now uses Screening's convention.
   It is also the right one for the UI: v_rel's along-track part is always negative in LEO
   crossings, so y ≈ +N, as the EncounterPlane draws it. Please keep the convention stable and note
   it in your README.
2. **Window-boundary "TCAs" (minor).** When range is increasing at the window start (or decreasing at
   the end), a boundary point is reported as the TCA. `missDistanceM` is then the 3-D range at the
   boundary, but `pc` uses the encounter-plane projection. That projection is the miss of a pass
   *outside* the window, so the two numbers disagree. With a 10 km envelope at 10 km/s this needs the
   real TCA within about 1 s of the edge. Slow, near co-orbital pairs (0.01–1 km/s) can stay inside
   the envelope for minutes, though. Suggest: drop start-boundary minima (that pass is over) and refine
   end-boundary ones beyond `end` to the true TCA, or flag them as an issue.
3. **Pc convergence tolerance (cosmetic).** `abs(p - prev) <= 1e-12 + 1e-6 p` stops at 32 nodes for
   tiny Pc. Below about 1e-10 results are only good to a few percent (2.8 % at 1e-38 against brute
   force). That is irrelevant to the 1e-6 / 1e-5 / 1e-4 thresholds; a relative-only test or a note
   would do.
4. **Middle erfc branch (nit).** `1 - (erfc(b) + erfc(-a)) / 2` cancels when the y-chord is short (near
   the disk edge); `(erf(b) - erf(a)) / 2` keeps full precision. Negligible effect on totals.
5. **Contract item 7 (agree).** The frontend's ellipse view is schematic R/N; with the convention in
   (1) it is a good approximation when v_rel is mostly along-track.
