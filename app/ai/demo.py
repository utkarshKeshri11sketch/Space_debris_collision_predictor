"""The demo scenarios, mirroring frontend/src/api/mockData.ts, with ILLUSTRATIVE operator data.

Used by scripts/build_ai_cache.py and the tests. Times are anchored to `now` so "hours until closest approach"
matches the mock server, whose TCAs are also relative to when the page loads. The fuel reserve and
mission-impact figures are demo assumptions, not real telemetry.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _iso(now: datetime, hours: float) -> str:
    return (now + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _opt(now, id_, label, direction, dv, burn_h, miss, pc, kg, rec=False) -> dict:
    return {"id": id_, "label": label, "direction": direction, "dvMs": dv, "burnAt": None if burn_h is None else _iso(now, burn_h),
            "newMissM": miss, "newPc": pc, "propellantKg": kg, "recommended": rec}


def _ref(norad, name, type_="PAYLOAD", maneuverable=True) -> dict:
    return {"noradId": norad, "name": name, "type": type_, "maneuverable": maneuverable}


def scenarios(now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    iss, cosmos = _ref(25544, "ISS (ZARYA)"), _ref(50870, "COSMOS 1408 DEB", "DEBRIS", False)
    starlink, oneweb = _ref(59121, "STARLINK-31502"), _ref(48840, "ONEWEB-0461")

    def detail(id_, a, b, tca_h, miss, pc, speed, risk, options) -> dict:
        return {"id": id_, "primary": a, "secondary": b, "tca": _iso(now, tca_h), "missDistanceM": miss,
                "rtnM": {"r": round(miss * 0.31), "t": round(miss * 0.91), "n": round(miss * 0.273)}, "relSpeedKms": speed, "pc": pc,
                "risk": risk, "rangeSeries": [], "covariance": {"sigmaMajorM": 186, "sigmaMinorM": 74, "angleDeg": 32},
                "hardBodyRadiusM": 8, "options": options, "brief": ""}

    iss_cosmos = detail("iss-cosmos", iss, cosmos, 18.03, 412, 3.1e-4, 14.2, "critical", [
        _opt(now, "option-a", "A", "prograde", 0.42, 12.03, 4200, 2.3e-8, 0.18, True),
        _opt(now, "option-b", "B", "normal", 0.67, 14.03, 6800, 8.1e-10, 0.29),
        _opt(now, "no-action", "No action", "none", 0, None, 412, 3.1e-4, 0)])
    sl_ow = detail("starlink-oneweb", starlink, oneweb, 31.4, 690, 8.7e-5, 12.8, "high", [
        _opt(now, "option-a", "A", "prograde", 0.42, 25.4, 4200, 2.3e-8, 0.18, True),
        _opt(now, "option-b", "B", "normal", 0.67, 27.4, 6800, 8.1e-10, 0.29),
        _opt(now, "no-action", "No action", "none", 0, None, 690, 8.7e-5, 0)])
    return {
        "starlink-oneweb": {
            "conjunction": sl_ow,
            "sat_a": {"operator": "SpaceX (Starlink)", "can_maneuver": True, "fuel_reserve_pct": 78,
                      "mission_impact": {"score": 0.15, "note": "neighbouring satellites cover the service gap and the burn is automated"}},
            "sat_b": {"operator": "Eutelsat OneWeb", "can_maneuver": True, "fuel_reserve_pct": 41,
                      "mission_impact": {"score": 0.45, "note": "a burn interrupts a scheduled coverage window"}},
            "options": sl_ow["options"],
        },
        "iss-cosmos": {
            "conjunction": iss_cosmos,
            "sat_a": {"operator": "NASA / ISS Mission Control", "can_maneuver": True, "fuel_reserve_pct": 70,
                      "mission_impact": {"score": 0.8, "note": "a burn disrupts crew operations and needs careful planning"}},
            "sat_b": {"operator": "none (debris)", "can_maneuver": False, "fuel_reserve_pct": 0, "mission_impact": 0.0},
            "options": iss_cosmos["options"],
        },
    }


# The questions whose answers are pre-recorded for the offline demo (scripts/build_ai_cache.py).
DEMO_QUESTIONS = [
    "Why is this risky?",
    "What if we wait 6 hours?",
    "Is the ISS safe this week?",
    "Who should move, Starlink or OneWeb?",
]
