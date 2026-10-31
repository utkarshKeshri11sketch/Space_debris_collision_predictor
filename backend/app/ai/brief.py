"""Sentinel brief: a 3-5 sentence plain-English risk summary, grounded only in computed conjunction data.

brief(target, conjunctions) picks the events that involve `target` (a NORAD id, an object name, a conjunction
id, a conjunction dict, or None for the whole run), puts the MOST DANGEROUS one first, and returns the text
that goes into ConjunctionDetail.brief. The LLM (prompts/brief.md) only phrases it; numbers are validated
and a deterministic template is the fallback, so the result is always correct and never empty.
Results are cached in memory by content, so repeated GETs cost no API calls.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from . import fmt
from .config import brief_uses_llm
from .generate import generate_grounded_sync, load_prompt
from .scoring import ACT_PC

HUMAN_NOTE = "A human operator must approve any maneuver."
_cache: dict[str, str] = {}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _hours_until(tca: str, now: datetime) -> float | None:
    parsed = fmt.parse_time(tca)
    return None if parsed is None else (parsed - now).total_seconds() / 3600


def best_option(detail: Mapping[str, Any]) -> Mapping[str, Any] | None:
    real = [o for o in detail.get("options", []) if o.get("direction") != "none"]
    return next((o for o in real if o.get("recommended")), real[0] if real else None)


def physics_says_wait(detail: Mapping[str, Any]) -> bool:
    """Physics marks "No action" recommended below its burn threshold (maneuver.PC_MANEUVER_THRESHOLD,
    1e-4, the NASA CARA red level). Between ACT_PC and that level the brief must not recommend a burn,
    or the text contradicts the options shown next to it."""
    return any(o.get("recommended") and o.get("direction") == "none" for o in detail.get("options", []))


def _objects(c: Mapping[str, Any]) -> set[int]:
    return {c["primary"]["noradId"], c["secondary"]["noradId"]}


def _matches(target: Any, c: Mapping[str, Any]) -> bool:
    if target is None:
        return True
    if isinstance(target, Mapping):  # a conjunction: matches itself and events sharing one of its objects
        return c.get("id") == target.get("id") or bool(_objects(target) & _objects(c))
    text = str(target).strip().lower()
    return text == str(c.get("id", "")).lower() or any(
        text in (str(c[k]["noradId"]).lower(), c[k]["name"].lower(), fmt.short_name(c[k]["name"]).lower()) for k in ("primary", "secondary")
    )


def select_events(target: Any, conjunctions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Events involving the target, most dangerous (highest collision probability) first.
    A conjunction passed as the target is itself the first (headline) event."""
    hits = sorted((c for c in conjunctions if _matches(target, c) and c is not target), key=lambda c: c["pc"], reverse=True)
    if isinstance(target, Mapping) and "primary" in target:
        return [target, *[c for c in hits if c.get("id") != target.get("id")]]
    return hits


def _maneuver_sentence(p: Mapping, s: Mapping) -> str:
    if p.get("maneuverable") and s.get("maneuverable"):
        return "Both spacecraft can maneuver, so their operators need to agree who moves; the operator negotiation compares fuel, cost and mission impact."
    if not p.get("maneuverable") and not s.get("maneuverable"):
        return "Neither object can maneuver, so this can only be monitored."
    mover, fixed = (p, s) if p.get("maneuverable") else (s, p)
    why = "is debris and cannot maneuver" if fixed.get("type") in ("DEBRIS", "ROCKET_BODY") else "cannot maneuver"
    return f"{fixed['name']} {why}, so {mover['name']} has to decide alone."


def conjunction_brief(detail: Mapping[str, Any], *, now: datetime | None = None, others: int = 0) -> str:
    """Deterministic 3-5 sentence brief for one event (the fallback and the offline text)."""
    p, s = detail["primary"], detail["secondary"]
    h = _hours_until(detail["tca"], _now(now))
    when = "" if h is None else (" earlier today" if h < 0 else f" in {fmt.hours(h)}")
    pc = detail["pc"]
    wait = physics_says_wait(detail)
    level = ("low enough to keep watching rather than act" if pc < ACT_PC
             else "high enough to watch closely and keep a burn ready, though below the level where a burn is recommended"
             if wait else "serious enough that operators normally act")
    sentences = [
        f"{p['name']} and {s['name']} will pass {fmt.distance(detail['missDistanceM'])} apart{when} (their closest approach) at {fmt.speed(detail['relSpeedKms'])}.",
        f"The chance they collide is {fmt.probability(pc)}, about {fmt.odds(pc)}, which is {level}.",
        _maneuver_sentence(p, s),
    ]
    opt = best_option(detail)
    tail = ""
    if others:
        tail = f" {others} other close approach{'es are' if others > 1 else ' is'} also on the watch list."
    if opt and pc >= ACT_PC:
        burn_h = fmt.hours_between(detail["tca"], opt.get("burnAt")) if opt.get("burnAt") else None
        timing = "" if burn_h is None else f" {fmt.hours(burn_h)} before closest approach"
        if wait:
            sentences.append(
                f"No burn is recommended yet. If the risk rises, the prepared option is a {fmt.dv(opt['dvMs'])} {opt['direction']} burn{timing}, "
                f"using {fmt.kg(opt['propellantKg'])} of fuel, which would widen the gap to {fmt.distance(opt['newMissM'])}.{tail}"
            )
        else:
            sentences.append(
                f"Recommended action: a {fmt.dv(opt['dvMs'])} {opt['direction']} burn{timing}, using {fmt.kg(opt['propellantKg'])} of fuel, "
                f"which widens the gap to {fmt.distance(opt['newMissM'])} and cuts the collision chance to {fmt.probability(opt['newPc'])}.{tail}"
            )
    else:
        sentences.append(f"No maneuver is recommended right now; keep tracking and re-check as new data arrives.{tail}")
    sentences.append(HUMAN_NOTE)
    return " ".join(sentences)


