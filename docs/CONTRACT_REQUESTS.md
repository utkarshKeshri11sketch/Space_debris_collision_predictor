# Contract requests

Append new requests at the bottom. Format: `### [from] → [to]: title`, what you need, why, status.

### AI (be-ai) → Lead: how the AI module plugs in

`app/ai` takes and returns plain dicts (frontend camelCase), no dependency on `app/models.py`. See `app/ai/README.md`
for router glue (`negotiate`, `ask_stream`, `generate_brief`). Needs from the skeleton:

1. **Dependency**: `openai` (`app/ai/requirements.txt`) for Groq/Gemini/Cerebras (all OpenAI-compatible). `pytest` for tests.
   No AWS/Bedrock dependency; free providers only.
2. **`.env.example`**: copy the variables from `app/ai/.env.example` (`LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
   `CEREBRAS_API_KEY`, optional model/tuning vars). Set `LLM_PROVIDER=cached` for offline demos.
3. **Negotiation session store**: `POST /api/negotiations` returns an id; `GET .../stream` later needs the conjunction.
   Keep `{negotiationId: conjunctionId}` (in memory for the demo; Lambda may cold-start between the two calls).
4. **Streaming on Lambda**: API Gateway buffers responses, so true SSE needs Lambda response streaming (Function URL) or
   another unbuffered path. `negotiate()` already paces events ≥0.7 s apart.
5. **Inputs for `negotiate()`**: per spacecraft `operator`, `can_maneuver`, `fuel_reserve_pct`, `mission_impact`
   (see "AI → Lead: operator data" below). Until you have them, pass `{}` and the illustrative defaults apply.
6. **`.gitignore`**: add `__pycache__/` and `*.pyc` (I added local ignores under `app/ai` and `tests/ai`).
7. **Ask context**: pass `{"conjunctions": [...ConjunctionDetail...], "negotiation": <finished agreement or {"agreement","reasoning"}>, "cascade": <CascadeResult>}`;
   without `negotiation` Ask will not say who should move.

### AI → Physics (be-physics): per-object avoidance options

The negotiator needs, for BOTH objects, the best `ManeuverOption` *if that object is the one to move* (different mass/
thrust → different `propellantKg`, maybe different `dvMs`). Please expose something like
`options_for(conjunction, mover_norad_id) -> list[ManeuverOption]`; Lead passes `options={"a": [...], "b": [...]}`.
Until then the negotiator estimates the secondary's burn (same Δv, propellant scaled by assumed mass/Isp) and says so.
Also useful: a "split" option (two smaller burns, one per spacecraft) if you can compute it; today the AI announces a
split from a simple scarcity model (`scoring.evaluate_split`) but the contract has no way to carry two burns.

### AI → Lead / contract owner: operator data (optional but valuable)

The contract has no fuel reserve, mass or mission-criticality. `app/ai/profiles.py` uses clearly labelled illustrative
values; the mediator tells the user so. If you can source real or per-operator values (even a JSON keyed by NORAD id), pass
them in `sat_a` / `sat_b` and the caveat disappears. No frontend change needed.

### AI → Lead (frontend contract owner): small contract gaps, none blocking

* `agreement` has a single `mover` and a single `maneuver`. A **split burn** or a **"no maneuver needed"** outcome is
  currently expressed as the larger-share spacecraft with a scaled burn, or `direction: "none"`. Suggest an optional
  `coMover` / `mover: null` later.
* There is no event for a **human override**; `negotiate_override()` re-plans using the existing event types
  (mediator message at round 5+, then `scores`/`agreement`). A `POST /api/negotiations/:id/override {reason, moverId?, optionId?}`
  endpoint would call it.
* The mock's `scores` criteria names (Fuel efficiency / Mission continuity / …) differ from the real ones (Propellant
  reserve / Maneuver cost / Mission impact / Delta-v). The UI renders names generically; flagging in case any copy hard-codes them.
