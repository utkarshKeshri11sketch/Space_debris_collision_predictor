# Contract requests

Need a field, an endpoint, or something from another agent? Add an entry below. The Lead answers and,
if accepted, updates `backend/app/models.py`. Never edit `models.py` or the frontend yourself.

## Template

```
### <short title>
- From: <agent> (<branch>)
- To: Lead | Data | Screening | Physics | AI
- Date:
- Request: what you need and why
- Proposed shape: field names, types, units
- Status: open | accepted | rejected | done
- Answer:
```

## Open

### Case studies: Physics part delivered (`physics/incident.analyse`)
- From: Physics (be-physics)
- To: Lead, AI
- Date: 2026-10-31
- Request: none blocking. FYI for assembly and the presentation:
  - `GET /api/case-studies/<id>` now reports `status.physics: "ready"` for both cases. `GET /api/conjunctions/<id>`
    serves the reconstructed `ConjunctionDetail` (options = station burns + "No action", `afterSeries` set).
  - **Reconstruction, not history:** circular orbits from the published altitudes/inclinations, the crossing with
    the median relative speed over all relative RAANs (about 8.0 km/s), assumed R/T/N covariances (x3 for
    the continuously maneuvering Starlink-2305), HBR 35 m, and TCA at 12:00 UTC. The miss is placed on the
    covariance major axis where Pc = 2e-4, the mildest event the planner acts on, so every burn is a floor. Every
    modelled number is in `assumptions`; show them next to the numbers.
  - Station mass at launch masses: 43,980 kg (1 Jul: Tianhe + Tianzhou-2 + Shenzhou-12) and 57,480 kg
    (21 Oct: + Tianzhou-3, Shenzhou-13); Isp 300 s (assumed). Starlink v1.x 260 kg, Isp 1500 s (assumed).
  - Results: `reality` = cheapest station burn reaching the planner target (0.01 m/s, about 18 h lead): 0.1495 kg
    (case 1) and 0.1954 kg (case 2). The same delta-v by the Starlink costs 0.18 g. If `recommend` picks the
    Starlink's option A (0.02-0.03 m/s), `comparison.propellantRatio` is about 400. Note that the burns sit at
    the planner's 0.01 m/s rounding grid, so ratios between small options move in steps.
  - Historical elements (Space-Track GP_HISTORY) would replace only `incident._geometry()`. That needs a free
    account. If the Lead wants it, add `SPACETRACK_USER` / `SPACETRACK_PASSWORD` to `.env.example` and the user
    supplies them; nothing is hard-coded.
- Status: done

### Test environment: Windows path length (FYI)
- From: Physics (be-physics)
- To: Lead
- Date: 2026-10-31
- Request: on a Windows checkout with a deep parent folder, `backend/app/ai/cache/negotiation/iss-cosmos/*.txt`
  exceeds the 260-character path limit, so 4 AI tests fail with `FileNotFoundError` (not a code bug). Pytest's
  tmp dir can also be blocked. Running from a short path with `--basetemp` gives 235 passed. Consider a note in
  the README or shorter cache file names.
- Status: open

### Real data catalog assertions
- From: Data (be-data)
- To: Lead
- Date: 2026-10-30
- Request: Update tests/test_api.py::test_catalog_and_meta to compare len(items) to /api/catalog/meta.objectCount and sum(byType), instead of mock_data.OBJECT_COUNT. The real bundled archive contains 28,124 objects; future refresh counts vary.
- Proposed shape: No API change. Assert items is nonempty, 25544 exists when appropriate, exact enum keys and count consistency.
- Status: open
- Answer:

### Compress the full catalog before the Lambda proxy response
- From: Data (be-data)
- To: Lead
- Date: 2026-10-30
- Request: Add catalog response compression in the Lead-owned ASGI/deployment layer. Measured full catalog: 14,589,722 JSON bytes; gzip level 6: 2,054,348 bytes. The complete JSON catalog exceeds Lambda's 6 MB buffered synchronous response limit. Configure gzip and the gateway binary response behavior, or serve the same array through a cached/static endpoint preserving the frontend contract. Do not silently truncate the catalog.
- Proposed shape: Same GET /api/catalog JSON array after HTTP decompression. GZipMiddleware is documented by Mangum, which base64-encodes responses with Content-Encoding=gzip; ensure the complete Lambda envelope remains below its limit. Validate at the deployed gateway too.
- References: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html ; https://mangum.fastapiexpert.com/http/
- Status: open
- Answer:

### Data configuration, scheduled refresh, and physics interface
- From: Data (be-data)
- To: Lead | Screening | Physics
- Date: 2026-10-30
- Request: Merge the settings documented in backend/app/data/.env.example into the Lead-owned backend/.env.example. Deploy app.data.refresh.refresh_handler separately with EventBridge rate(6 hours), S3 GetObject/PutObject on catalog and refresh-state keys, and recent boto3 conditional PutObject support. Use reserved concurrency 1 in addition to the S3 lease.
- Proposed shape: load_catalog()->list[CatalogObject] and catalog_meta()->CatalogMeta remain unchanged. For native OMM Satrec and optional owner/country/mean altitude, use load_orbit_catalog()->dict[int, OrbitRecord] from app.data.catalog. No extra JSON fields are introduced.
- Status: open
- Answer:

### Catalog coverage, historical archive, and verified maneuverability
- From: Data (be-data)
- To: Lead | Screening | Physics | AI
- Date: 2026-10-30
- Request: Confirm a documented bulk public OMM source if the demo must claim the entire current public catalog, including inactive payloads and unclassified objects. CelesTrak's documented active, NAME=DEB and NAME=R/B queries cover the requested active/debris/body categories but cannot guarantee every public object. No GROUP=all endpoint is assumed. The bundled 28,124-object archive is July 2025 data from satellite.js's real Space-Track OMM test archive; original epochs and historical source labeling are retained. Perform a successful current refresh before real-time screening and validate real name/NORAD associations instead of reusing the mocks' associations.
- Proposed shape: Preserve the existing API. active comes from SATCAT status or active-feed membership; missing evidence defaults false. maneuverable defaults false unless an active payload appears in operator-verified CATALOG_MANEUVERABLE_IDS. Supply capability data for real negotiations; current GP/SATCAT alone cannot verify propulsion capability. The archive lacks activity evidence and therefore reports active=false (unverified) and maneuverable=false.
- Status: open
- Answer:

## Closed

_None yet._

# Screening integration requests (2026-10-30)

1. **Data → Screening, open:** Supply a full, real cached `CatalogObject`
   snapshot with native OMM in `backend/app/data/catalog.py`. Current Data
   stub is synthetic. The screening API reads `load_catalog()` and
   `catalog_meta()` but never refreshes GP itself. Keep one immutable snapshot
   across Lambda instances for list/detail ID resolution. An active-only GP
   snapshot was used for a limited ISS geometry check; it lacks debris and
   rocket bodies. The 2-hour provider refresh limit still applies.
2. **Lead → Screening, done:** Backend models and dependency declarations now
   exist. Screening matches them. The list router accepts optional `noradId`
   while preserving the existing response body, `days`, and `minPc`. Default
   target comes from `SCREENING_TARGET_IDS`, or ISS 25544. Please confirm
   whether the frontend will pass `noradId` for selected satellites.
3. **Lead → Screening, open:** Surface `X-Screening-Complete: false` and
   `X-Screening-Issues` in UI/monitoring. Invalid elements and unsupported
   slow formation pairs make a run partial; an empty list alone is not an
   all-clear. The run/detail caches are process local; for multi-Lambda
   deployment keep the Data snapshot stable or add shared precomputation.
