"""AI Negotiator: one agent per operator argues its case, a mediator weighs it and recommends who moves.

Division of labour (important for trust):
  * Numbers (burn sizes, propellant, scores, who moves) are computed in Python (scoring.py), never by the LLM.
  * The LLM only writes the agents' arguments/rebuttals and the mediator's explanation, from those facts.
    Every generated text is validated (generate.py): numbers must match the facts, else one retry, else a
    template. Acceptances and override notices are always templated.
  * With no reachable provider the whole negotiation still runs on templates, so the demo cannot fail.
  * A human always approves: the stream ends with an `agreement` that is only a recommendation.

Events are exactly the frontend's NegotiationEvent union (frontend/src/api/types.ts):
    message{speaker,round,text} | scores{criteria[{name,weight,a,b}]} | agreement{mover,maneuver,signedBy} | error{message}
Rounds: 0 mediator opens, 1 opening arguments, 2 rebuttals (optional), 3 mediator decision (+ scores),
4 acceptances, 5+ override notices. `a` is the suitability of A (conjunction.primary) moving, `b` of B.

Entry points (async generators of event dicts; they never raise, failures become one `error` event):
    negotiate(conjunction, sat_a, sat_b, options)
    negotiate_override(conjunction, sat_a, sat_b, options, rejected)   # a human rejected the recommendation
See satinfo.py for the sat_* fields and _options_for for the accepted `options` shapes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Mapping

from . import fmt
from .config import negotiation_pace_s, rebuttals_enabled
from .generate import generate_grounded, load_prompt
from .satinfo import Sat, build_sat
from .scoring import ACT_PC, SPLIT_TRIGGER, TARGET_PC, Candidate, Decision, criteria, decide, evaluate_split

logger = logging.getLogger("orbitsentinel.ai.negotiator")


class NegotiationInputError(ValueError):
    pass


# ------------------------------------------------------------------------------------------ setup


@dataclass
class Setup:
    conj: Mapping[str, Any]
    a: Sat
    b: Sat
    opts_a: list[dict]
    opts_b: list[dict]
    estimated: set[str] = field(default_factory=set)   # sides whose burn was scaled, not supplied

    @property
    def id(self) -> str:
        return str(self.conj.get("id", "conjunction"))

    def sat(self, side: str) -> Sat:
        return self.a if side == "A" else self.b

    def opts(self, side: str) -> list[dict]:
        return self.opts_a if side == "A" else self.opts_b


def _burns(options: list[dict]) -> list[dict]:
    return [o for o in options if o.get("direction") != "none"]


def pick_option(options: list[dict], exclude_ids: set[str] | frozenset = frozenset()) -> dict | None:
    """Recommended burn first, else the cheapest by propellant; skips excluded ids."""
    real = [o for o in _burns(options) if o.get("id") not in exclude_ids]
    return next((o for o in real if o.get("recommended")), min(real, key=lambda o: o["propellantKg"], default=None))


def _options_for(options: Any, a: Sat, b: Sat) -> tuple[list[dict], list[dict]]:
    """`options` is a flat list of ManeuverOption (burns for the primary), or {"a": [...], "b": [...]}
    (also keyed by NORAD id) with the burns for each object if THAT object moves."""
    if isinstance(options, Mapping):
        def get(side: str, sat: Sat) -> list[dict]:
            return list(options.get(side) or options.get(side.upper()) or options.get(str(sat.ref["noradId"])) or [])
        return get("a", a), get("b", b)
    return list(options or []), []


def build_setup(conjunction: Mapping[str, Any], sat_a: Mapping | None, sat_b: Mapping | None, options: Any) -> Setup:
    try:
        a, b = build_sat(sat_a, conjunction["primary"]), build_sat(sat_b, conjunction["secondary"])
        _ = (conjunction["missDistanceM"], conjunction["pc"], conjunction["relSpeedKms"], conjunction["tca"])
    except (KeyError, TypeError) as exc:
        raise NegotiationInputError("The negotiation request was incomplete.") from exc
    opts_a, opts_b = _options_for(options, a, b)
    setup = Setup(conjunction, a, b, opts_a, opts_b)
    for side, other in (("A", "B"), ("B", "A")):
        # ASSUMPTION: relative motion is symmetric, so the same delta-v gives about the same miss distance
        # whichever object flies it; only propellant differs. For small dv the rocket equation is linear
        # (m_prop ~ m*dv/(Isp*g0)), so we scale the other side's supplied propellant by the (m/Isp) ratio.
        # Scaling a supplied number keeps both sides in the same units. maneuver.py should supply real
        # per-object options instead.
        me, you = setup.sat(side), setup.sat(other)
        if me.can_maneuver and not _burns(setup.opts(side)) and (src := pick_option(setup.opts(other))):
            ratio = (me.mass_kg / me.isp_s) / (you.mass_kg / you.isp_s)
            est = {**src, "id": f"{src['id']}-{side.lower()}", "propellantKg": round(src["propellantKg"] * ratio, 4), "recommended": False}
            setup.opts(side).append(est)
            setup.estimated.add(side)
    return setup


def _candidate(side: str, sat: Sat, opt: dict) -> Candidate:
    after = sat.fuel_pct - 100.0 * opt["propellantKg"] / sat.capacity_kg if sat.capacity_kg else sat.fuel_pct
    return Candidate(side, max(after, 0.0), opt["propellantKg"], opt["dvMs"], sat.mission_impact, opt["newPc"])


# ----------------------------------------------------------------------------------------- facts


def _burn_facts(conj: Mapping, opt: dict | None) -> dict | None:
    if not opt:
        return None
    h = fmt.hours_between(conj.get("tca"), opt.get("burnAt")) if opt.get("burnAt") else None
    return {
        "dvMs": opt["dvMs"], "direction": opt["direction"], "propellantKg": opt["propellantKg"],
        "hoursBeforeClosestApproach": None if h is None else round(h, 1),
        "resultingMissM": opt["newMissM"], "resultingPc": opt["newPc"],
    }


def _side_facts(setup: Setup, side: str, opt: dict | None) -> dict:
    s = setup.sat(side)
    return {
        "name": s.name, "operator": s.operator, "canManeuver": s.can_maneuver, "isDebris": s.is_debris,
        "fuelReservePercent": round(s.fuel_pct), "missionImpactPercent": round(s.mission_impact * 100),
        "missionImpactReason": s.mission_note, "burnIfItMoves": _burn_facts(setup.conj, opt),
    }


def _encounter(conj: Mapping) -> dict:
    return {
        "missDistanceM": conj["missDistanceM"], "relativeSpeedKms": conj["relSpeedKms"],
        "collisionProbability": conj["pc"], "targetCollisionProbabilityAfterBurn": TARGET_PC,
    }


def _burn_phrase(opt: dict) -> str:
    return f"a {fmt.dv(opt['dvMs'])} {opt['direction']} burn using {fmt.kg(opt['propellantKg'])}"


def _assumption_note(setup: Setup) -> str:
    notes = []
    if setup.estimated:
        notes.append("the " + " and ".join(setup.sat(s).name for s in sorted(setup.estimated)) + " burn is estimated from the same geometry with an assumed spacecraft mass")
    if setup.a.assumed or setup.b.assumed:
        notes.append("some fuel and mission-impact inputs are illustrative assumptions")
    return f" Note: {'; '.join(notes)}." if notes else ""


# ---------------------------------------------------------------------------------- text builders


def _tpl_argue(me: dict, other: dict) -> str:
    points = me.get("yourBestPoints") or []
    if points:
        return f"We ask that {other['name']} take the maneuver: {points[0]}" + (f", and {points[1]}." if len(points) > 1 else ".")
    mine = me["burnIfItMoves"]
    if mine is None:
        return f"{me['name']} has no computed burn available, so we ask {other['name']} to take the maneuver."
    return (f"No computed criterion favours {other['name']} moving, so {me['name']} is ready to fly {_burn_phrase(mine)} "
            f"with {me['fuelReservePercent']}% fuel in reserve, if the mediator agrees.")


def _tpl_rebut(me: dict, other: dict) -> str:
    theirs = me.get("otherOperatorsBestPoints") or []
    mine = me.get("yourBestPoints") or []
    grant = f"We acknowledge that {theirs[0]}." if theirs else "We acknowledge your position."
    hold = f" Our point stands: {mine[0]}." if mine else ""
    return f"{grant}{hold} We will accept the mediator's scoring."


def _tpl_accept(stance: str, me: Sat, other: Sat, opt: dict | None) -> str:
    if stance == "move":
        burn = f"{_burn_phrase(opt)}, taking separation to {fmt.distance(opt['newMissM'])}" if opt else "the maneuver"
        return f"Understood. {me.name} will prepare {burn}. Submitted for human flight approval; no command has been sent."
    if stance == "share":
        return f"Agreed. {me.name} will fly its share of the burn and submit it for human flight approval; no command has been sent."
    return f"Agreed. {me.name} keeps its current trajectory and will keep tracking {other.name} through closest approach, ready to re-screen if the maneuver slips."


def _tpl_mediator(setup: Setup, dec: Decision, mover: Sat, split: dict | None) -> str:
    a, b = setup.a, setup.b
    parts = []
    for sat, o in ((a, pick_option(setup.opts_a)), (b, pick_option(setup.opts_b))):
        if o:
            parts.append(f"{sat.name} moving: {_burn_phrase(o)}, miss {fmt.distance(o['newMissM'])}, collision probability {fmt.probability(o['newPc'])}.")
    parts.append(f"Weighted suitability: {a.name} {dec.total_a:.0f}/100, {b.name} {dec.total_b:.0f}/100.")
    if dec.reason == "only-eligible":
        parts.append(f"Only {mover.name}'s option reaches the target collision probability of {fmt.probability(TARGET_PC)}.")
    elif dec.reason == "none-eligible":
        parts.append(f"Neither option reaches the target collision probability of {fmt.probability(TARGET_PC)}; escalate to a human before acting.")
    elif dec.reason == "tie":
        parts.append("The scores are effectively tied, so the spacecraft with more fuel left should move.")
    elif dec.deciding:
        parts.append("Decided mainly by " + " and ".join(d.lower() for d in dec.deciding) + ".")
    if split:
        partner = setup.b if mover is setup.a else setup.a
        parts.append(f"A single burn would use over {int(SPLIT_TRIGGER * 100)}% of {mover.name}'s remaining fuel, so splitting is cheaper overall: {mover.name} flies {split['moverSharePercent']}% and {partner.name} the rest.")
    parts.append(f"Recommendation: {mover.name} maneuvers, pending human approval.{_assumption_note(setup)}")
    return " ".join(parts)


# ---------------------------------------------------------------------------------- the generator


def _msg(speaker: str, rnd: int, text: str) -> dict:
    return {"type": "message", "speaker": speaker, "round": rnd, "text": text}


def _none_option(conj: Mapping) -> dict:
    return {"id": "no-action", "label": "No action", "direction": "none", "dvMs": 0, "burnAt": None,
            "newMissM": conj["missDistanceM"], "newPc": conj["pc"], "propellantKg": 0, "recommended": True}


async def _paced(events: AsyncIterator[dict], pace: float) -> AsyncIterator[dict]:
    """Keep at least `pace` seconds between events. Time spent waiting on the LLM counts toward the gap, so a
    live negotiation is not slowed further, while template-only runs still animate like a chat."""
    loop = asyncio.get_running_loop()
    last = None
    async for event in events:
        if pace > 0 and last is not None:
            wait = pace - (loop.time() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        yield event
        last = loop.time()


async def negotiate(
    conjunction: Mapping[str, Any], sat_a: Mapping[str, Any] | None, sat_b: Mapping[str, Any] | None, options: Any,
    *, llm: Callable[..., Any] | None = None, pace_s: float | None = None, rebuttals: bool | None = None,
) -> AsyncIterator[dict]:
    """Run one negotiation. `llm` is for tests; the default is llm.acall_llm (the provider chain)."""
    try:
        setup = build_setup(conjunction, sat_a, sat_b, options)
    except NegotiationInputError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    pace = negotiation_pace_s() if pace_s is None else pace_s
    async for event in _paced(_run(setup, llm, rebuttals_enabled() if rebuttals is None else rebuttals, None), pace):
        yield event


async def negotiate_override(
    conjunction: Mapping[str, Any], sat_a: Mapping[str, Any] | None, sat_b: Mapping[str, Any] | None, options: Any,
    rejected: Mapping[str, Any], *, llm: Callable[..., Any] | None = None, pace_s: float | None = None,
) -> AsyncIterator[dict]:
    """A human rejected the recommendation. `rejected`: {"mover": noradId|name|"A"|"B" (optional),
    "option_id": str (optional), "reason": str}. Logs the reason and proposes the next-best option."""
    try:
        setup = build_setup(conjunction, sat_a, sat_b, options)
    except NegotiationInputError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    pace = negotiation_pace_s() if pace_s is None else pace_s
    async for event in _paced(_run(setup, llm, False, dict(rejected)), pace):
        yield event


def _side_of(setup: Setup, who: Any) -> str | None:
    if who is None:
        return None
    text = str(who).strip().lower()
    if text in ("a", "b"):
        return text.upper()
    for side in ("A", "B"):
        s = setup.sat(side)
        if text in (str(s.ref["noradId"]).lower(), s.name.lower(), s.operator.lower()):
            return side
    return None


def _sanitize(reason: Any) -> str:
    """The reason is human-typed text: strip control characters and cap it. It is only ever quoted in a
    template, never sent to the model as an instruction."""
    return re.sub(r"[\x00-\x1f\x7f\"]+", " ", str(reason or "")).strip()[:200] or "no reason given"


def _points_for(setup: Setup, side: str, opts: dict[str, dict | None], rows: list[dict]) -> list[str]:
    """True, computed reasons why the OTHER spacecraft is the better one to move (this side's best case).

    Computed here so each agent argues a consistent position from facts; the model only phrases them."""
    other = "B" if side == "A" else "A"
    me, you = setup.sat(side), setup.sat(other)
    mine, theirs = opts[side], opts[other]
    k = side.lower()
    better = {r["name"]: r[other.lower()] > r[k] for r in rows}  # the other spacecraft scores higher on this criterion
    points = []
    if better["Propellant reserve"]:
        points.append(f"{you.name} has more fuel left ({round(you.fuel_pct)}% against {round(me.fuel_pct)}% at {me.name})")
    if better["Maneuver cost"]:
        points.append(f"the burn costs {you.name} less propellant ({fmt.kg(theirs['propellantKg'])} against {fmt.kg(mine['propellantKg'])} for {me.name})")
    if better["Mission impact"]:
        points.append(f"a burn costs {you.name} less mission value ({round(you.mission_impact * 100)}% against {round(me.mission_impact * 100)}% for {me.name}: {me.mission_note or 'service interruption'})")
    if better["Delta-v"]:
        points.append(f"{you.name} needs less delta-v ({fmt.dv(theirs['dvMs'])} against {fmt.dv(mine['dvMs'])})")
    return points


def _facts_for(setup: Setup, side: str, opts: dict[str, dict | None], transcript: list[str], rows: list[dict]) -> dict:
    other = "B" if side == "A" else "A"
    return {"yourSpacecraft": _side_facts(setup, side, opts[side]), "otherSpacecraft": _side_facts(setup, other, opts[other]),
            "encounter": _encounter(setup.conj), "assumptions": setup.a.assumed + setup.b.assumed, "transcriptSoFar": transcript[-3:],
            "yourBestPoints": _points_for(setup, side, opts, rows), "otherOperatorsBestPoints": _points_for(setup, other, opts, rows)}


async def _run(setup: Setup, llm, rebuttals: bool, rejected: dict | None) -> AsyncIterator[dict]:
    conj, a, b = setup.conj, setup.a, setup.b
    movers = [s for s in ("A", "B") if setup.sat(s).can_maneuver]
    base = f"negotiation/{setup.id}"
    system_agent, system_med = load_prompt("operator_agent"), load_prompt("mediator")
    names = [a.name, b.name, a.operator, b.operator]

    if not movers:
        yield _msg("mediator", 0, f"{a.name} and {b.name} are both unable to maneuver, so there is nothing to negotiate. Escalate to the operators for a manual response and keep tracking the encounter.")
        yield {"type": "error", "message": "Neither spacecraft can maneuver; no avoidance negotiation is possible."}
        return

    # ---- human override: choose the next-best option, never the rejected one
    forced: tuple[str, dict] | None = None
    override_note = ""
    if rejected is not None:
        reason = _sanitize(rejected.get("reason"))
        bad_side, bad_opt = _side_of(setup, rejected.get("mover")), rejected.get("option_id")
        logger.info("negotiation %s: human override mover=%s option=%s reason=%r", setup.id, bad_side, bad_opt, reason)
        choices: list[tuple[str, dict]] = []
        for side in movers:
            if side == bad_side and not bad_opt:
                continue  # that operator refused to move at all
            excluded = {bad_opt} if bad_opt and bad_side in (None, side) else set()
            if o := pick_option(setup.opts(side), excluded):
                choices.append((side, o))
        if not choices:
            yield _msg("mediator", 5, f"Override logged (reason given: \"{reason}\"). No other computed option remains, so a human flight director must decide the response.")
            yield {"type": "error", "message": "No alternative maneuver is available after the override."}
            return
        choices.sort(key=lambda c: (c[1]["newPc"] > TARGET_PC, c[1]["propellantKg"]))  # eligible first, then cheapest
        forced = choices[0]
        override_note = (f"Override logged (reason given: \"{reason}\"). Re-planning without the rejected "
                         f"{'operator' if bad_side and not bad_opt else 'option'}; the next-best option is {setup.sat(forced[0]).name} flying {_burn_phrase(forced[1])}.")

    # ---- one side only (the other is debris or cannot move): it decides alone
    if len(movers) == 1 and forced is None:
        side = movers[0]
        other_side = "B" if side == "A" else "A"
        me, other = setup.sat(side), setup.sat(other_side)
        opt = pick_option(setup.opts(side))
        yield _msg("mediator", 0, f"{other.name} is {'debris' if other.is_debris else 'unable to maneuver'} and cannot move, so there is no negotiation. {me.name} decides alone whether to avoid.")
        act = opt is not None and conj["pc"] >= ACT_PC
        facts = {"yourSpacecraft": _side_facts(setup, side, opt), "otherSpacecraft": _side_facts(setup, other_side, None),
                 "encounter": _encounter(conj), "decision": "maneuver" if act else "monitor", "actionThresholdCollisionProbability": ACT_PC}
        if act:
            fallback = f"{me.name} will move: {_burn_phrase(opt)} raises separation to {fmt.distance(opt['newMissM'])} and cuts collision probability to {fmt.probability(opt['newPc'])}. This needs human flight approval."
            task = "Turn: decision. You are the only spacecraft that can move. State that you will maneuver, the burn, and the result."
        else:
            fallback = f"At collision probability {fmt.probability(conj['pc'])} we do not recommend a burn for {me.name}; we will keep tracking and re-screen as tracking data updates."
            task = "Turn: decision. Collision probability is below the action threshold. State that you will not maneuver and will keep monitoring."
        yield _msg("agentA" if side == "A" else "agentB", 1, await generate_grounded(llm, system_agent, facts, task, names, fallback, cache_key=f"{base}/solo_{side.lower()}"))
        mfallback = (f"{me.name} should maneuver: {_burn_phrase(opt)} gives {fmt.distance(opt['newMissM'])} separation. " if act else f"{me.name} should keep its trajectory: the risk is below the action threshold. ") + f"A human flight director must approve.{_assumption_note(setup)}"
        yield _msg("mediator", 3, await generate_grounded(llm, system_med, {**facts, "recommendedMover": me.name}, "Explain the decision.", names, mfallback, cache_key=f"{base}/mediator_solo", must_include=[re.escape(fmt.short_name(me.name)), "human"]))
        yield {"type": "agreement", "mover": me.ref, "maneuver": {**(opt if act else _none_option(conj)), "recommended": True},
               "signedBy": [f"{fmt.short_name(me.name)} operator agent", "Sentinel mediator"]}
        return

    # ---- override but only one spacecraft can move: no scoring columns to show, just the next-best burn
    if forced and len(movers) == 1:
        me = setup.sat(forced[0])
        yield _msg("mediator", 5, override_note)
        yield _msg("mediator", 6, f"{me.name} is the only spacecraft that can move, so the next-best burn is the proposal. A human flight director must approve.{_assumption_note(setup)}")
        yield {"type": "agreement", "mover": me.ref, "maneuver": {**forced[1], "recommended": True}, "signedBy": [f"{fmt.short_name(me.name)} operator agent", "Sentinel mediator"]}
        return

    # ---- full negotiation (both can move, or an override forces a choice)
    opts: dict[str, dict | None] = {"A": pick_option(setup.opts_a), "B": pick_option(setup.opts_b)}
    if forced:
        opts[forced[0]] = forced[1]
    if opts["A"] is None or opts["B"] is None:
        yield {"type": "error", "message": "No avoidance option is available for the primary spacecraft."}
        return
    rows = criteria(_candidate("A", a, opts["A"]), _candidate("B", b, opts["B"]))
    dec = decide(_candidate("A", a, opts["A"]), _candidate("B", b, opts["B"]), rows)
    if forced:
        dec = Decision(forced[0], dec.total_a, dec.total_b, "score", dec.deciding)
    mover, mover_opt = setup.sat(dec.mover), dict(opts[dec.mover])

    split = None
    if forced is None and (sp := evaluate_split(opts["A"]["propellantKg"], opts["B"]["propellantKg"], a.fuel_kg, b.fuel_kg, a.mission_impact, b.mission_impact, dec.mover)):
        share = sp.share_a if dec.mover == "A" else 1 - sp.share_a
        split = {"moverSharePercent": round(share * 100), "partnerSharePercent": round((1 - share) * 100)}
        # Contract limitation: `agreement` has one mover, so the larger-share spacecraft carries its share.
        mover_opt = {**mover_opt, "id": f"{mover_opt['id']}-split", "dvMs": round(mover_opt["dvMs"] * share, 3),
                     "propellantKg": round(mover_opt["propellantKg"] * share, 4)}

    mfacts = {
        "encounter": _encounter(conj), "spacecraftA": _side_facts(setup, "A", opts["A"]), "spacecraftB": _side_facts(setup, "B", opts["B"]),
        "weightedScoreIfAMoves": round(dec.total_a), "weightedScoreIfBMoves": round(dec.total_b),
        "weights": {"propellantReserve": 0.35, "maneuverCost": 0.25, "missionImpact": 0.20, "deltaV": 0.20},
        "recommendedMover": mover.name, "decidedBy": list(dec.deciding), "decisionType": dec.reason, "split": split,
        "assumptionsMade": a.assumed + b.assumed + [f"{setup.sat(s).name} burn estimated" for s in sorted(setup.estimated)],
    }
    # The mediator's explanation depends only on computed facts, so start it now and let it run while the agents talk.
    mediator_task = asyncio.create_task(generate_grounded(
        llm, system_med, mfacts, "Explain the decision.", names, _tpl_mediator(setup, dec, mover, split),
        cache_key=f"{base}/mediator", max_tokens=300,
        must_include=[re.escape(fmt.short_name(mover.name)), "human",
                      *([r"tie|tied|close|narrow|slight|marginal|near"] if dec.reason == "tie" else [])]))

    async def turn(side: str, speaker: str, kind: str, rnd: int, transcript: list[str]) -> tuple[str, str, int]:
        f = _facts_for(setup, side, opts, transcript, rows)
        task = ("Turn: opening argument. Ask that the OTHER spacecraft take the maneuver, using yourBestPoints (they are true and computed)."
                if kind == "argue" else
                "Turn: rebuttal. Acknowledge one fair point from otherOperatorsBestPoints, then restate one of yourBestPoints. Do not change your position and do not offer to move.")
        fallback = (_tpl_argue if kind == "argue" else _tpl_rebut)(f["yourSpacecraft"], f["otherSpacecraft"])
        text = await generate_grounded(llm, system_agent, f, task, names, fallback, cache_key=f"{base}/{speaker}_{rnd}", max_tokens=300)
        return speaker, text, rnd

    try:
        if override_note:
            yield _msg("mediator", 5, override_note)
        else:
            yield _msg("mediator", 0, f"Screening shows {a.name} and {b.name} passing {fmt.distance(conj['missDistanceM'])} apart at {conj['relSpeedKms']} km/s, collision probability {fmt.probability(conj['pc'])}. Both spacecraft can maneuver, so each operator should state its case before I score the options.")
            transcript: list[str] = []
            # Round 1: B sees A's argument. Round 2 (rebuttals): both answer round 1, so they are generated together.
            plan = [(1, "argue", [("A", "agentA")]), (1, "argue", [("B", "agentB")])]
            if rebuttals:
                plan.append((2, "rebut", [("A", "agentA"), ("B", "agentB")]))
            for rnd, kind, batch in plan:
                results = await asyncio.gather(*(turn(side, speaker, kind, rnd, transcript) for side, speaker in batch))
                for (side, _), (speaker, text, r) in zip(batch, results):
                    transcript.append(f"{setup.sat(side).name}: {text}")
                    yield _msg(speaker, r, text)

        yield _msg("mediator", 3, await mediator_task)
        yield {"type": "scores", "criteria": rows}

        for side, speaker in (("A", "agentA"), ("B", "agentB")):
            me, other = setup.sat(side), setup.sat("B" if side == "A" else "A")
            stance = "share" if split else ("move" if side == dec.mover else "stay")
            yield _msg(speaker, 4, _tpl_accept(stance, me, other, mover_opt if side == dec.mover else None))

        yield {"type": "agreement", "mover": mover.ref, "maneuver": {**mover_opt, "recommended": True},
               "signedBy": [f"{fmt.short_name(a.name)} operator agent", f"{fmt.short_name(b.name)} operator agent", "Sentinel mediator"]}
    finally:
        mediator_task.cancel()  # client disconnected or an error: do not leave the call running
