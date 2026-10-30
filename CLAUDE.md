# OrbitSentinel — agent guide

Read this fully before writing code. `CLAUDE.md` is an identical copy.

## What we are building

OrbitSentinel is an AI-powered space-debris collision prediction and avoidance platform for the Anvathon
hackathon (AWS-sponsored). Pitch: **"Detection is solved, decisions aren't."** Free warnings exist, but
operators get raw numbers with no advice, and there are no rules for who moves when two active satellites
are on a collision course.

Features (frontend done in `frontend/`, running on mock data): 3D globe of the whole catalog, collision
screening, conjunction detail, avoidance options, AI Negotiator, Cascade simulator, Sentinel brief +
Ask Sentinel, phone alert view.

Demo scenarios: ISS (25544) × COSMOS 1408 DEB · STARLINK-31502 × ONEWEB-0461 negotiation · SL-16 R/B cascade.

Data: CelesTrak GP in **OMM** format (not TLE). Download at most once per 2 h, cache in S3 + local snapshot.
SOCRATES validates our conjunctions.

Stack: React + TS + Vite + three.js frontend. Backend: Python 3.11, FastAPI, Pydantic v2, sgp4 + numpy,
AWS Lambda (Mangum) + API Gateway, S3, EventBridge, Amazon Bedrock (Gemini/cached fallback). Free credits only.

## Ownership — one folder, one branch each

| Agent | Owns | Branch |
| --- | --- | --- |
| Lead (Claude #1) | `backend/app/main.py`, `backend/app/models.py`, `backend/app/routers/`, `backend/app/mock_data.py`, `backend/scripts/`, deploy, docs | `main` (integration) |
| Data (Codex #1) | `backend/app/data/` + `backend/tests/data/` | `be-data` |
| Screening (Codex #2) | `backend/app/physics/screening.py` + `backend/tests/screening/` | `be-screening` |
| Physics (Claude #2) | `backend/app/physics/maneuver.py`, `cascade.py` + `backend/tests/physics/` | `be-physics` |
| AI (Claude #3) | `backend/app/ai/` + `backend/tests/ai/` | `be-ai` |

## Golden rules

- **The frontend's types + mock handlers are the API contract** (`frontend/src/api/types.ts`,
  `handlers.ts`, `mockData.ts`). `backend/app/models.py` mirrors them exactly: camelCase field names,
  units, nesting, enums. Never change the frontend or `models.py` yourself.
- Need something from another agent or the contract? Add it to `docs/CONTRACT_REQUESTS.md`.
- Only edit files in your own folder (+ `backend/tests/<your_area>/`). Commit small, often, clear messages.
- Never invent physics numbers silently: document every assumption in code comments.
- No secrets in code; use env vars (`backend/.env.example`).

## How the shell works

Every endpoint already answers with the frontend's mock data. Routers call **stub functions** in your
folder; each stub currently delegates to `app/mock_data.py`. Your job: replace the stub body, keep the
signature and return type, and keep `scripts/check.sh` green.

| Endpoint | Router | Calls (owner) |
| --- | --- | --- |
| `GET /api/health` | `main.py` | — |
| `GET /api/catalog` → `CatalogObject[]` | `routers/catalog.py` | `data.catalog.load_catalog()` (Data) |
| `GET /api/catalog/meta` → `CatalogMeta` | `routers/catalog.py` | `data.catalog.catalog_meta()` (Data) |
| `GET /api/conjunctions?days=7&minPc=1e-6` → `Conjunction[]` | `routers/conjunctions.py` | `physics.screening.screen()` (Screening) |
| `GET /api/conjunctions/{id}` → `ConjunctionDetail` / 404 | `routers/conjunctions.py` | `physics.screening.get_conjunction()` (Screening), `options` from `physics.maneuver.options()` (Physics), `brief` (AI) |
| `POST /api/negotiations {conjunctionId}` → 201 `{negotiationId}` / 404 / 422 | `routers/negotiations.py` | — |
| `GET /api/negotiations/{id}/stream` → SSE `NegotiationEvent` | `routers/negotiations.py` | `ai.negotiator.negotiate()` (AI) |
| `POST /api/cascade CascadeRequest` → `CascadeResult` / 404 | `routers/cascade.py` | `physics.cascade.simulate()` (Physics) |
| `POST /api/ask {question}` → SSE `{"type":"token","text"}` / 400 | `routers/ask.py` | `ai.ask.ask()` (AI) |

SSE format: each event is `data: <json>\n\n`; the stream ends with `data: [DONE]\n\n`. Routers add the
framing — your generators just yield dicts (negotiator) or strings (ask). Errors: JSON `{"message": "..."}`
with a 4xx status, or an in-stream `{"type":"error","message":"..."}` event.

Negotiation weights for the mediator: propellant reserve 35%, maneuver cost 25%, mission impact 20%, Δv 20%.

## Run and test

```sh
cd backend
python -m pip install -r requirements.txt
cp .env.example .env              # optional
python -m uvicorn app.main:app --reload --port 8000
python -m pytest -q               # in-process contract tests
bash scripts/check.sh             # starts a server, hits every endpoint, validates against models.py
```

Point the frontend at it: in `frontend/.env.local` set `VITE_USE_MOCKS=false` and
`VITE_API_BASE_URL=http://127.0.0.1:8000`, then `npm run dev`.

Lambda handler: `backend/lambda_handler.py` → `lambda_handler.handler`.
