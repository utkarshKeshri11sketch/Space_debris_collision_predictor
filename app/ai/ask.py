"""Ask Sentinel: Q&A grounded ONLY in the data passed in (conjunctions, their options, cascade results).

    answer = await ask(question, context)             # full text
    async for chunk in ask_stream(question, context): # word chunks, for POST /api/ask (SSE)

`context` (JSON-shaped, frontend camelCase):
    {"conjunctions": [<Conjunction|ConjunctionDetail>, ...],   # detail objects carry `options`
     "cascade": <CascadeResult>?, "catalogMeta": <CatalogMeta>?}

Safety: the question is untrusted text. Off-topic questions are refused politely without a model call;
on-topic ones go to the model inside a delimited block together with a facts block, and the answer is
discarded for a rule-based one if it contains numbers that are not in the facts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Mapping, Sequence

from . import fmt
from .brief import HUMAN_NOTE, _hours_until, best_option, conjunction_brief, overview_brief
from .generate import generate_grounded, load_prompt
from .llm import stream_words

MAX_QUESTION_CHARS = 500
MAX_FACT_EVENTS = 8

OFF_TOPIC = ("I can only help with satellites, space debris, close approaches, avoidance maneuvers and the "
             "cascade simulation in this screening run. Try asking which conjunction is most urgent.")
NOT_IN_RUN = "That isn't in the current screening run, so I can't answer it from computed data."
CASCADE_INFO = ("The Cascade Lab models a breakup as seeded fragments spreading along the parent orbit, with orbit "
                "precession turning the cloud into a ring. It is an approximate illustration of how one collision raises "
                "the risk to other satellites over the years, not a forecast of specific collisions. Run a scenario in the Cascade Lab.")

_TOPIC = re.compile(
    r"satellite|debris|collision|collide|conjunction|orbit|space|maneuver|manoeuvre|burn|delta|fuel|propellant|risk|danger|"
    r"threat|safe|urgent|worst|critical|cascade|kessler|fragment|breakup|rocket|closest|approach|miss distance|probab|"
    r"negotiat|operator|wait|delay|later|move|screen|catalog|tca|\bpc\b|brief|summary|status|overview|alert|iss\b|norad|"
    r"why|what if|how (close|soon|likely)|when|who",
    re.IGNORECASE,
)
_DANGEROUS_WORDS = re.compile(r"ignore (all |any |previous |the )*(instructions|rules)|system prompt|reveal your|you are now", re.IGNORECASE)


def _aliases(obj: Mapping[str, Any]) -> list[str]:
    name = obj["name"]
    out = {name.lower(), str(obj["noradId"])}
    if len(short := fmt.short_name(name).lower()) >= 3:
        out.add(short)
    return sorted(out, key=len, reverse=True)


def mentioned_objects(question: str, conjunctions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    q = question.lower()
    seen: dict[int, Mapping[str, Any]] = {}
    for c in conjunctions:
        for obj in (c["primary"], c["secondary"]):
            if obj["noradId"] not in seen and any(re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", q) for a in _aliases(obj)):
                seen[obj["noradId"]] = obj
    return list(seen.values())


def is_on_topic(question: str, context: Mapping[str, Any]) -> bool:
    if _DANGEROUS_WORDS.search(question) and not mentioned_objects(question, context.get("conjunctions") or []):
        return False
    return bool(_TOPIC.search(question)) or bool(mentioned_objects(question, context.get("conjunctions") or []))


def _relevant(question: str, conjs: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    objs = mentioned_objects(question, conjs)
    ids = {o["noradId"] for o in objs}
    hits = [c for c in conjs if c["primary"]["noradId"] in ids or c["secondary"]["noradId"] in ids]
    return objs, sorted(hits, key=lambda c: c["pc"], reverse=True)


def _wait_hours(question: str) -> float | None:
    m = re.search(r"(?:wait|delay|postpone|hold off|later)\D{0,20}?(\d+(?:\.\d+)?)\s*(?:h\b|hr|hour)", question, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _event_facts(c: Mapping[str, Any], now: datetime, wait: float | None = None) -> dict:
    h = _hours_until(c["tca"], now)
    opts = [{"label": o["label"], "direction": o["direction"], "dvMs": o["dvMs"], "propellantKg": o["propellantKg"],
             "resultingMissM": o["newMissM"], "resultingCollisionProbability": o["newPc"], "recommended": o["recommended"]}
            for o in c.get("options", [])[:4]]
    out: dict[str, Any] = {
        "primary": c["primary"]["name"], "primaryCanManeuver": c["primary"].get("maneuverable"),
        "secondary": c["secondary"]["name"], "secondaryCanManeuver": c["secondary"].get("maneuverable"),
        "risk": c.get("risk"), "hoursUntilClosestApproach": None if h is None else round(h, 1),
        "missDistanceM": c["missDistanceM"], "collisionProbability": c["pc"], "oddsOneIn": round(1 / c["pc"]) if c["pc"] else None,
        "relativeSpeedKms": c["relSpeedKms"], "options": opts,
    }
    opt = best_option(c)
    if opt and opt.get("burnAt") and (bh := _hours_until(opt["burnAt"], now)) is not None:
        out["hoursUntilRecommendedBurn"] = round(bh, 1)
        if wait is not None:  # derived in Python so the model never does arithmetic
            out["ifWeWait"] = {"waitHours": wait, "burnWindowStillOpen": wait < bh,
                               "hoursLeftBeforeBurnAfterWaiting": round(max(bh - wait, 0), 1),
                               "hoursLeftBeforeClosestApproachAfterWaiting": None if h is None else round(max(h - wait, 0), 1)}
    return out


def _cascade_facts(c: Mapping[str, Any]) -> dict:
    last = (c.get("years") or [{}])[-1]
    return {"parent": (c.get("parent") or {}).get("name"), "fragmentCount": c.get("fragmentCount"),
            "lastYear": last.get("year"), "trackedTotalAtLastYear": last.get("trackedTotal"),
            "extraConjunctionsPercentAtLastYear": last.get("extraConjunctionsPct"),
            "satellitesAtRiskAtLastYear": last.get("satellitesAtRisk"), "secondaryCollisions": len(c.get("secondaryCollisions") or [])}


def _negotiation_facts(neg: Any) -> dict | None:
    """Context may carry the finished negotiation: the `agreement` event, or {"agreement": event, "reasoning": str}."""
    if not isinstance(neg, Mapping):
        return None
    agreement = neg.get("agreement", neg)
    if agreement.get("type") != "agreement":
        return None
    m = agreement["maneuver"]
    out = {"recommendedMover": agreement["mover"]["name"], "dvMs": m["dvMs"], "direction": m["direction"], "propellantKg": m["propellantKg"],
           "resultingMissM": m["newMissM"], "resultingCollisionProbability": m["newPc"], "needsHumanApproval": True}
    if neg.get("reasoning"):
        out["mediatorReasoning"] = str(neg["reasoning"])[:400]
    return out


def build_facts(question: str, context: Mapping[str, Any], now: datetime) -> dict:
    conjs = list(context.get("conjunctions") or [])
    _, hits = _relevant(question, conjs)
    ranked = sorted(conjs, key=lambda c: c["pc"], reverse=True)
    chosen = (hits + [c for c in ranked if c not in hits])[:MAX_FACT_EVENTS]
    wait = _wait_hours(question)
    facts: dict[str, Any] = {
        "screeningWindowDays": 7, "conjunctionCount": len(conjs),
        "conjunctions": [_event_facts(c, now, wait if i == 0 else None) for i, c in enumerate(chosen)],
    }
    if neg := _negotiation_facts(context.get("negotiation")):
        facts["negotiationResult"] = neg
    if meta := context.get("catalogMeta"):
        facts["catalog"] = {"objectCount": meta.get("objectCount"), "byType": meta.get("byType")}
    if cas := context.get("cascade"):
        facts["cascadeResult"] = _cascade_facts(cas)
    return facts


def rule_answer(question: str, context: Mapping[str, Any], now: datetime) -> str:
    """Deterministic answer from the same data; used offline and when the model's answer fails validation."""
    conjs = list(context.get("conjunctions") or [])
    q = question.lower()
    objs, hits = _relevant(question, conjs)
    top = hits[0] if hits else (max(conjs, key=lambda c: c["pc"]) if conjs else None)
    if (wait := _wait_hours(question)) is not None and top:
        opt, h = best_option(top), _hours_until(top["tca"], now)
        bh = _hours_until(opt["burnAt"], now) if opt and opt.get("burnAt") else None
        if bh is not None:
            verdict = (f"the planned burn window would still be open, with {fmt.hours(bh - wait)} to spare" if wait < bh
                       else "the planned burn window would already have passed")
            return (f"This run does not model what a delayed burn would cost, so I can only say what the timing shows. For {top['primary']['name']} and "
                    f"{top['secondary']['name']}, the recommended burn is {fmt.hours(bh)} away and closest approach is {fmt.hours(h or 0)} away. "
                    f"If you wait {fmt.hours(wait)}, {verdict}. {HUMAN_NOTE}")
        return f"This run does not model delayed burns, and no burn time is set for this event. Closest approach is {fmt.hours(h or 0)} away. {HUMAN_NOTE}"
    if re.search(r"negotiat|who (should|has to|will|must) (move|maneuver|manoeuvre|burn)|who moves", q):
        if neg := _negotiation_facts(context.get("negotiation")):
            return (f"The negotiation recommends that {neg['recommendedMover']} flies a {fmt.dv(neg['dvMs'])} {neg['direction']} burn using "
                    f"{fmt.kg(neg['propellantKg'])}, which raises the miss distance to {fmt.distance(neg['resultingMissM'])} "
                    f"and cuts the collision probability to {fmt.probability(neg['resultingCollisionProbability'])}. {HUMAN_NOTE}")
        both = [c for c in conjs if c["primary"].get("maneuverable") and c["secondary"].get("maneuverable")]
        if not both:
            return "No close approach in this run involves two maneuverable spacecraft, so no operator negotiation is needed."
        c = both[0]
        return (f"{c['primary']['name']} and {c['secondary']['name']} can both maneuver, and the operator negotiation has not been run yet. "
                f"Open the Negotiator to compare fuel reserve, maneuver cost, mission impact and delta-v and see who is recommended to move. {HUMAN_NOTE}")
    if objs:
        names = " and ".join(o["name"] for o in objs[:2])
        if not hits:
            return f"No close approaches involving {names} in this screening run. {HUMAN_NOTE}"
        more = f" ({len(hits)} events involve it; this is the highest-probability one.)" if len(hits) > 1 else ""
        return f"{conjunction_brief(hits[0], now=now)}{more}"
    if re.search(r"cascade|kessler|breakup|explo|fragment", q):
        if cas := context.get("cascade"):
            f = _cascade_facts(cas)
            return (f"The simulated breakup of {f['parent']} creates {f['fragmentCount']:,} fragments. By year {f['lastYear']} the model shows "
                    f"{f['extraConjunctionsPercentAtLastYear']}% more close approaches, {f['satellitesAtRiskAtLastYear']:,} satellites at risk and {f['secondaryCollisions']} secondary collisions. "
                    f"This is an approximate illustration, not a forecast.")
        return CASCADE_INFO
    if re.search(r"risk|danger|worst|critical|threat|safe|urgent|first|summary|overview|status|brief|why|today|week", q) or not conjs:
        return overview_brief(conjs, now=now)
    return NOT_IN_RUN


