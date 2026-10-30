# Physics analysis: avoidance maneuvers and cascade simulation

Owner: Physics agent (Claude #2), branch `be-physics`.
Files: `app/physics/maneuver.py`, `app/physics/cascade.py`, `tests/physics/` (repo root, same layout as
`app/ai/` on `be-ai`).

Source of truth for the contract: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`,
`frontend/src/api/handlers.ts` and `frontend/src/api/mockData.ts` (commit `019aa51`).

## 1. Repo state at analysis time

- `main` contains only `frontend/`, `README.md`, `TEAMMATE_HANDOFF.md` and `.gitignore`. There is no
  `AGENTS.md`/`CLAUDE.md` and no backend skeleton yet.
- **Update:** `be-ai` put its package at the repo root (`app/ai/`), so physics moved to `app/physics/`
  as well. It was first committed under `backend/`.
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
4. **Search:** along-track burns only (prograde, retrograde), as the role brief asks and as LEO
   operators normally fly. Burn leads lie on a quarter-orbit grid near three lead profiles: nominal
   6 h, early 18 h, late 2 h. The window is bounded by `now + 2 h` (commanding margin) and a 24 h
   maximum. The search finds the smallest Δv ≤ 5 m/s that reaches **Pc ≤ 1e-7 and miss ≥ 1 km**
   (geometric scan, then bisection), rounded up to 0.01 m/s.
5. **Options:**
   - A: the cheaper direction at the nominal lead.
   - B: the other direction at the nominal lead.
   - C: A's direction, early (least Δv, least mature prediction).
   - D: A's direction, late (most Δv).
   - Plus `no-action`.
   `recommended` = A when the current Pc ≥ 1e-4, otherwise `no-action`. All thresholds are parameters.
6. **Propellant:** Tsiolkovsky, with an assumed mass/Isp table matching `app/ai/profiles.py` (ISS 420 t
   at 300 s; Starlink 800 kg at 1500 s; OneWeb 150 kg at 1600 s; EO satellites 1 t at 220 s; default
   500 kg at 220 s). Every value is commented as an assumption. Reported to 4 significant figures.
7. **afterSeries:** linear relative motion `|r_rel' + v_rel·t|` on the same `tSec` grid as `rangeSeries`.
8. The mover can be the primary or the secondary, so the AI negotiator can cost a burn for each operator.
9. **Entry points:**
   - `options(detail)` and `options_for(detail, mover_norad_id)` take a contract `ConjunctionDetail`.
     Without screening's state vectors, `encounter_from_detail` rebuilds the geometry from `rtnM` and
     `relSpeedKms`. It assumes both orbits are near-circular and meet at one altitude, so v_rel is
     horizontal and the crossing angle comes from |v_rel| = 2v·sin(θ/2).
   - `plan_maneuvers(encounter)` uses exact states when Screening supplies them.

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
7. **J2 nodal precession:** every fragment carries its inclination, taken from the kicked angular
   momentum. Its node drifts at dΩ/dt = −1.5·n·J2·(R_E/p)²·cos i, integrated with decay, so sinking
   fragments speed up. The spread of the central 90 % of nodes relative to the parent's own node
   shows the plane fanning into a ring. `simulate(scenario).diagnostics` reports
   `nodalSpreadDeg[year]` and `ringClosedYear`. The shell-density statistics are node-free: any
   orbit at that altitude still crosses the debris plane twice per revolution, so the time-averaged
   rates are unchanged.
8. **Baseline:** catalog survivors under the same decay model. With `includeLaunches`, add a constant
   2 500 objects/yr. That figure is an assumption tied to recent tracked-catalog growth.
9. `spreadDvMs` = mean and standard deviation of the sampled Δv magnitudes. `seed` is deterministic per
   (noradId, event), so identical requests return identical results (cacheable).

### 4.3 What the build changed (implemented and tested)

- **Already-safe events:** when the unchanged trajectory already meets the targets, burns are costed
  to double the miss distance. Without this, every burn comes out as 0 m/s.
- **Mock fixtures are not self-consistent:** a 412 m miss with the mock covariance (186/74 m, HBR 58 m)
  gives Pc ≈ 3e-7, not 3.1e-4. Our Pc follows the geometry. For a "critical" demo the screening data
  needs a tighter miss or a larger covariance.
- **Typical numbers** (ISS × debris, mock-like detail, 150 m miss):
  - A: 0.03 m/s prograde about 6 h out (about 4 kg of ISS propellant)
  - C: 0.02 m/s about 16 h out
  - D: 0.07 m/s about 2.7 h out
  Along-track burns are cheap because the drift grows as about 3·Δv·t.
- **J2 ring formation** (SL-16, 71°): the parent's node regresses at −2.1°/day. The fan closes into a
  full ring within about 1 year after a collision (kicks of hundreds of m/s) and about 3 years after an
  explosion. A FENGYUN fragment collision (98.7°) closes in about 4 years.
- **`spreadDvMs`** describes the fragments that stay in orbit (the cloud the globe draws). For an SL-16
  collision that is mean ≈ 357 m/s, sd ≈ 583 m/s. Including NSBM's km/s tail, which escapes or
  re-enters at once, would give sd ≈ 2 km/s.
- **Shells** are 20 km to 2000 km, then 250 km.
- **Timing** on the 33 482-object synthetic catalog (local laptop): `build_environment` about 1.2 s
  (cache it), SL-16 collision about 0.6 s, explosion about 0.1 s.
- **SL-16 collision, 25 y with launches:** 4 703 fragments, 3 secondary collisions (≈ 135–150 fragments
  each, ≈ 835 km), and about 2 600 active satellites at higher risk in year 0.
- **Dependencies:** `numpy` only. No SciPy and no `sgp4` inside `app/physics/maneuver.py` or
  `cascade.py`.
- **Tests:** `tests/physics/` (32 tests, about 9 s), run with `pytest tests/physics`. They check closed-form
  Pc, CW against two-body RK4, contract shapes, determinism, NSBM yields, decay lifetimes, J2 rates
  (sun-synchronous ≈ 0.986°/day) and ring formation.

## 5. Dependencies on other agents

| Need | From | Detail |
|---|---|---|
| Backend root and `app/models.py` Pydantic models | Lead | I return plain `dict`s with the exact camelCase keys above, ready for `Model.model_validate`. |
| Router wiring | Lead | `POST /api/cascade` calls `simulate(request, catalog, environment=env).result`. `GET /api/conjunctions/:id` adds `plan_for_detail(detail).to_contract()`. See PHYS-2. |
| States at TCA, covariance, HBR, `rangeSeries` grid | Screening (optional) | Improves geometry; not blocking, because the detail-only fallback exists. Needs r/v of both objects at TCA in one inertial frame (km, km/s), the combined covariance in the encounter plane with angle from the radial axis, and HBR (m). Logged in `docs/CONTRACT_REQUESTS.md`. |
| Catalog objects (`noradId`, `name`, `type`, `active`, `omm`) | Data | `omm` needs MEAN_MOTION, ECCENTRICITY, INCLINATION, RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, BSTAR. Cascade picker needs the exact names `SL-16 R/B`, `FENGYUN 1C DEB`, `IRIDIUM 33 DEB`. |
| Calling the planner per operator | AI | `options_for(detail, mover_norad_id)` answers be-ai's request (PHYS-6). |

## 6. Open questions

1. **Backend root:** resolved, it is the repo root (`app/`), following `be-ai`.
2. **Covariance:** neither OMM nor GP data carries covariance. Screening has to assume one (for example,
   growth with element age). We need one shared definition so Pc in the list and `newPc` in the options
   agree. I propose Screening calls my `collision_probability()`.
3. **Cascade numbers:** NSBM numbers differ from the mock. An SL-16 collision gives ≈ 4 700 fragments
   (mock 12 784). An explosion gives ≈ 240 (mock 4 260). The orbiting-fragment Δv spread is
   ≈ {mean 357, sd 583} m/s (mock {85, 38}). The shader multiplies by `sd/100`, so the cloud will look
   much wider. The frontend is out of scope for me; flagged for the Lead.
4. **Propellant:** real ISS propellant for 0.4 m/s is about 60 kg (mock 0.18 kg). We report real figures.
5. **Recommendation threshold:** the default is 1e-4 (common NASA CARA/ESA practice), so
   `starlink-oneweb` (Pc 8.7e-5 in the mock) would default to "no action" while still listing burns.
   Should the operator-specific threshold come from the AI or the request?
6. **Cascade latency:** `build_environment(catalog)` (catalog decay and shell densities) takes about
   1.2 s and does not depend on the request. The Lead should cache it per catalog sync. Each cascade
   then takes 0.1–0.6 s.