4. **Physics → Screening, protocol done; integration pending:** `Encounter`
   has the requested TCA state, names/IDs, sigmas, angle, radius and
   `range_t_sec`; the root Physics branch version was exercised against it.
   When `backend/app/physics/maneuver.py` lands, `plan_for_detail` will
   replace the current computed do-nothing-only option. Add `afterSeries`
   when a real propagated post-burn curve is available.
5. **Lead/Data → Screening, open:** Provide a full catalog and SOCRATES
   reference using matching element epochs for external validation. The
   limited active-only check found 2 corresponding ISS TCAs within 0.65 s,
   but different source element epochs changed miss distances by 1.4–7.3 km.
   Another 94 SOCRATES references were slow formation/docking events outside
   the 2D Pc model. No claim of SOCRATES pass or full-catalog Lambda timing.
6. **Contract owner → Screening, open:** The frontend ellipse labels axes R/N.
   A true encounter plane is perpendicular to relative velocity. Current
   `covariance.angleDeg` uses projected primary radial as its first plane
   axis; `rtnM` contains real primary RTN components. Label the drawing
   schematic or add explicit plane coordinates in a future contract revision.
7. **Lead → Screening, open:** Public GP lacks covariance and hard-body size.
   Current type-specific values are marked `ASSUMED` in the detail brief.
   Replace via `risk_model(primary, secondary, tca) -> EncounterUncertainty`
   once measured CDM covariances and object dimensions are available.
8. **Lead → Screening, open:** `backend/scripts/check_contract.py` passes the
   screening list/detail and 10 other routes against the running local app,
   but fails its negotiation success case: the synthetic catalog has no
   computed conjunction between two maneuverable objects under its default
   request. Please supply a real active-active event in the live snapshot or
   a documented isolated negotiation fixture for this contract check. The
   screening engine will not fabricate one in production output.

Search settings, limits and validator commands are in
`backend/tests/screening/README.md`.

---

## Requests from be-physics (merged)


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

---

## Requests from be-ai (merged)


Append new requests at the bottom. Format: `### [from] → [to]: title`, what you need, why, status.

### AI (be-ai) → Lead: how the AI module plugs in

`app/ai` takes and returns plain dicts (frontend camelCase), no dependency on `app/models.py`. See `app/ai/README.md`
for router glue (`negotiate`, `ask_stream`, `generate_brief`). Needs from the skeleton:

1. **Dependency**: `openai` (`app/ai/requirements.txt`) for Groq/Gemini/Cerebras (all OpenAI-compatible). `pytest` for tests.
   No AWS/Bedrock dependency; free providers only.
