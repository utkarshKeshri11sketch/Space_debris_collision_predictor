# Analysis: AI area (`app/ai/`, branch `be-ai`)

Written after reading the repo as of `origin/main` (frontend only; no backend, no `AGENTS.md`/`CLAUDE.md`).
Sources: `frontend/src/api/{types,client,handlers,mockData}.ts`, `frontend/README.md`, `frontend/DECISIONS.md`,
`NegotiatorScreen.tsx`, `ConjunctionScreen.tsx`, `App.tsx` (SentinelBrief, command palette).

## 1. Repo layout

```text
frontend/   React + TS + Vite + three.js (done). API client in src/api/, MSW mocks in src/api/{handlers,mockData}.ts
app/ai/     this agent's package          tests/ai/   this agent's tests          docs/   CONTRACT_REQUESTS.md, analysis/
```

Env vars: `VITE_USE_MOCKS` (default true; `false` = real backend), `VITE_API_BASE_URL` (empty = same origin).
The client calls only `/api/...`, sends no auth, and supports `GET`/`POST` + `fetch` streaming.

## 2. All endpoints the frontend calls

| Method | Path | Request | Response | Type | Owner |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/catalog` | – | `CatalogObject[]` | JSON | Data |
| GET | `/api/catalog/meta` | – | `CatalogMeta` | JSON | Data |
| GET | `/api/conjunctions?days=7&minPc=1e-6` | query | `Conjunction[]` (mock returns details) | JSON | Screening / Lead |
| GET | `/api/conjunctions/:id` | – | `ConjunctionDetail` (**has `brief`**) | JSON | Screening / Lead (+AI brief) |
| POST | `/api/negotiations` | `{conjunctionId}` | `201 {negotiationId}`; 404 unknown; **422 if either object not maneuverable** | JSON | **AI** (+Lead router) |
| GET | `/api/negotiations/:id/stream` | – | `NegotiationEvent` frames, 404 `{message}` if expired | **SSE** | **AI** |
| POST | `/api/cascade` | `CascadeRequest` | `CascadeResult` | JSON | Physics |
| POST | `/api/ask` | `{question}` (400 `{message}` if blank) | answer tokens | **SSE** | **AI** |

Errors: non-2xx JSON with `message` (or `detail`) is shown to the user verbatim.

SSE framing (`client.ts`): `Content-Type: text/event-stream`, UTF-8 `data: <JSON>\n\n`, end with `data: [DONE]\n\n` or close.
Parser tolerates CRLF, comments, multi-line data. Mock paces events ~1.35 s (+0–0.4 s) apart; ask tokens 20 ms apart.
`ask` accepts per frame: a JSON string, `{type:"token",text}`, `{token}`, plain text, or `{type:"error",message}`.

## 3. Exact shapes I produce / consume (copied from `types.ts`)

```ts
export type NegotiationEvent =
  | { type: 'message'; speaker: 'mediator' | 'agentA' | 'agentB'; round: number; text: string }
  | { type: 'scores'; criteria: { name: string; weight: number; a: number; b: number }[] }
  | { type: 'agreement'; mover: ObjectRef; maneuver: ManeuverOption; signedBy: string[] }
  | { type: 'error'; message: string };
