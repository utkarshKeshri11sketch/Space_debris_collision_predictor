# app/ai — OrbitSentinel AI layer

Owner: AI agent (branch `be-ai`). **Free LLM providers only** (Groq, Gemini, Cerebras); never add a paid one.
Pure Python, no FastAPI/Pydantic dependency: functions take and return JSON-shaped dicts using the frontend's
camelCase field names (`frontend/src/api/types.ts`), so routers pass `model.model_dump(by_alias=True)` in and wrap
the output. Dependency: `openai` (see `requirements.txt`). Settings: `.env.example`.

## Entry points

| Function | Used by | Returns |
| --- | --- | --- |
| `negotiate(conjunction, sat_a, sat_b, options)` | `GET /api/negotiations/:id/stream` | async iterator of `NegotiationEvent` dicts |
| `negotiate_override(..., rejected)` | human overrides a recommendation | same, with the next-best option |
| `brief(target, conjunctions)` / `generate_brief(detail)` | `ConjunctionDetail.brief`, dashboard brief | `str`, 3–5 sentences |
| `ask(question, context)` / `ask_stream(...)` | `POST /api/ask` | `str` / async iterator of word chunks |
| `call_llm(system, messages, stream=False, json_mode=False)` | everything above | text, or iterator when `stream=True` |

### Router glue (for Lead)

```python
# SSE for negotiation: one frame per event, then [DONE]; negotiate() never raises (failures are `error` events)
async def frames():
    async for event in negotiate(conjunction, sat_a, sat_b, options):
        yield f"data: {json.dumps(event)}\n\n"
    yield "data: [DONE]\n\n"
return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# Ask: {"type":"token","text":"..."} frames are accepted by the frontend client
async for chunk in ask_stream(question, {"conjunctions": conjs, "negotiation": finished_negotiation, "cascade": cascade_result}):
    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
```

`negotiate()` pauses ≥0.7 s between events (`AI_NEGOTIATION_PACE_S`) so the UI animates like a live chat. The router
should still return 404/422 before streaming (unknown conjunction; the frontend mock returns 422 when either object
cannot maneuver, although `negotiate()` also handles that case).

### `negotiate` inputs

* `conjunction`: a `ConjunctionDetail` dict.
* `sat_a` / `sat_b` (A = `primary`, B = `secondary`): `operator`, `can_maneuver`, `fuel_reserve_pct` (0–100),
  `mission_impact` (0–1, or `{"score", "note"}`), optionally `propellant_capacity_kg`, `mass_kg`, `isp_s`.
  Anything missing is filled from `profiles.py` (illustrative) and reported as an assumption in the mediator text.
* `options`: a flat list of `ManeuverOption` (burns for A), or `{"a": [...], "b": [...]}` (also keyed by NORAD id) with
  the best burns if THAT object moves. If B has none, its burn is estimated from A's (same Δv, propellant scaled by
  mass/Isp) and the mediator says so.

## How it works

* **Scores are computed in Python, never by the LLM** (`scoring.py`): propellant reserve 35%, maneuver cost 25%,
  mission impact 20%, Δv 20%, each normalised 0–100 between the two spacecraft. An option must reach Pc ≤ 1e-6 to
  count; if only one does it wins; scores within 2 points are a tie (more fuel left moves).
* **The LLM only phrases things** (`prompts/*.md`): agents' arguments/rebuttals and the mediator's explanation. Each
  agent is handed its true, computed talking points (`yourBestPoints`) so the debate is consistent.
* **Every generated text is validated** (`generate.py`): numbers must exist in the facts, the mediator must name the
  computed mover, no truncation, ≤120 words. On failure: one regeneration naming the problem, then a template.
* **Edge cases**: one side cannot maneuver / is debris → announced immediately, no debate, that satellite decides alone
  (burns only if Pc ≥ 1e-5); nobody can move → `error`; two small burns cheaper than one → split announced
  (`agreement` carries the larger share; the contract has a single `mover`); human override → reason logged and
  quoted (never sent to the model), next-best option proposed.
* **Always degrades**: groq → gemini → cerebras → cached → templates. HTTP 429, timeouts (>15 s) and any error move on;
  a failing provider is skipped for 60 s (15 s after a 429). Free tiers are tight (Groq: 8,000 tokens/min), so prompts
  use compact JSON and a negotiation makes ~6 short calls.
* **Offline demo**: `LLM_PROVIDER=cached` replays `app/ai/cache/` (entries are tied to a hash of the facts, so they are
  only used for the situation they were recorded for). Regenerate with `python scripts/build_ai_cache.py` (needs a key).

## Tests and tools

```sh
python -m pytest tests/ai              # no keys or network needed
python scripts/check_llm.py            # one tiny call per provider that has a key
python scripts/build_ai_cache.py       # record the demo cache with a live provider
```
