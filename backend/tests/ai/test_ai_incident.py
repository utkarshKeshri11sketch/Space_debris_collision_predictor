"""Case-study AI layer against a contract-shaped stand-in for Physics' analyse() (TEST NUMBERS ONLY)."""
import json
import os

os.environ.setdefault("SCREENING_WARMUP", "0")
os.environ.setdefault("AI_NEGOTIATION_PACE_S", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai import incident  # noqa: E402
from app.casestudy import facts, service  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CaseStudy, NegotiationEvent  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

CASE = facts.CASES[0]


def _option(id_, direction, dv, kg, miss, pc, rec=False, burn="2021-07-01T06:00:00Z"):
    return {"id": id_, "label": id_, "direction": direction, "dvMs": dv, "burnAt": burn,
            "newMissM": miss, "newPc": pc, "propellantKg": kg, "recommended": rec}


def fake_analysis(case=CASE):
    """Synthetic numbers in the contract shape; real values come from app/physics/incident.py."""
    series = [{"tSec": (i - 40) * 1.5, "rangeKm": 1.0 + abs(i - 40) * 0.1} for i in range(81)]
    none = _option("no-action", "none", 0, 0, 900, 3e-5, burn=None)
    return {
        "conjunction": {
            "id": case["id"], "tca": "2021-07-01T12:00:00Z", "missDistanceM": 900, "rtnM": {"r": 300, "t": 800, "n": 250},
            "relSpeedKms": 9.5, "pc": 3e-5, "risk": "high",
            "primary": {"noradId": 48274, "name": "CSS (TIANHE)", "type": "PAYLOAD", "maneuverable": True},
            "secondary": {"noradId": case["starlink"]["noradId"], "name": case["starlink"]["name"], "type": "PAYLOAD", "maneuverable": True},
            "rangeSeries": series, "afterSeries": series, "covariance": {"sigmaMajorM": 500, "sigmaMinorM": 200, "angleDeg": 30},
            "hardBodyRadiusM": 30, "options": [_option("a1", "retrograde", 0.3, 4.4, 4000, 5e-8, True), none], "brief": "",
        },
        "optionsBySide": {"a": [_option("a1", "retrograde", 0.3, 4.4, 4000, 5e-8, True), none],
                          "b": [_option("b1", "prograde", 0.3, 0.0053, 4000, 5e-8, True), none]},
        "reality": {"moverNoradId": 48274, "dvMs": 0.3, "propellantKg": 4.4, "massKg": 44000, "ispS": 300,
                    "basis": "TEST: minimum burn reaching the planner's target"},
        "assumptions": ["TEST fixture"],
    }


@pytest.fixture()
def api(monkeypatch):
    from app.physics import incident as physics_incident
    monkeypatch.setattr(physics_incident, "analyse", lambda case: fake_analysis(case))
    service._ANALYSES.clear()
    yield TestClient(app)
    service._ANALYSES.clear()


def test_recommend_matches_mediator_and_prefers_cheap_mover():
    analysis = fake_analysis()
    sat_a, sat_b = incident.sat_profiles(CASE, analysis)
    decision = incident.recommend(analysis["conjunction"], analysis["optionsBySide"], sat_a, sat_b)
    assert decision["moverSide"] == "b" and decision["moverNoradId"] == CASE["starlink"]["noradId"]
    assert [c["weight"] for c in decision["criteria"]] == [0.35, 0.25, 0.2, 0.2]
    assert decision["alternative"]["propellantKg"] == 4.4


def test_narrative_uses_only_computed_numbers():
    analysis = fake_analysis()
    decision = incident.recommend(analysis["conjunction"], analysis["optionsBySide"], *incident.sat_profiles(CASE, analysis))
    text = incident.narrate(CASE, analysis, decision)
    assert set(text) == {"reality", "orbitSentinel", "brief"}
    assert "830" in text["orbitSentinel"]  # 4.4 / 0.0053 = 830x, from the inputs only
    assert "human" in text["brief"].lower()


def test_case_study_endpoint_ready(api):
    body = CaseStudy.model_validate(api.get(f"/api/case-studies/{CASE['id']}").json())
    assert body.status.physics == "ready" and body.status.ai == "ready"
    assert body.comparison.propellantRatio == pytest.approx(4.4 / 0.0053)


def test_case_replays_through_live_negotiation(api):
    assert api.get(f"/api/conjunctions/{CASE['id']}").status_code == 200
    started = api.post("/api/negotiations", json={"conjunctionId": CASE["id"]})
    assert started.status_code == 201
    text = api.get(f"/api/negotiations/{started.json()['negotiationId']}/stream").text
    events = [json.loads(b[6:]) for b in text.split("\n\n") if b.startswith("data: {")]
    parsed = [TypeAdapter(NegotiationEvent).validate_python(e) for e in events]
    assert parsed[-1].type == "agreement" and parsed[-1].mover.noradId == CASE["starlink"]["noradId"]


def test_pending_until_physics_delivers():
    service._ANALYSES.clear()
    body = TestClient(app).get(f"/api/case-studies/{CASE['id']}").json()
    if body["status"]["physics"] == "pending":
        assert body["conjunction"] is None and body["comparison"] is None