export interface ObjectRef { noradId: number; name: string; type: ObjectType; maneuverable: boolean }
export interface ManeuverOption {
  id: string; label: string; direction: 'prograde' | 'retrograde' | 'radial' | 'normal' | 'none';
  dvMs: number; burnAt: string | null; newMissM: number; newPc: number; propellantKg: number; recommended: boolean;
}
export interface ConjunctionDetail extends Conjunction {   // Conjunction: id, primary, secondary: ObjectRef, tca,
  rangeSeries; afterSeries?; covariance; hardBodyRadiusM;  //   missDistanceM, rtnM, relSpeedKms, pc, risk
  options: ManeuverOption[]; brief: string;                // <-- brief: plain string, AI-generated
}
```

Units: metres (miss), km/s (speed), m/s (Δv), kg (propellant), ISO-8601 UTC times, `pc` is a probability 0–1.

## 4. What the UI does with my output

* **Negotiator screen** (`NegotiatorScreen.tsx`): only starts if both objects `maneuverable`. Appends each `message` to a transcript
  labelled by `speaker` + `ROUND n`; shows `scores` as a weighted-criteria table and **computes the totals itself**
  (`Σ a·weight / Σ weight` per side), so `a` = suitability if agent A (**primary**) moves, `b` for B (secondary), 0–100 scale as in the mock.
  `agreement` renders "`mover.name` maneuvers", `maneuver.dvMs`/`direction`/`newMissM`/`propellantKg`, and `signedBy.join(' + ')`.
  `error` event or a stream that ends without agreement shows an error with Reconnect. A human override dialog exists; the stream
  itself is only a recommendation. Mock sequence: mediator r0, agentA r1, agentB r1, mediator r2, scores, agentA r3, agentB r3, agreement.
* **Sentinel brief** (`App.tsx` `SentinelBrief`): dashboard shows `useConjunction(topThreat.id).brief`, typewritten at ~5 chars/24 ms,
  so **briefs must be short plain text, no markdown**. `ConjunctionScreen` shows the same `data.brief` on the detail page.
* **Ask Sentinel** (command palette, Ctrl/⌘+K, Enter): appends tokens into one answer paragraph (`aria-live`); plain prose, no markdown.
  Mock topics: ISS safety, cascade/debris, negotiation, else the global brief. Questions are free text.
* **Phone alert / Cascade**: do not use AI endpoints.

Sample mock values to match: ISS×COSMOS 1408 DEB (412 m, Pc 3.1e-4, 14.2 km/s, option A 0.42 m/s prograde → 4.2 km, Pc 2.3e-8, 0.18 kg);
STARLINK-31502 × ONEWEB-0461 (690 m, Pc 8.7e-5, 12.8 km/s, both maneuverable); mock `sentinelBrief` text in `mockData.ts`.

## 5. Dependencies on other agents

| Need | From | Status / workaround |
| --- | --- | --- |
| `ConjunctionDetail` incl. `options` | Screening + Physics via Lead | I take it as a dict; fixtures in `tests/ai/conftest.py` mirror the mocks |
| Per-object `ManeuverOption` ("if THAT object moves") | Physics (`maneuver.py`) | Requested; fallback estimates the secondary's propellant from the primary's, disclosed in the mediator message |
| Router, SSE wrapper, negotiation-id→conjunction store, 404/422 checks, IAM, env | Lead | Glue documented in `app/ai/README.md` |
| Spacecraft propellant/mass/mission data | nobody (not in contract) | Illustrative profiles in `profiles.py`, labelled as assumptions |
| Conjunction list for Ask | Lead | `ask_stream(question, {"conjunctions": [...]})` |

## 6. Open questions

1. Lambda + API Gateway buffers responses: how will true SSE be delivered (Lambda response streaming / Function URL)? Lead decision.
2. Negotiation ids across Lambda cold starts: in-memory map may be lost between `POST` and `GET stream`.
3. Will `GET /api/conjunctions/:id` call the AI per request? Default is free templates; `AI_BRIEF_MODE=llm` enables the model with a content-hash cache.
4. Score criteria names differ from the mock (spec says reserve 35 / cost 25 / mission impact 20 / Δv 20); UI renders names generically — confirm no copy depends on the old names.
5. Bedrock model access/region and which model id to use for credits; default is a cheap Claude Haiku id, overridable via `BEDROCK_MODEL_ID`.
6. `Conjunction` list in the mock returns `ConjunctionDetail` objects; real `/api/conjunctions` may return lighter items — Ask works either way but is better with `options`.

## 7. Plan / status

Built and tested (37 tests, `python -m pytest tests/ai`): negotiator, deterministic scoring, grounding guard, brief, ask, provider chain
(Bedrock → Gemini → cache → templates). Remaining: wire into Lead's routers; try Bedrock live once credentials exist; tune prompts on
real output; pre-record the three demo scenarios into `AI_CACHE_DIR` as an offline safety net.
