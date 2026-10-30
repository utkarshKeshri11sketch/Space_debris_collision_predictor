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
| Lead (Claude #1) | `backend/app/main.py`, `backend/app/models.py`, `backend/app/routers/`, `backend/app/warmup.py`, `backend/scripts/`, deploy, docs | `main` (integration) |
| Data (Codex #1, handed to Lead on 2026-10-30) | `backend/app/data/` + `backend/tests/data/` | `be-data` (merged) |
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

## How the backend fits together (integrated 2026-10-30)

All four areas are merged into `main` and the routers call the real code. No mock data is served.

| Endpoint | Router | Real implementation |
| --- | --- | --- |
| `GET /api/health` | `main.py` | — |
| `GET /api/catalog` / `GET /api/catalog/meta` | `routers/catalog.py` | `data.catalog.load_catalog()` / `catalog_meta()` (gzipped) |
| `GET /api/conjunctions?days&minPc` | `routers/conjunctions.py` | `physics.screening.screen()` over the watch-list from `data.watchlist` |
| `GET /api/conjunctions/{id}` | `routers/conjunctions.py` | `screening.get_conjunction()` + options from `physics.maneuver` + brief from `ai.generate_brief()` |
| `POST /api/negotiations` + `GET /{id}/stream` (SSE) | `routers/negotiations.py` | `ai.negotiate()` with per-side options from `maneuver.options_for()` |
| `POST /api/cascade` | `routers/cascade.py` | `physics.cascade.simulate(request, catalog)` |
| `POST /api/ask` (SSE) | `routers/ask.py` | `ai.ask_stream(question, {conjunctions, catalogMeta})` |

Real-data decisions (Lead):
- **Catalog**: CelesTrak GP (active + DEB + R/B), refreshed by `python -m app.data.refresh`; until a
  refresh succeeds the bundled July 2025 archive is served (Screening refuses it as too old).
- **Maneuverable** = active payload of a propulsive fleet (Starlink, OneWeb, Kuiper, ISS, Tianhe) or
  listed in `CATALOG_MANEUVERABLE_IDS`. An assumption, not operator-verified.
- **Watch-list** = ISS + the closest real cross-operator maneuverable pair from CelesTrak SOCRATES.
  SOCRATES only picks what we screen; all numbers come from our own SGP4 screening.
- **Pc** = worst-case (maximum) probability over covariance scale (Alfano 2005, SOCRATES MAX_PROB),
  because public GP data has no covariance. `SCREENING_PC_MODEL=assumed` restores the per-type model.
- **Speed**: a background warm-up screens at startup and every 10 min; first results take minutes.

SSE format: each event is `data: <json>` followed by a blank line; the stream ends with `data: [DONE]`. Errors: JSON
`{"message": "..."}` with a 4xx status, or an in-stream `{"type":"error","message":"..."}` event.

## Run and test

```sh
cd backend
python -m pip install -r requirements.txt
cp .env.example .env              # optional
python -m uvicorn app.main:app --reload --port 8000
python -m app.data.refresh       # download the live CelesTrak catalog + SOCRATES (max once / 2 h)
python -m pytest -q               # all areas: data, screening, physics, ai, API contract
bash scripts/check.sh             # starts a server, hits every endpoint, validates against models.py
```

Point the frontend at it: in `frontend/.env.local` set `VITE_USE_MOCKS=false` and
`VITE_API_BASE_URL=http://127.0.0.1:8000`, then `npm run dev`.

Lambda handler: `backend/lambda_handler.py` → `lambda_handler.handler`.
