"""Tests for app/physics/incident.py: shapes follow docs/case_studies/CONTRACT.md and models.py."""
import math
from datetime import datetime

import pytest

from app.casestudy import facts
from app.models import ConjunctionDetail, IncidentReality, ManeuverOption
from app.physics import incident
from app.physics.maneuver import MIN_MISS_TARGET_M, PC_TARGET, Propulsion, collision_probability, propellant_kg

CASE_IDS = [c["id"] for c in facts.CASES]


@pytest.fixture(scope="module", params=CASE_IDS)
def analysis(request):
    case = facts.case(request.param)
    return case, incident.analyse(case)


def test_both_cases_build_and_have_the_contract_keys(analysis):
    _, result = analysis
    assert set(result) == {"conjunction", "optionsBySide", "reality", "assumptions"}
    assert set(result["optionsBySide"]) == {"a", "b"}


def test_conjunction_is_a_valid_frontend_detail(analysis):
    case, result = analysis
    detail = ConjunctionDetail.model_validate(result["conjunction"])
    assert detail.id == case["id"]
    assert (detail.primary.noradId, detail.secondary.noradId) == (case["station"]["noradId"], case["starlink"]["noradId"])
    assert detail.primary.maneuverable and detail.secondary.maneuverable
    assert detail.brief == ""
    assert datetime.fromisoformat(detail.tca.replace("Z", "+00:00")).date().isoformat() == case["date"]
    assert len(detail.rangeSeries) == 81 and detail.rangeSeries[0].tSec == -60 and detail.rangeSeries[-1].tSec == 60
    assert min(p.rangeKm for p in detail.rangeSeries) == pytest.approx(detail.missDistanceM / 1000, rel=0.05)
    assert detail.afterSeries and len(detail.afterSeries) == 81
    assert min(p.rangeKm for p in detail.afterSeries) > detail.missDistanceM / 1000
    assert detail.risk == "critical" and detail.pc >= 1e-4


def test_detail_numbers_are_self_consistent(analysis):
    _, result = analysis
    d = result["conjunction"]
    rtn_norm = math.sqrt(sum(v**2 for v in d["rtnM"].values()))
    assert rtn_norm == pytest.approx(d["missDistanceM"], rel=1e-3)
    cov = d["covariance"]
    assert cov["sigmaMajorM"] >= cov["sigmaMinorM"] > 0 and 0 <= cov["angleDeg"] < 180
    assert 1.0 < d["relSpeedKms"] < 15.0
    theta = math.radians(cov["angleDeg"])
    # The miss lies on the covariance major axis, so Pc recomputed from the rounded fields matches.
    pc = collision_probability(d["missDistanceM"] * math.cos(theta), d["missDistanceM"] * math.sin(theta),
                               cov["sigmaMajorM"], cov["sigmaMinorM"], cov["angleDeg"], d["hardBodyRadiusM"])
    assert pc == pytest.approx(d["pc"], rel=0.05)


def test_options_by_side_shapes_and_costs(analysis):
    _, result = analysis
    for side in ("a", "b"):
        opts = result["optionsBySide"][side]
        for o in opts:
            ManeuverOption.model_validate(o)
        burns = [o for o in opts if o["direction"] != "none"]
        assert 3 <= len(burns) <= 4
        assert opts[-1]["id"] == "no-action" and opts[-1]["propellantKg"] == 0.0
        assert sum(o["recommended"] for o in opts) == 1
        for o in burns:
            assert o["dvMs"] > 0 and o["propellantKg"] > 0
            assert o["newPc"] <= PC_TARGET * 1.001 and o["newMissM"] >= MIN_MISS_TARGET_M
    assert result["conjunction"]["options"] == result["optionsBySide"]["a"]


def test_propellant_matches_the_rocket_equation(analysis):
    _, result = analysis
    station = Propulsion(result["reality"]["massKg"], result["reality"]["ispS"], "")
    starlink = Propulsion(incident.STARLINK_KG, incident.STARLINK_ISP_S, "")
    for side, prop in (("a", station), ("b", starlink)):
        for o in result["optionsBySide"][side]:
            assert o["propellantKg"] == pytest.approx(propellant_kg(o["dvMs"], prop), rel=1e-3)


def test_starlink_burn_costs_far_less_propellant_than_the_station(analysis):
    _, result = analysis
    cheapest = {s: min(o["propellantKg"] for o in result["optionsBySide"][s] if o["direction"] != "none") for s in "ab"}
    assert cheapest["b"] * 100 < cheapest["a"]


def test_reality_is_the_cheapest_station_burn(analysis):
    case, result = analysis
    reality = IncidentReality.model_validate(result["reality"])
    station_burns = [o for o in result["optionsBySide"]["a"] if o["direction"] != "none"]
    assert reality.moverNoradId == case["station"]["noradId"]
    assert reality.dvMs == min(o["dvMs"] for o in station_burns) > 0
    assert reality.propellantKg > 0 and reality.ispS == incident.STATION_ISP_S
    assert reality.propellantKg == pytest.approx(
        propellant_kg(reality.dvMs, Propulsion(reality.massKg, reality.ispS, "")), rel=1e-3)
    assert "Reconstructed" in reality.basis


def test_station_mass_differs_between_july_and_october():
    july, october = (incident.analyse(c)["reality"]["massKg"] for c in facts.CASES)
    assert 43_000 < july < 45_000 and 56_000 < october < 58_000


def test_assumptions_cover_the_modelled_numbers(analysis):
    _, result = analysis
    text = " ".join(result["assumptions"]).lower()
    for needle in ("tca", "covariance", "hard-body", "miss distance", "mass", "isp", "starlink", "reality"):
        assert needle in text
    assert all(isinstance(a, str) and a for a in result["assumptions"])


def test_analysis_is_deterministic():
    case = facts.CASES[0]
    assert incident.analyse(case) == incident.analyse(case)


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError):
        incident.analyse({**facts.CASES[0], "id": "case-unknown"})
