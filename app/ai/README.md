# app/ai — OrbitSentinel AI layer

Owner: AI agent (branch `be-ai`). Pure-Python, no FastAPI/Pydantic dependency: functions take and return
JSON-shaped dicts using the frontend's camelCase field names (`frontend/src/api/types.ts`), so the routers
just pass `model.model_dump(by_alias=True)` in and wrap the output.

## Entry points

| Function | Used by | Returns |
| --- | --- | --- |
| `negotiate(context)` | `POST /api/negotiations` + `GET /api/negotiations/:id/stream` | async iterator of `NegotiationEvent` dicts |
| `conjunction_brief(detail)` | `ConjunctionDetail.brief` | `str` (template, free, instant) |
| `generate_brief(detail)` | same, when `AI_BRIEF_MODE=llm` | `str` (LLM, grounded, cached; falls back to template) |
| `overview_brief(conjunctions)` | dashboard summary | `str` |
| `ask_stream(question, context)` | `POST /api/ask` | async iterator of text chunks |

### Router glue (for Lead)

```python
# SSE for negotiation: one frame per event, then [DONE]
async def frames():
    async for event in negotiate({"conjunction": detail, "candidates": cands}):
        yield f"data: {json.dumps(event)}\n\n"
    yield "data: [DONE]\n\n"
return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# Ask: {"type":"token","text":"..."} frames are accepted by the frontend client
async for chunk in ask_stream(question, {"conjunctions": conjs, "catalogMeta": meta}):
    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
```

`negotiate()` never raises: bad input or failures become a single `{"type":"error","message":...}` event.
The router should still 404/422 before streaming (unknown conjunction, non-maneuverable pair), as the
frontend mock does.

### Negotiation context

```jsonc
{
  "conjunction": { /* ConjunctionDetail */ },
  "candidates": { "59121": { /* ManeuverOption if THAT object moves */ }, "48840": { /* ... */ } },  // optional
  "profiles":   { "59121": { "reserveKg": 12, "missionImpact": 0.15, "massKg": 800, "ispS": 1500 } }  // optional
}
```

If `candidates` is absent for an object, the primary's recommended option is used for the primary and the
secondary's burn is **estimated** (same Δv, propellant scaled by mass/Isp). The mediator says so in its
message. Real per-object options from `physics/maneuver.py` should be passed in `candidates`.

## How decisions are made

* **Numbers are never LLM output.** Scoring (`scoring.py`) is deterministic: propellant reserve 35%,
  maneuver cost 25%, mission impact 20%, Δv 20%; each 0–100 and comparative between the two spacecraft.
  Higher = more suitable to be the mover. An option must reach Pc ≤ 1e-6 to count; if only one does, it
  wins; if scores are within 2 points, the spacecraft with more propellant left moves.
* **Wording is LLM output, checked.** The two operator agents' messages come from the LLM; every number
  must be traceable to the facts supplied (`grounding.py`), else a template message replaces it. The
  mediator's messages are always templated from the computed numbers.
* **Always degrades gracefully.** Bedrock → Gemini → recorded cache → templates. A failing provider is
  skipped for `AI_COOLDOWN_S`. The demo works with no network and no keys.
* **Assumptions are disclosed.** The contract has no propellant/mass/mission data, so `profiles.py`
  holds *illustrative* values (clearly labelled); the mediator tells the user they are assumptions.
  Replace via `profiles` in the context (or a data source) when real data exists.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `AI_PROVIDER` | `auto` | `auto` (bedrock→gemini), `bedrock`, `gemini`, or `none` (templates/cache only) |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | any Bedrock text model supporting the Converse API |
| `BEDROCK_REGION` | `$AWS_REGION` or `us-east-1` | region with model access enabled |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | – / `gemini-1.5-flash` | fallback provider (REST, stdlib only) |
| `AI_MAX_TOKENS`, `AI_TIMEOUT_S`, `AI_COOLDOWN_S` | 400, 20, 60 | limits |
| `AI_CACHE_DIR` | – | record/replay directory for LLM answers (use to pre-record the demo) |
| `AI_BRIEF_MODE` | `template` | `llm` makes briefs call the model (cached per content hash) |
| `AI_NEGOTIATION_PACE_S` | `0.9` | pause between streamed negotiation events |

Credit use: a negotiation is 4 short LLM calls (≈160 output tokens each), an Ask is 1 call, briefs are free
by default.

## Tests

```sh
python -m pytest tests/ai
```
