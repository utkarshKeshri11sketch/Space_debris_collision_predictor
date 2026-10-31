# Case study contract: 2021 China Space Station x Starlink

Goal for the presentation: replay the two real 2021 incidents through OrbitSentinel and show, with
numbers, how much more efficient a negotiated decision is than what happened.

**What happened:** the ~44–57 t crewed station flew avoidance burns with chemical thrusters, twice. There was
no coordination channel: China wrote to the UN afterwards, and said its emails to the US went unanswered.
**What OrbitSentinel does:** screens the pair, costs a burn for EACH side, lets the two operator agents
argue, and the mediator (35/25/20/20 weights) recommends who moves, in seconds, for a human to approve.

## Cases (facts in `backend/app/casestudy/facts.py`, all sourced)

| id | station | Starlink | date |
| --- | --- | --- | --- |
| `case-2021-07-01-css-starlink-1095` | CSS (TIANHE) 48274 | STARLINK-1095 44971 (2020-001BK) | 1 Jul 2021 |
| `case-2021-10-21-css-starlink-2305` | CSS (TIANHE) 48274 | STARLINK-2305 47989 (2021-024N) | 21 Oct 2021 |

Public facts: station near-circular ~390 km, i ~41.5°. Starlink-1095 descended 16 May–24 Jun 2021 to
~382 km and stayed there. Starlink-2305 was maneuvering continuously. Exact TCA, miss distance and
the station's burn size were **not published**: they must be reconstructed and labelled as such.

## Ownership

| Part | Owner | File |
| --- | --- | --- |
| Facts, sources, assembly, API, presentation simulation page | Lead | `backend/app/casestudy/`, `backend/app/routers/case_studies.py`, `docs/case_studies/` |
| Encounter reconstruction + costing both sides | Physics | `backend/app/physics/incident.py` + `backend/tests/physics/test_incident.py` |
| Decision, negotiation profiles, narrative | Lead (AI agent not used for this task) | `backend/app/ai/incident.py` + `backend/tests/ai/test_incident.py` |

## Physics: `analyse(case: dict) -> dict`

`case` is one entry of `facts.CASES`. Return:

```jsonc
{
  "conjunction": ConjunctionDetail,          // exact frontend shape; id = case["id"]
                                             // primary = station ref, secondary = Starlink ref, both maneuverable: true
                                             // tca = reconstructed UTC on the case date; missDistanceM, rtnM, relSpeedKms,
                                             // pc, risk, rangeSeries (81 pts), afterSeries, covariance, hardBodyRadiusM,
                                             // options = burns if the STATION moves + "No action"; brief: ""
  "optionsBySide": {"a": [ManeuverOption], "b": [ManeuverOption]},  // a = station moves, b = Starlink moves
  "reality": {                               // what the station actually spent (reconstructed)
    "moverNoradId": 48274, "dvMs": 0.0, "propellantKg": 0.0,
    "massKg": 0.0, "ispS": 0.0,
    "basis": "how dv/propellant were obtained, in one sentence"
  },
  "assumptions": ["every modelled number, one line each, with its source or 'assumption'"]
}
```

Use `app.physics.maneuver` (`plan_maneuvers`, `propellant_kg`, `Encounter`) so costs use the same
models as live events. Historical element sets: Space-Track GP_HISTORY (needs a free account) if
available; otherwise build circular orbits from the published altitudes/inclinations and state that.

## AI part (built by Lead): `recommend`, `narrate`, `sat_profiles`

- `recommend(conjunction, options_by_side, sat_a, sat_b) -> {"moverSide": "a"|"b", "moverNoradId": int, "maneuver": ManeuverOption, "criteria": [{name, weight, a, b}], "alternative": ManeuverOption}`
  — the same scoring as the live negotiator (`app.ai.scoring`), weights 35/25/20/20.
- `sat_profiles(case, analysis) -> (sat_a, sat_b)` — `negotiate()` inputs for the 2021 station (crewed, chemical
  thrusters, high mission impact) and the 2021 Starlink (v1.x, ~260 kg, Hall thrusters). Mark every
  non-public value as assumed.
- `narrate(case, analysis, decision) -> {"reality": str, "orbitSentinel": str, "brief": str}` — grounded
  only in `case["facts"]`, `facts.AFTERMATH` and the computed numbers. No invented quotes, no blame.

The existing endpoints then replay the case unchanged:
`GET /api/conjunctions/<case id>`, `POST /api/negotiations {conjunctionId: <case id>}` + stream,
and the frontend at `/conjunctions/<case id>` and `/negotiator/<case id>`.

## Lead: `GET /api/case-studies` and `GET /api/case-studies/{id}` → `CaseStudy` (see `app/models.py`)

`status.physics` / `status.ai` say `pending` until each part is delivered; nothing is faked meanwhile.

## Rewind 2009 (Cascade Lab): Iridium 33 x Cosmos 2251

`GET /api/collision-studies` and `GET /api/collision-studies/case-2009-02-10-iridium33-cosmos2251` →
`CollisionStudy` (`app/models.py`, `frontend/src/api/types.ts`). Built by Lead in `app/casestudy/collision.py`
from sourced facts (Kelso 2009, Iridium's Shepperd 2023 replay, NASA's Liou 2013 counts) plus the same physics
as live events: `maneuver.plan_maneuvers` for Iridium 33's avoidance burn on a reconstructed encounter, and
`cascade.collision_fragment_yield` for the NASA breakup model. Pc over time is quoted from Iridium's replay,
not computed. Frontend: `/cascade/rewind-2009`, linked from the Cascade Lab. After changing the study, run
`python scripts/build_collision_fixture.py` from `backend/` so offline mode shows the same numbers.
