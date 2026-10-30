# Data pipeline analysis

Inspected base commit 67bdfb3bd41652d8b999ba882888f8e865362e9b on 2026-10-30 before implementation.

## Repository

- Root: AGENTS.md, CLAUDE.md, README.md, TEAMMATE_HANDOFF.md.
- frontend/src/api/: client.ts, types.ts, handlers.ts (MSW), mockData.ts, mocks.ts.
- frontend/src/app/App.tsx: catalog search, counts, filters and sync time.
- frontend/src/features/mission-control/ObjectInspector.tsx: name, NORAD ID, type, active/maneuverable, mean altitude, orbital elements.
- frontend/src/sim/: omm.ts validates OMM, propagation.worker.ts uses satellite.js for SGP4.
- backend/app/: models.py (Lead owned), routers/, data/catalog.py (our stub), physics/, ai/, mock_data.py.
- backend/tests/test_api.py and scripts/check_contract.py provide shell checks.
- docs/analysis/lead.md and docs/CONTRACT_REQUESTS.md contain team coordination.

## Frontend client and environment

All API calls originate in frontend/src/api/client.ts. Types are in types.ts; MSW handlers in handlers.ts; generated synthetic data in mockData.ts. VITE_USE_MOCKS defaults to enabled unless exactly false. VITE_API_BASE_URL defaults to the same origin and removes a trailing slash. frontend/.env.example sets VITE_USE_MOCKS=true and an empty base URL.

## Every frontend endpoint

1. GET /api/catalog: no query/body; JSON CatalogObject[]. Data owns implementation through load_catalog().
2. GET /api/catalog/meta: no query/body; JSON CatalogMeta. Data owns catalog_meta().
3. GET /api/conjunctions?days=7&minPc=1e-6: no body; JSON Conjunction[]. Screening owns it. MSW clamps days to [0,7], then filters Pc and TCA.
4. GET /api/conjunctions/{encodedId}: no query/body; JSON ConjunctionDetail; 404 message when absent. Screening, Physics and AI own it.
5. POST /api/negotiations: JSON {conjunctionId:string}; 201 JSON {negotiationId:string}; 404 unknown conjunction; 422 if either object cannot maneuver. Lead/AI own it.
6. GET /api/negotiations/{encodedId}/stream: no query/body; Accept text/event-stream; SSE NegotiationEvent; 404 expired session. AI owns it.
7. POST /api/cascade: JSON CascadeRequest; JSON CascadeResult; 400 invalid event/number fields and 404 unknown object. Physics owns it.
8. POST /api/ask: JSON {question:string}; Accept text/event-stream; SSE {type:"token",text:string}, 400 empty question. Client also accepts string/token fields and error events. AI owns it.

Both streams use data: <JSON> followed by two newlines, ending with data: [DONE]. No data endpoint streams. GET /api/health is backend-only, not called by this frontend. Errors are JSON {message:string}, with detail:string accepted by the client too.

## Exact TypeScript contract (copied verbatim)

```ts
export type ObjectType = 'PAYLOAD' | 'DEBRIS' | 'ROCKET_BODY' | 'UNKNOWN';
export type Risk = 'critical' | 'high' | 'watch';
export interface CatalogObject {
  noradId: number;
  name: string;
  type: ObjectType;
  active: boolean;
  maneuverable: boolean;
  omm: Record<string, string | number>;
}
export interface ObjectRef {
  noradId: number;
  name: string;
  type: ObjectType;
  maneuverable: boolean;
}
export interface Conjunction {
  id: string;
  primary: ObjectRef;
  secondary: ObjectRef;
  tca: string;
  missDistanceM: number;
  rtnM: { r: number; t: number; n: number };
  relSpeedKms: number;
  pc: number;
  risk: Risk;
}
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
export type NegotiationEvent =
  | { type: 'message'; speaker: 'mediator' | 'agentA' | 'agentB'; round: number; text: string }
  | { type: 'scores'; criteria: { name: string; weight: number; a: number; b: number }[] }
  | { type: 'agreement'; mover: ObjectRef; maneuver: ManeuverOption; signedBy: string[] }
  | { type: 'error'; message: string };
export interface CascadeResult {
  parent: ObjectRef & { omm: Record<string, string | number> };
  fragmentCount: number;
  spreadDvMs: { mean: number; sd: number };
  seed: number;
  years: {
    year: number;
    trackedTotal: number;
    baselineTotal: number;
    extraConjunctionsPct: number;
    satellitesAtRisk: number;
  }[];
  secondaryCollisions: {
    year: number;
    latDeg: number;
    lonDeg: number;
    altKm: number;
    fragments: number;
  }[];
}
export interface CascadeRequest {
  noradId: number;
  event: 'collision' | 'explosion';
  years: number;
  includeLaunches: boolean;
}
export interface CatalogMeta {
  objectCount: number;
  byType: Record<ObjectType, number>;
  syncedAt: string;
  source: string;
}
```

