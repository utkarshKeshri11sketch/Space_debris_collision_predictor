# AI layer: how it works (for the team and the pitch)

Branch `be-ai`, code in `app/ai/`, tests in `tests/ai/`. **Free LLM APIs only** (Groq, Gemini, Cerebras).
Detail for developers: `app/ai/README.md`. Cross-team asks: `docs/CONTRACT_REQUESTS.md`.

## The idea in one paragraph

Free collision warnings already exist, but they hand operators raw numbers and nobody decides who should move when
two active satellites are on a collision course. Our AI layer plays the **lawyers and the judge**: one AI agent
speaks for each operator, a mediator weighs fuel, cost, mission impact and Δv, and recommends who moves, streamed
live like a chat. A human approves or overrides. The **numbers and the decision are computed by code**; the AI
only explains them in plain English, and anything it says is checked against the data.

## What the audience sees (Starlink × OneWeb, live, ~8–10 s)

1. Mediator: the two spacecraft pass 690 m apart at 12.8 km/s, collision probability 8.7 × 10⁻⁵; each operator may speak.
2. **Starlink's agent:** OneWeb's burn costs less propellant (0.03 kg vs 0.18 kg), so OneWeb should move.
3. **OneWeb's agent:** Starlink has more fuel (78% vs 41%) and a burn costs it far less mission value (15% vs 45%).
4. Rebuttals, then the **mediator's scores** (reserve 35 / cost 25 / mission impact 20 / Δv 20) and decision:
   a narrow call, Starlink moves (0.42 m/s prograde, miss 690 m → 4.2 km, Pc → 2.3 × 10⁻⁸).
5. Both agents accept; the plan is "signed" and waits for **human approval** (or an override that triggers a re-plan).

ISS × COSMOS 1408 debris: debris cannot negotiate, so the ISS decides alone ("should our satellite move?").

## What is computed vs. what the AI writes

| Computed in Python (never by the AI) | Written by the AI (then validated) |
| --- | --- |
| Burn Δv / propellant / new miss / new Pc (from `maneuver.py`) | Each agent's argument and rebuttal |
| The four criterion scores, weighted totals, who moves | The mediator's explanation |
| Eligibility (Pc ≤ 1e-6), ties, split-burn check | The Sentinel brief wording |
| Each agent's true talking points | Ask Sentinel answers |

Validation (`generate.py`): every number must appear in the facts we gave the model (m↔km allowed), the mediator
must name the computed mover (and say "tie" if it was one), text must not be cut off or too long. Otherwise one
regeneration, then a built-in template. Tested: the AI cannot change a score or the mover.

## Providers and resilience

`call_llm(system, messages, stream=False, json_mode=False)` in `llm.py`; order **groq → gemini → cerebras → cached**,
start chosen by `LLM_PROVIDER`. 429, timeout (>15 s) or any error falls to the next; the failed provider is skipped
for a while. Keys only from env vars (`app/ai/.env.example`). With `LLM_PROVIDER=cached` and no keys every AI
function works from `app/ai/cache/` (pre-recorded) or built-in templates, with zero API calls.

**Verified with real keys on 2026-10-30** (Groq + Gemini; no Cerebras key was available, so Cerebras is untested):

| Provider | Result |
| --- | --- |
| Groq | works with `openai/gpt-oss-120b` (~0.8 s/call). The brief's `llama-3.3-70b-versatile` **no longer exists** on this account; models listed were gpt-oss-120b/20b and qwen3.8-27b. Free tier: 8,000 tokens/min, so one negotiation uses most of a minute → Gemini takes over under load. |
| Gemini | works with `gemini-2.5-flash` (thinking switched off; ~1.5 s/call). Full negotiation through Gemini alone: ~10 s. |
| Cerebras | untested; default model id `llama-3.3-70b` is a guess. |

Full live negotiation through Groq: 8.3 s to the final agreement (5 model calls; mediator runs in parallel with the debate).

## Frontend contract (unchanged)

`NegotiationEvent`: `message{speaker,round,text}` · `scores{criteria[{name,weight,a,b}]}` · `agreement{mover,maneuver,signedBy}` ·
`error{message}`. Order: mediator r0 → agentA r1 → agentB r1 → (rebuttals r2) → mediator r3 → scores → acceptances r4 → agreement.
`a`/`b` = suitability (0–100) of the primary/secondary moving; the UI computes the weighted totals itself.
`ConjunctionDetail.brief` is a plain string (3–5 sentences, no markdown, typed out on the dashboard). `/api/ask` streams plain-prose tokens.
Criteria names follow the product brief, not the mock's older names (UI renders names generically).

## Honest limitations

* **Operator data is assumed.** The contract has no fuel, mass or mission-impact fields. Fuel reserve and mission impact
  for the demo satellites are illustrative (`demo.py`, `profiles.py`) and the mediator says so; real values can be passed in.
* **Without per-object burns from `maneuver.py`** the secondary's burn is estimated from the primary's (same Δv, scaled
  propellant) and labelled as estimated.
* A split burn is announced in text, but the contract's `agreement` has one `mover`, so it carries the larger share.
* Cached demo text is tied to the exact situation it was recorded for; for anything else the live models or templates are used.
* Model output still needs human review; nothing here sends a command. The AI cannot see anything outside the data it is given.

## Open questions for the team

1. API Gateway buffers responses: how do we deliver real SSE on Lambda (response streaming / Function URL)?
2. Negotiation ids across Lambda cold starts (in-memory map may vanish between `POST` and the stream).
3. Who supplies fuel/mission data for real operators (even a small JSON keyed by NORAD id)?
4. Cerebras: someone with a free key should run `python scripts/check_llm.py` once.
