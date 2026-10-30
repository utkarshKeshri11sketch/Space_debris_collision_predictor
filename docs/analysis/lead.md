# Lead analysis — API contract

Source of truth: `frontend/src/api/types.ts`, `client.ts`, `handlers.ts`, `mockData.ts`.

## Env vars (frontend)

- `VITE_USE_MOCKS` — mocks run unless it is exactly `false`.
- `VITE_API_BASE_URL` — prefix for every `/api/...` path (trailing slash stripped). Empty = same origin.

## Endpoints

| Method | Path | Params / body | Response | Kind |
| --- | --- | --- | --- | --- |
| GET | `/api/catalog` | — | `CatalogObject[]` (33,482 in mocks) | JSON |
| GET | `/api/catalog/meta` | — | `CatalogMeta` | JSON |
| GET | `/api/conjunctions` | `days` (0–7, frontend sends 7), `minPc` (sends `1e-6`) | `Conjunction[]` | JSON |
| GET | `/api/conjunctions/{id}` | — | `ConjunctionDetail`; 404 `{message}` | JSON |
| POST | `/api/negotiations` | `{conjunctionId}` | 201 `{negotiationId}`; 404; 422 if either object can't maneuver | JSON |
| GET | `/api/negotiations/{id}/stream` | `Accept: text/event-stream` | `NegotiationEvent` per `data:` line, then `[DONE]`; 404 if unknown | SSE |
| POST | `/api/cascade` | `CascadeRequest` | `CascadeResult`; 400 bad input; 404 unknown object | JSON |
| POST | `/api/ask` | `{question}` | `{"type":"token","text"}` per `data:` line, then `[DONE]`; 400 empty | SSE |

Error bodies: the client shows `body.message ?? body.detail`, so always send `{"message": "..."}`.
SSE parser accepts `\n\n` or `\r\n\r\n` separators and multi-line `data:`; `[DONE]` ends the stream.
`/api/ask` also accepts plain JSON strings or `{"token": ...}`; in-stream `{"type":"error","message"}` shows an error.

## Shapes (copied from types.ts)

```ts
type ObjectType = 'PAYLOAD' | 'DEBRIS' | 'ROCKET_BODY' | 'UNKNOWN';
type Risk = 'critical' | 'high' | 'watch';
interface CatalogObject { noradId: number; name: string; type: ObjectType; active: boolean; maneuverable: boolean; omm: Record<string, string | number>; }
interface ObjectRef { noradId: number; name: string; type: ObjectType; maneuverable: boolean; }
interface Conjunction { id: string; primary: ObjectRef; secondary: ObjectRef; tca: string; missDistanceM: number; rtnM: { r: number; t: number; n: number }; relSpeedKms: number; pc: number; risk: Risk; }
interface ManeuverOption { id: string; label: string; direction: 'prograde'|'retrograde'|'radial'|'normal'|'none'; dvMs: number; burnAt: string | null; newMissM: number; newPc: number; propellantKg: number; recommended: boolean; }
interface ConjunctionDetail extends Conjunction { rangeSeries: { tSec: number; rangeKm: number }[]; afterSeries?: { tSec: number; rangeKm: number }[]; covariance: { sigmaMajorM: number; sigmaMinorM: number; angleDeg: number }; hardBodyRadiusM: number; options: ManeuverOption[]; brief: string; }
type NegotiationEvent =
  | { type: 'message'; speaker: 'mediator' | 'agentA' | 'agentB'; round: number; text: string }
  | { type: 'scores'; criteria: { name: string; weight: number; a: number; b: number }[] }
  | { type: 'agreement'; mover: ObjectRef; maneuver: ManeuverOption; signedBy: string[] }
  | { type: 'error'; message: string };
interface CascadeResult { parent: ObjectRef & { omm: Record<string, string | number> }; fragmentCount: number; spreadDvMs: { mean: number; sd: number }; seed: number; years: { year: number; trackedTotal: number; baselineTotal: number; extraConjunctionsPct: number; satellitesAtRisk: number }[]; secondaryCollisions: { year: number; latDeg: number; lonDeg: number; altKm: number; fragments: number }[]; }
interface CascadeRequest { noradId: number; event: 'collision' | 'explosion'; years: number; includeLaunches: boolean; }
interface CatalogMeta { objectCount: number; byType: Record<ObjectType, number>; syncedAt: string; source: string; }
```

## Sample values (mocks)

- Conjunction ids: `iss-cosmos` (critical, 412 m, Pc 3.1e-4, 14.2 km/s, TCA +18 h), `starlink-oneweb` (high,
  690 m, 8.7e-5; only negotiable pair), plus five watch events.
- `rangeSeries`: 81 points, `tSec` −60…+60 in 1.5 s steps. `hardBodyRadiusM` 58 for ISS, otherwise 8.
- Options: A prograde 0.42 m/s (recommended, 4.2 km, Pc 2.3e-8), B normal 0.67 m/s, plus `no-action`.
- Cascade years clamp to 1–25, `years` has `years + 1` rows starting at 0. SL-16 R/B is 22285.
- Mock negotiation criteria (fuel 0.3, mission 0.3, readiness 0.2, risk 0.2) **differ from the brief's
  weights** (propellant 35%, cost 25%, mission 20%, Δv 20%). The UI renders whatever `criteria` it gets,
  so the AI agent should send the brief's four criteria.

## Decisions

- `negotiationId` = `<uuid>~<conjunctionId>` so the stream works across stateless Lambda containers.
- Validation errors return 400 with `{message}` (matches the mock's 400 for bad cascade input).
- The list endpoint trims `ConjunctionDetail` to `Conjunction` via `response_model`.

## Open questions

- SSE on Lambda: API Gateway REST buffers responses. Use a Lambda Function URL with response streaming,
  or accept that events arrive all at once. Decide at deploy time.
- `/api/catalog` is ~10 MB of JSON for 33k objects; may exceed the 6 MB Lambda response limit → gzip or S3 redirect.
