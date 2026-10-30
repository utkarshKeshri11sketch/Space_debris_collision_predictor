"""Assemble a case study from Lead facts + Physics reconstruction + AI decision/narrative.

Each part is optional while the agents work: a missing part is reported in `status` instead of
being filled with invented numbers.
"""
from __future__ import annotations

import logging

from ..models import CaseStudy, ConjunctionDetail
from . import facts

LOG = logging.getLogger(__name__)
PREFIX = "case-"


def is_case(conjunction_id: str) -> bool:
    return conjunction_id.startswith(PREFIX)


def _try(label: str, fn, *args):
    try:
        return fn(*args), "ready"
    except NotImplementedError:
        return None, "pending"
    except Exception:  # noqa: BLE001 - one broken part must not hide the others
        LOG.exception("Case study %s failed", label)
        return None, "error"


_ANALYSES: dict[str, dict] = {}


def _analysis(case_id: str) -> tuple[dict | None, str]:
    """Physics reconstruction, cached once it succeeds (a pending/error result is retried)."""
    if case_id in _ANALYSES:
        return _ANALYSES[case_id], "ready"
    from ..physics import incident
    result, status = _try("physics", incident.analyse, facts.case(case_id))
    if result is not None:
        _ANALYSES[case_id] = result
    return result, status


def _comparison(reality: dict | None, maneuver: dict | None) -> dict | None:
    if not reality or not maneuver or not reality.get("propellantKg") or not maneuver.get("propellantKg"):
        return None
    saved = reality["propellantKg"] - maneuver["propellantKg"]
    return {"propellantSavedKg": saved, "propellantRatio": reality["propellantKg"] / maneuver["propellantKg"],
            "dvRealityMs": reality.get("dvMs"), "dvOrbitSentinelMs": maneuver.get("dvMs")}


def build(case_id: str) -> CaseStudy | None:
    case = facts.case(case_id)
    if case is None:
        return None
    from ..ai import incident as ai_incident
    analysis, physics_status = _analysis(case_id)
    decision, ai_status = (None, "pending")
    narrative = None
    if analysis:
        decision, ai_status = _try("ai.recommend", ai_incident.recommend, analysis["conjunction"], analysis["optionsBySide"])
        if decision:
            narrative, _ = _try("ai.narrate", ai_incident.narrate, case, analysis, decision)
    sources = [{"key": key, **value} for key, value in facts.SOURCES.items()]
    return CaseStudy.model_validate({
        "id": case_id, "title": case["title"], "date": case["date"], "facts": case["facts"],
        "aftermath": facts.AFTERMATH, "sources": sources,
        "conjunction": get_conjunction(case_id).model_dump() if analysis else None,
        "reality": analysis["reality"] if analysis else None,
        "orbitSentinel": decision, "narrative": narrative,
        "comparison": _comparison(analysis and analysis["reality"], decision and decision.get("maneuver")),
        "assumptions": analysis["assumptions"] if analysis else [],
        "status": {"physics": physics_status, "ai": ai_status},
    })


def get_conjunction(case_id: str) -> ConjunctionDetail | None:
    """The reconstructed event as a normal ConjunctionDetail, so the existing Conjunction and
    Negotiator screens can open /conjunctions/<case id> and /negotiator/<case id> unchanged."""
    analysis, _ = _analysis(case_id) if facts.case(case_id) else (None, "")
    if not analysis:
        return None
    return ConjunctionDetail.model_validate(analysis["conjunction"])


def negotiation_inputs(case_id: str) -> tuple[dict, dict | None, dict | None, dict] | None:
    """(conjunction, sat_a, sat_b, options) for ai.negotiate(), with the 2021 spacecraft profiles."""
    analysis, _ = _analysis(case_id)
    if not analysis:
        return None
    from ..ai import incident as ai_incident
    profiles, _ = _try("ai.sat_profiles", ai_incident.sat_profiles, facts.case(case_id))
    sat_a, sat_b = profiles or (None, None)
    return get_conjunction(case_id).model_dump(), sat_a, sat_b, analysis["optionsBySide"]
