# Physics analysis: avoidance maneuvers and cascade simulation

Owner: Physics agent (Claude #2), branch `be-physics`.
Files: `backend/app/physics/maneuver.py`, `backend/app/physics/cascade.py`, `backend/tests/physics/`.

Source of truth for the contract: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`,
`frontend/src/api/handlers.ts` and `frontend/src/api/mockData.ts` (commit `019aa51`).

## 1. Repo state at analysis time

- `main` contains only `frontend/`, `README.md`, `TEAMMATE_HANDOFF.md` and `.gitignore`. There is no
  `AGENTS.md`/`CLAUDE.md` and no backend skeleton yet.
- **Assumption:** the backend lives in `backend/` with the package at `backend/app/`. If the Lead uses a
  different root, the files can be moved with `git mv` and nothing else changes.
- Frontend environment variables (`frontend/.env.example`): `VITE_USE_MOCKS=true` (any value except
  `false` keeps MSW mocks on) and `VITE_API_BASE_URL=` (empty means the same origin; a trailing `/` is
  stripped).

## 2. All endpoints the frontend calls

| Method | Path | Request | Response | Transport | Owner |
|---|---|---|---|---|---|
| GET | `/api/catalog` | none | `CatalogObject[]` | JSON | Data |
| GET | `/api/catalog/meta` | none | `CatalogMeta` | JSON | Data |
| GET | `/api/conjunctions?days=7&minPc=1e-6` | query: `days` (0–7), `minPc` | `Conjunction[]` (each item is a full `ConjunctionDetail` in the mock) | JSON | Screening |
| GET | `/api/conjunctions/:id` | path `id` | `ConjunctionDetail` or 404 `{message}` | JSON | Screening + **Physics (`options`, `afterSeries`)** + AI (`brief`) |
| POST | `/api/negotiations` | `{ conjunctionId }` | 201 `{ negotiationId }`; 404 unknown; 422 when either object is not maneuverable | JSON | AI |
| GET | `/api/negotiations/:id/stream` | none | `NegotiationEvent` frames, then `data: [DONE]` | SSE | AI (uses **Physics** options) |
| POST | `/api/cascade` | `CascadeRequest` | `CascadeResult`; 400 bad input; 404 unknown object | JSON | **Physics** (router: Lead) |
| POST | `/api/ask` | `{ question }` | token frames (`{type:'token',text}`), then `[DONE]`; 400 when empty | SSE | AI |

Errors: the client reads `body.message ?? body.detail`, so a FastAPI `HTTPException(detail=...)` works.
Units (frontend README): ISO 8601 UTC times; metres for miss distances; km for positions and ranges;
km/s for relative speed; m/s for Δv; kg for propellant.

## 3. Shapes I produce (copied from `types.ts`)

### 3.1 Maneuver options: `ConjunctionDetail.options` and `ConjunctionDetail.afterSeries`

```ts
export interface ManeuverOption {
  id: string;
  label: string;
  direction: 'prograde' | 'retrograde' | 'radial' | 'normal' | 'none';
  dvMs: number;
  burnAt: string | null;
  newMissM: number;
  newPc: number;
  propellantKg: number;
  recommended: boolean;
}
export interface ConjunctionDetail extends Conjunction {
  rangeSeries: { tSec: number; rangeKm: number }[];
  afterSeries?: { tSec: number; rangeKm: number }[];
  covariance: { sigmaMajorM: number; sigmaMinorM: number; angleDeg: number };
  hardBodyRadiusM: number;
  options: ManeuverOption[];
  brief: string;
}
```

Mock values (ISS × COSMOS 1408 DEB, `iss-cosmos`, miss 412 m, Pc 3.1e-4, 14.2 km/s):

| id | label | direction | dvMs | burnAt | newMissM | newPc | propellantKg | recommended |
|---|---|---|---|---|---|---|---|---|
| `option-a` | `A` | prograde | 0.42 | TCA − 6 h | 4200 | 2.3e-8 | 0.18 | true |
| `option-b` | `B` | normal | 0.67 | TCA − 4 h | 6800 | 8.1e-10 | 0.29 | false |
| `no-action` | `No action` | none | 0 | null | = missDistanceM | = pc | 0 | false |

Mock `covariance` is `{186, 74, 32°}`, HBR is 58 m (ISS) or 8 m, and `rangeSeries` has 81 points at
`tSec = −60 … +60` in steps of 1.5 s.

How the UI uses these fields:

- **ConjunctionScreen**: lists every option (Δv to 2 dp, `formatDistance(newMissM)`, propellant to 2 dp,
  a "Recommended" chip). The detail line shows `burnAt` (formatted UTC) and `formatProbability(newPc)`.
  The range chart draws `afterSeries` **only for the recommended option**. For other options it draws
  `hypot(t·relSpeed, newMissM/1000)`. The burn preview runs for any option except `direction === 'none'`.
- **AlertScreen** (phone): `options.find(recommended)`. A `none` option shows "Maintain the current
  trajectory." If nothing is recommended, it shows "No recommended burn was returned."
- **NegotiatorScreen**: shows the agreement's `maneuver` (`dvMs`, `direction`, `newMissM`, `propellantKg`).
- The **EncounterPlane** plots the covariance ellipse with **R horizontally and N vertically**. It is centred
  on `(rtnM.r, rtnM.n)` and rotated by `angleDeg` counter-clockwise from +R. So the contract's covariance
  is a 2-D ellipse in the encounter plane, with axes close to R and N.

### 3.2 Cascade: `POST /api/cascade`

```ts
export interface CascadeRequest {
  noradId: number;
  event: 'collision' | 'explosion';
  years: number;
  includeLaunches: boolean;
}
export interface CascadeResult {
  parent: ObjectRef & { omm: Record<string, string | number> };
  fragmentCount: number;
  spreadDvMs: { mean: number; sd: number };
  seed: number;
  years: { year: number; trackedTotal: number; baselineTotal: number;
           extraConjunctionsPct: number; satellitesAtRisk: number }[];
  secondaryCollisions: { year: number; latDeg: number; lonDeg: number; altKm: number; fragments: number }[];
}
```

Mock behaviour (`getMockCascade`):

- `years` is clamped to 1–25 and rounded. `years[]` has `years + 1` entries (year 0 … N).
- `fragmentCount` is 12784 for a collision and 4260 for an explosion. `spreadDvMs` is `{85, 38}` for a
  collision and `{32, 15}` for an explosion. `seed = 90421 + noradId`.
- `baselineTotal = 33482 + 1250·year` with launches, or `33482 − 42·year` without.
- `secondaryCollisions` contains only events with `year ≤ horizon`. The mock has events at 8.4 y / 825 km
  and 17.2 y / 910 km.
- The mock tests require `trackedTotal > baselineTotal`, and the no-launch baseline must be below the
  launch baseline.

How the UI uses these fields:

- CascadeScreen picks parents by **name**: `SL-16 R/B` (default), `FENGYUN 1C DEB`, `IRIDIUM 33 DEB`.
  The real catalog must contain these exact names.
- It shows "new fragments > 10 cm" (= `fragmentCount`). The current (nearest-year) values feed
  "Satellites at higher risk", "Extra close approaches +x %" and the secondary-event count.
- The chart plots `trackedTotal` against `baselineTotal`, with dots for secondary events.
- The 3-D scene (`DebrisCascade.tsx` + `cascade.vert.glsl`) uses only `parent.omm` (MEAN_MOTION,
  MEAN_ANOMALY, ARG_OF_PERICENTER, INCLINATION, RA_OF_ASC_NODE), `fragmentCount` (capped at 18 000
  points), `seed`, and `spreadDvMs.sd` (kick scale = `gauss · sd / 100`). Secondary events need `latDeg`,
  `lonDeg`, `altKm` and `fragments` (capped at 2000 points).

## 4. Physics plan

### 4.1 `maneuver.py`

**Input:** an `Encounter` holding the primary and secondary state vectors at TCA (same inertial frame;
TEME from SGP4 is fine), the combined covariance in contract form (`sigmaMajorM`, `sigmaMinorM`,
`angleDeg`), HBR, TCA, and the `tSec` grid of `rangeSeries`.

1. **Encounter frame:** x̂ = the mover's radial direction projected perpendicular to v_rel; ŷ = x̂ × v̂_rel.
   This matches the UI's R-horizontal / N-vertical encounter-plane plot.
2. **Pc:** 2-D Gaussian integrated over the HBR disk (Foster/Chan short-encounter assumption). The integral
   is reduced to 1-D in the covariance principal frame with exact `erfc` (no SciPy, keeps Lambda small).
   Exposed as `collision_probability()` so Screening can use the same formula.
3. **Burn effect:** Clohessy–Wiltshire impulsive response of the mover, from the burn at `TCA − lead` to
   TCA. The new relative position is r_rel ∓ δ, and the new miss is its component perpendicular to
   v_rel. The test checks CW against numerical two-body integration.
4. **Search:** for each direction (prograde, retrograde, ±radial, ±normal), try burn leads on a
   quarter-orbit grid near a 6 h nominal lead. Bound it by `now + 2 h` (commanding margin) and a 24 h
   maximum. Find the smallest Δv ≤ 5 m/s that reaches **Pc ≤ 1e-7 and miss ≥ 1 km** (geometric scan,
   then bisection).
5. **Options:** the cheapest three directions become A/B/C, sorted by Δv, plus `no-action`. `recommended`
   = option A when the current Pc ≥ 1e-4, otherwise `no-action`. All thresholds are parameters.
6. **Propellant:** Tsiolkovsky, with an assumed mass/Isp table (ISS ≈ 420 t at 300 s; Starlink/OneWeb
   electric propulsion; default 500 kg at 220 s hydrazine). Every value is commented as an assumption.
7. **afterSeries:** linear relative motion `|r_rel' + v_rel·t|` on the same `tSec` grid as `rangeSeries`.
8. The mover can be the primary or the secondary, so the AI negotiator can cost a burn for each operator.

### 4.2 `cascade.py`

1. **Breakup:** NASA Standard Breakup Model (Johnson et al. 2001) for fragments with L_c ≥ 10 cm. Count:
   explosion `6·S·Lc^-1.6`; collision `0.1·M^0.75·Lc^-1.71`. Sizes are drawn from the same power law,
   A/M from the NSBM bimodal distributions (rocket body vs spacecraft), and Δv from the NSBM log-normal
   with isotropic directions.
2. **Collision scenario:** the 40 J/g catastrophic test at 10 km/s. An intact parent is struck by a 10 kg
   fragment. A debris parent strikes an 800 kg intact payload. Parent masses come from a documented table.
3. **Orbits:** each kicked state is converted to (a, e) and perigee/apogee. Unbound or perigee < 100 km
   means immediate re-entry.
4. **Decay:** drag with the Vallado exponential atmosphere and King-Hele perigee-fixed apogee decay, in
   10-day steps. B = Cd·A/M with Cd = 2.2 for fragments. Catalog objects use B derived from `BSTAR`.
5. **Environment:** spatial density per altitude shell from time-weighted Keplerian residence. Fragments
   and catalog objects are both binned this way.
   - `extraConjunctionsPct` = Σ over active payloads of fragment density / baseline density (same v_rel
     and cross-section assumed).
   - `satellitesAtRisk` = active payloads whose local conjunction rate rises ≥ 10 %.
6. **Secondary collisions:** kinetic-gas rate ρ_frag·ρ_intact·σ·v_rel·V per shell (σ = 10 m²,
   v_rel = 10 km/s). An event is placed where the expected cumulative count crosses each integer; the
   shell with the largest contribution sets `altKm`, and seeded lat/lon are bounded by the parent
   inclination. Event fragments are the NSBM expectation for the colliding mass, and they feed back into
   the density (the cascade).
7. **Baseline:** catalog survivors under the same decay model. With `includeLaunches`, add a constant
   2 500 objects/yr. That figure is an assumption tied to recent tracked-catalog growth.
8. `spreadDvMs` = mean and standard deviation of the sampled Δv magnitudes. `seed` is deterministic per
   (noradId, event), so identical requests return identical results (cacheable).

## 5. Dependencies on other agents

| Need | From | Detail |
|---|---|---|
| Backend root and `app/models.py` Pydantic models | Lead | I return plain `dict`s with the exact camelCase keys above, ready for `Model.model_validate`. |
| Router wiring | Lead | `POST /api/cascade` calls `simulate_cascade(parent, catalog, …)`. `GET /api/conjunctions/:id` adds `plan_maneuvers(...).to_contract()`. |
| States at TCA, covariance, HBR, `rangeSeries` grid | Screening | Needs r/v of both objects at TCA in one inertial frame (km, km/s), the combined covariance in the encounter plane with angle from the radial axis, and HBR (m). Logged in `docs/CONTRACT_REQUESTS.md`. |
| Catalog objects (`noradId`, `name`, `type`, `active`, `omm`) | Data | `omm` needs MEAN_MOTION, ECCENTRICITY, INCLINATION, RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, BSTAR. Cascade picker needs the exact names `SL-16 R/B`, `FENGYUN 1C DEB`, `IRIDIUM 33 DEB`. |
| Calling the planner per operator | AI | `plan_maneuvers(encounter, mover="primary"/"secondary")` gives each agent its own costed options. |

## 6. Open questions

1. **Backend root:** is it `backend/app/…`? (Assumed above.)
2. **Covariance:** neither OMM nor GP data carries covariance. Screening has to assume one (for example,
   growth with element age). We need one shared definition so Pc in the list and `newPc` in the options
   agree. I propose Screening calls my `collision_probability()`.
3. **Cascade numbers:** NSBM numbers differ from the mock. An SL-16 collision gives ≈ 4 700 fragments
   (mock 12 784). An explosion gives ≈ 240 (mock 4 260). Real Δv spread is ≈ 100–200 m/s (mock sd 38),
   and the shader multiplies by `sd/100`, so the cloud will look wider. The frontend is out of scope for
   me; flagged for the Lead.
4. **Propellant:** real ISS propellant for 0.4 m/s is about 60 kg (mock 0.18 kg). We report real figures.
5. **Recommendation threshold:** the default is 1e-4 (common NASA CARA/ESA practice), so
   `starlink-oneweb` (Pc 8.7e-5 in the mock) would default to "no action" while still listing burns.
   Should the operator-specific threshold come from the AI or the request?
6. **Cascade latency:** decaying about 30 000 catalog objects plus fragments takes about 1–2 s. The
   baseline survival is a separate cached function keyed on the catalog sync time.