def _slug(question: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", question.lower()))[:60] or "empty"


async def ask(
    question: str, context: Mapping[str, Any], *, llm: Callable[..., Any] | None = None, use_llm: bool = True, now: datetime | None = None,
) -> str:
    """Full answer text. Never raises on provider failure."""
    now = now or datetime.now(timezone.utc)
    question = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", (question or "")).strip()[:MAX_QUESTION_CHARS]
    if not question:
        return "Ask a question about this screening run, for example which close approach is most urgent."
    if not is_on_topic(question, context):
        return OFF_TOPIC
    fallback = rule_answer(question, context, now)
    if not use_llm:
        return fallback
    facts = build_facts(question, context, now)
    names = [n for c in context.get("conjunctions") or [] for n in (c["primary"]["name"], c["secondary"]["name"])]
    return await generate_grounded(llm, load_prompt("ask"), facts, f"QUESTION (untrusted user text):\n<<<{question}>>>", names, fallback,
                                   cache_key=f"ask/{_slug(question)}", max_tokens=260)


async def ask_stream(question: str, context: Mapping[str, Any], *, delay_s: float = 0.0, **kwargs: Any) -> AsyncIterator[str]:
    """Same answer as ask(), streamed word by word (answers are short and must be validated whole first)."""
    async for chunk in stream_words(await ask(question, context, **kwargs), delay_s):
        yield chunk