def overview_brief(conjunctions: Sequence[Mapping[str, Any]], *, now: datetime | None = None) -> str:
    """Whole-run summary (no particular target)."""
    if not conjunctions:
        return "No close approaches were found above the screening threshold in this run. Continue routine monitoring."
    return conjunction_brief(max(conjunctions, key=lambda c: c["pc"]), now=now, others=len(conjunctions) - 1)


def _facts(top: Mapping[str, Any], others: Sequence[Mapping[str, Any]], now: datetime, target_name: str | None) -> dict:
    opt = best_option(top)
    h = _hours_until(top["tca"], now)
    # When physics recommends no burn yet, the option is only a prepared one; the key says so, so the
    # model cannot present it as a recommendation. Other facts (and their cache keys) are unchanged.
    burn_key = "preparedBurnNotRecommendedYet" if physics_says_wait(top) else "recommendedBurn"
    return {
        "briefingFor": target_name,
        "mostDangerousEvent": {
            "primary": {"name": top["primary"]["name"], "canManeuver": top["primary"].get("maneuverable"), "type": top["primary"].get("type")},
            "secondary": {"name": top["secondary"]["name"], "canManeuver": top["secondary"].get("maneuverable"), "type": top["secondary"].get("type")},
            "hoursUntilClosestApproach": None if h is None else round(h, 1), "missDistanceM": top["missDistanceM"],
            "relativeSpeedKms": top["relSpeedKms"], "collisionProbability": top["pc"], "oddsOneIn": round(1 / top["pc"]) if top["pc"] else None,
            "risk": top.get("risk"),
            burn_key: None if not opt else {
                "dvMs": opt["dvMs"], "direction": opt["direction"], "propellantKg": opt["propellantKg"],
                "hoursBeforeClosestApproach": None if not opt.get("burnAt") else round(fmt.hours_between(top["tca"], opt["burnAt"]) or 0, 1),
                "resultingMissM": opt["newMissM"], "resultingCollisionProbability": opt["newPc"],
            },
        },
        "otherEventCount": len(others),
    }


def brief(
    target: Any, conjunctions: Sequence[Mapping[str, Any]], *, now: datetime | None = None, use_llm: bool | None = None,
    llm: Callable[..., str] | None = None,
) -> str:
    """The Sentinel brief for `target` (see module docstring). Never raises."""
    moment = _now(now)
    events = select_events(target, conjunctions)
    if not events:
        return "No close approaches involve this object in the current screening run, so no action is needed. Continue routine monitoring. " + HUMAN_NOTE
    top, others = events[0], events[1:]
    template = conjunction_brief(top, now=moment, others=len(others))
    if not (brief_uses_llm() if use_llm is None else use_llm):
        return template
    name = None if target is None or isinstance(target, Mapping) else str(target)
    facts = _facts(top, others, moment, name)
    # Content hash with whole hours, so a brief is reused for an hour rather than regenerated on every GET.
    key_facts = json.loads(json.dumps(facts))
    if (h := key_facts["mostDangerousEvent"]["hoursUntilClosestApproach"]) is not None:
        key_facts["mostDangerousEvent"]["hoursUntilClosestApproach"] = round(h)
    key = hashlib.sha256(json.dumps(key_facts, sort_keys=True).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    names = [top["primary"]["name"], top["secondary"]["name"]]
    text = generate_grounded_sync(load_prompt("brief"), facts, "Write the brief.", names, template, cache_key=f"brief/{top.get('id', 'run')}", llm=llm, must_include=[r"human"])
    sentences = [x for x in text.replace("? ", ". ").split(". ") if x.strip()]
    if not 3 <= len(sentences) <= 6:  # a brief outside 3-5 sentences (small slack for abbreviations) is not what we promised
        text = template
    _cache[key] = text
    return text


def generate_brief(detail: Mapping[str, Any], **kwargs: Any) -> str:
    """Brief for a single ConjunctionDetail (what GET /api/conjunctions/:id puts in `brief`)."""
    return brief(detail, [detail], **kwargs)