## Mock examples and UI implications

Mock catalog contains 33,482 synthetic records. Named examples: ISS (ZARYA), 25544, PAYLOAD, active=true, maneuverable=true, nominal altitude 418 km; COSMOS 1408 DEB, 50870, DEBRIS, false/false, 421 km; SL-16 R/B, 22285, ROCKET_BODY, false/false, 840 km. These are mock identities and orbits, not verified real associations. Mock OMM uses eccentricity 0.0004, BSTAR 0.00001 and a Date.now() epoch. Metadata includes all four byType keys, objectCount=33482 and source="Synthetic OMM catalog · sample data".

ObjectInspector computes mean altitude from MEAN_MOTION using mu=398600.4418 km^3/s^2 and radius=6378.137 km. It does not consume owner/country or an altitude field. The globe consumes OMM and filters on type; search uses name/ID; active and maneuverable are distinct required booleans. Return exactly the six catalog fields; keep Satrec and metadata internal. Never replace old element epochs or claim a snapshot was synchronized now.

## Build plan and agent interfaces

- Replace catalog.py stub, preserving load_catalog()->list[CatalogObject] and catalog_meta()->CatalogMeta. Both read caches only and never contact CelesTrak.
- Expose load_orbit_catalog() as a NORAD-keyed internal mapping containing the API record, original OMM, native Satrec, optional owner/country and mean altitude km. Screening and Physics can use this.
- Use sgp4.omm.initialize (WGS72 default), normalizing UTC epochs for that API and supporting six-digit IDs without TLE parsing. Reject malformed/nonfinite orbital fields.
- Explicit fetch_catalog() and EventBridge refresh_handler() fetch supported active, NAME=DEB and NAME=R/B OMM JSON feeds, deduplicate by newest epoch and join the authoritative SATCAT CSV for type/status/owner. Name matching is only a documented fallback. No documented all group is assumed. These feeds cover active payloads and named debris/rocket bodies; unknown and inactive payload coverage is incomplete.
- Persist atomically to local storage and S3 when configured. Use a local exclusive process lock plus a conditional S3 lease, durable attempt timestamps and a hard two-hour floor even after failures. Stop immediately on an upstream error; keep last-known-good data; respect Retry-After. One reserved-concurrency refresh Lambda every 6h is recommended.
- Ship a provenance-labeled real snapshot; never synthesize missing demo orbits. Test native OMM propagation, API shape, metadata, six-digit IDs, failure preservation, disk/S3 cooldown and concurrent refresh behavior.

## Dependencies and open questions

- Lead: deployment must point EventBridge at app.data.refresh.refresh_handler and permit S3 GetObject/PutObject. Lead owns requirements, root .env.example, routers and tests/test_api.py.
- Existing backend/.env.example CELESTRAK_URL points only to active; active-only overrides cannot supply debris. Data will document settings under app/data/.env.example and request Lead updates.
- Existing test_catalog_and_meta hard-codes synthetic mock_data.OBJECT_COUNT. Lead must update that assertion to the real snapshot count; we will not edit their test.
- GP OMM does not prove maneuverability. Default false unless explicitly configured/verified. Activity comes from SATCAT status or active feed membership. Operators must supply capability data before real negotiation.
- Need a documented bulk full public OMM source if inactive payloads and unclassified objects are required; do not advertise these three feeds as the entire public catalog.
- This machine blocks terminal GitHub/PyPI/CelesTrak downloads. Source files were restored through the GitHub connector, verified by Git object SHA; the upstream commit is preserved in a sparse shallow checkout. Large frontend media is excluded. Direct live CelesTrak and AWS verification may remain external checks.
