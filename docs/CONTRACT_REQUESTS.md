# Contract requests

Append new requests at the bottom. Format: `### [from] → [to]: title`, what you need, why, status.

### AI (be-ai) → Lead: how the AI module plugs in

`app/ai` takes and returns plain dicts (frontend camelCase), no dependency on `app/models.py`. See
`app/ai/README.md` for router glue. Needs from the skeleton:

1. **Dependencies**: no new hard deps. `boto3` (ships with Lambda; add to dev requirements for local runs)
   is imported lazily. `pytest` for tests.
2. **`.env.example`** entries: `AI_PROVIDER`, `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, `GEMINI_API_KEY`,
   `GEMINI_MODEL`, `AI_CACHE_DIR`, `AI_BRIEF_MODE`, `AI_NEGOTIATION_PACE_S` (defaults in `app/ai/README.md`).
3. **Lambda IAM**: `bedrock:InvokeModel` on the chosen model, and model access enabled in the console.
4. **Negotiation session store**: `POST /api/negotiations` returns an id; `GET .../stream` later needs the
   conjunction. Keep `{negotiationId: conjunctionId}` (in memory is fine for the demo; Lambda may cold
   start between the two calls, so also accept re-deriving it, or store in S3/DynamoDB if that happens).
5. **Streaming on Lambda**: API Gateway buffers responses, so true SSE needs Lambda response streaming
   (Function URL) or the demo must run with the AI paced replay behind a non-buffered origin.

### AI → Physics (be-physics): per-object avoidance options

The negotiator needs, for BOTH objects, the best `ManeuverOption` *if that object is the one to move*
(different mass/thrust → different `propellantKg`, maybe different `dvMs`). Please expose something like
`options_for(conjunction, mover_norad_id) -> list[ManeuverOption]`; Lead passes the recommended ones as
`context["candidates"] = {str(noradId): option}`. Until then the negotiator estimates the secondary's
burn (same Δv, propellant scaled by assumed mass/Isp) and says so in the mediator message.

### AI → Lead / contract owner: spacecraft propellant + mission data (optional)

The contract has no propellant reserve, mass or mission-criticality field, but the mediator's 35% weight is
"propellant reserve". `app/ai/profiles.py` uses clearly-labelled illustrative values per spacecraft family.
If you can source real or per-operator values (even a small JSON keyed by NORAD id), pass them as
`context["profiles"][str(noradId)] = {"reserveKg", "missionImpact", "massKg", "ispS"}` and they replace the
assumptions (and the "illustrative" caveat disappears from the mediator text). No frontend change needed.

### AI → Lead: criteria names differ from the frontend mock

The mock's `scores` event uses `Fuel efficiency / Mission continuity / Operator readiness / Risk reduction`
(0.3/0.3/0.2/0.2). The real one follows the product brief: `Propellant reserve 0.35 / Maneuver cost 0.25 /
Mission impact 0.20 / Delta-v 0.20`. The UI renders names generically, so no change is needed; flagging in
case any copy hard-codes the old names.

### AI → Lead: ask context

`ask_stream(question, {"conjunctions": [...], "catalogMeta": {...}})` is grounded only in what the router
passes. Pass the same list `GET /api/conjunctions?days=7&minPc=1e-6` returns (detail objects are better, they
carry `options`) so answers match the UI.

### AI → Lead: `.gitignore`

Root `.gitignore` lacks `__pycache__/` and `*.pyc` (I added local ignores under `app/ai` and `tests/ai`).