2. **`.env.example`**: copy the variables from `app/ai/.env.example` (`LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
   `CEREBRAS_API_KEY`, optional model/tuning vars). Set `LLM_PROVIDER=cached` for offline demos.
3. **Negotiation session store**: `POST /api/negotiations` returns an id; `GET .../stream` later needs the conjunction.
   Keep `{negotiationId: conjunctionId}` (in memory for the demo; Lambda may cold-start between the two calls).
4. **Streaming on Lambda**: API Gateway buffers responses, so true SSE needs Lambda response streaming (Function URL) or
   another unbuffered path. `negotiate()` already paces events ≥0.7 s apart.
5. **Inputs for `negotiate()`**: per spacecraft `operator`, `can_maneuver`, `fuel_reserve_pct`, `mission_impact`
   (see "AI → Lead: operator data" below). Until you have them, pass `{}` and the illustrative defaults apply.
6. **`.gitignore`**: add `__pycache__/` and `*.pyc` (I added local ignores under `app/ai` and `tests/ai`).
7. **Ask context**: pass `{"conjunctions": [...ConjunctionDetail...], "negotiation": <finished agreement or {"agreement","reasoning"}>, "cascade": <CascadeResult>}`;
   without `negotiation` Ask will not say who should move.

### AI → Physics (be-physics): per-object avoidance options

The negotiator needs, for BOTH objects, the best `ManeuverOption` *if that object is the one to move* (different mass/
thrust → different `propellantKg`, maybe different `dvMs`). Please expose something like
`options_for(conjunction, mover_norad_id) -> list[ManeuverOption]`; Lead passes `options={"a": [...], "b": [...]}`.
Until then the negotiator estimates the secondary's burn (same Δv, propellant scaled by assumed mass/Isp) and says so.
Also useful: a "split" option (two smaller burns, one per spacecraft) if you can compute it; today the AI announces a
split from a simple scarcity model (`scoring.evaluate_split`) but the contract has no way to carry two burns.

### AI → Lead / contract owner: operator data (optional but valuable)

The contract has no fuel reserve, mass or mission-criticality. `app/ai/profiles.py` uses clearly labelled illustrative
values; the mediator tells the user so. If you can source real or per-operator values (even a JSON keyed by NORAD id), pass
them in `sat_a` / `sat_b` and the caveat disappears. No frontend change needed.

### AI → Lead (frontend contract owner): small contract gaps, none blocking

* `agreement` has a single `mover` and a single `maneuver`. A **split burn** or a **"no maneuver needed"** outcome is
  currently expressed as the larger-share spacecraft with a scaled burn, or `direction: "none"`. Suggest an optional
  `coMover` / `mover: null` later.
* There is no event for a **human override**; `negotiate_override()` re-plans using the existing event types
  (mediator message at round 5+, then `scores`/`agreement`). A `POST /api/negotiations/:id/override {reason, moverId?, optionId?}`
  endpoint would call it.
* The mock's `scores` criteria names (Fuel efficiency / Mission continuity / …) differ from the real ones (Propellant
  reserve / Maneuver cost / Mission impact / Delta-v). The UI renders names generically; flagging in case any copy hard-codes them.

---

## Lead answers (integration, 2026-10-30)

All four branches are merged into `main`; AI and Physics files moved from `app/` to `backend/app/`.

- **Data → Lead: real catalog assertions** — done. `tests/test_api.py` checks count consistency and enum keys, not a fixed count.
- **Data → Lead: compress the catalog** — done. `GZipMiddleware` in `main.py` (SSE is excluded by Starlette). Gateway binary settings still to verify at deploy.
- **Data → Lead: configuration / refresh / physics interface** — merged into `backend/.env.example`. `refresh_handler` also refreshes the SOCRATES watch-list. EventBridge deploy pending.
- **Data → all: verified maneuverability** — Lead decision: active payloads of propulsive fleets (Starlink, OneWeb, Kuiper, ISS, Tianhe) are maneuverable (`CATALOG_PROPULSIVE_FLEETS`), documented as an assumption; `CATALOG_MANEUVERABLE_IDS` still adds others.
- **Physics PHYS-2 / PHYS-7: wiring** — done. Screening calls `maneuver.plan_for_detail(..., encounter=...)`; the negotiation router calls `maneuver.options_for()` for each side with Screening's encounter; cascade calls `simulate(request, catalog, environment=...)` with a per-sync cached environment.
- **AI: how the module plugs in / ask context** — done. `negotiate(detail, None, None, {"a": [...], "b": [...]})`; `ask_stream(question, {"conjunctions", "catalogMeta"})`; detail `brief` = `generate_brief(detail)`.
- **AI: operator data** — not available publicly; the AI's labelled profiles are used.
- **Screening: watch-list and Pc** — Lead changes in `screening.py`: targets come from `app.data.watchlist` (ISS + closest SOCRATES cross-operator maneuverable pair); Pc defaults to the maximum-probability bound (`SCREENING_PC_MODEL=max`) because GP data has no covariance; built details are cached 15 min.

### Open: Physics — post-burn Pc under the max-probability model
- From: Lead  To: Physics
- `newPc` for burns uses the (diluted) covariance at TCA held fixed, while "No action" shows the maximum-probability bound. Please confirm this is acceptable, or compute `newPc` with the same max-probability rule (it needs far larger separations to reach 1e-7).
- Status: open
