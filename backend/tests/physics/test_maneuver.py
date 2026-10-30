import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.physics.maneuver import (
    MU_KM3_S2,
    Encounter,
    collision_probability,
    cw_displacement_km,
    encounter_from_detail,
    encounter_from_screening,
    encounter_plane_basis,
    options,
    options_for,
    plan_for_detail,
    plan_maneuvers,
    propellant_kg,
    propulsion_for,
    rtn_basis,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
TCA = NOW + timedelta(hours=18)
OPTION_KEYS = {"id", "label", "direction", "dvMs", "burnAt", "newMissM", "newPc", "propellantKg", "recommended"}


def crossing_encounter(miss_r_km=0.12, miss_other_km=0.05, sigma=(186.0, 74.0, 32.0), hbr=58.0):
    """ISS-like primary (418 km, 51.64 deg) crossing a retrograde-crossing debris orbit (82.5 deg)
    at the primary's ascending node, giving ~14 km/s relative speed like the iss-cosmos demo."""
    r = 6378.137 + 418.0
    v = math.sqrt(MU_KM3_S2 / r)
    ip, is_ = math.radians(51.64), math.radians(82.5)
    rp = np.array([r, 0.0, 0.0])
    vp = v * np.array([0.0, math.cos(ip), math.sin(ip)])
    vs = v * np.array([0.0, math.cos(is_), -math.sin(is_)])
    w = (vs - vp) / np.linalg.norm(vs - vp)
    other = np.cross(w, [1.0, 0.0, 0.0])  # in-plane axis perpendicular to radial and v_rel
    rs = rp + miss_r_km * np.array([1.0, 0.0, 0.0]) + miss_other_km * other
    return Encounter(TCA, rp, vp, rs, vs, *sigma, hbr, primary_norad_id=25544, primary_name="ISS (ZARYA)",
                     secondary_norad_id=50870, secondary_name="COSMOS 1408 DEB")


def test_pc_matches_closed_form_for_centred_isotropic_case():
    # Zero miss, circular covariance: Pc = 1 - exp(-R^2 / (2 sigma^2)) exactly.
    for sigma, radius in [(100.0, 20.0), (50.0, 58.0), (300.0, 5.0)]:
        expected = 1 - math.exp(-radius**2 / (2 * sigma**2))
        assert collision_probability(0, 0, sigma, sigma, 0, radius) == pytest.approx(expected, rel=1e-6)


def test_pc_offset_matches_small_body_approximation_and_is_rotation_consistent():
    # For HBR << sigma: Pc ~ pi R^2 * gaussian density at the miss point.
    sx, sy, R = 400.0, 150.0, 2.0
    mx, my = 500.0, 100.0
    density = math.exp(-0.5 * ((mx / sx) ** 2 + (my / sy) ** 2)) / (2 * math.pi * sx * sy)
    assert collision_probability(mx, my, sx, sy, 0, R) == pytest.approx(math.pi * R**2 * density, rel=1e-3)
    # Rotating both the miss vector and the ellipse by the same angle must not change Pc.
    a = math.radians(40)
    rx, ry = mx * math.cos(a) - my * math.sin(a), mx * math.sin(a) + my * math.cos(a)
    assert collision_probability(rx, ry, sx, sy, 40, R) == pytest.approx(collision_probability(mx, my, sx, sy, 0, R), rel=1e-9)


def test_pc_far_tail_is_small_but_positive():
    pc = collision_probability(5000, 0, 186, 74, 0, 58)
    assert 0 < pc < 1e-100 or pc == 0.0  # underflows gracefully, never negative or NaN
    assert collision_probability(1500, 0, 186, 74, 0, 58) < 1e-7


def _two_body_rk4(r, v, dt, steps=4000):
    def acc(x):
        return -MU_KM3_S2 * x / np.linalg.norm(x) ** 3
    h = dt / steps
    for _ in range(steps):
        k1r, k1v = v, acc(r)
        k2r, k2v = v + 0.5 * h * k1v, acc(r + 0.5 * h * k1r)
        k3r, k3v = v + 0.5 * h * k2v, acc(r + 0.5 * h * k2r)
        k4r, k4v = v + h * k3v, acc(r + h * k3r)
        r = r + h / 6 * (k1r + 2 * k2r + 2 * k3r + k4r)
        v = v + h / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
    return r, v


@pytest.mark.parametrize("axis", [(0, 1, 0), (1, 0, 0), (0, 0, 1)])
def test_cw_matches_numerical_two_body(axis):
    r0 = np.array([6378.137 + 418.0, 0.0, 0.0])
    v0 = math.sqrt(MU_KM3_S2 / r0[0]) * np.array([0.0, math.cos(0.9), math.sin(0.9)])
    n = math.sqrt(MU_KM3_S2 / r0[0] ** 3)
    dt = 1.6 * 2 * math.pi / n  # 1.6 orbits: not a node of any CW component
    dv_rtn = np.array(axis, float) * 0.5e-3  # 0.5 m/s
    ref_r, ref_v = _two_body_rk4(r0, v0, dt)
    burn_r, _ = _two_body_rk4(r0, v0 + rtn_basis(r0, v0).T @ dv_rtn, dt)
    numeric = rtn_basis(ref_r, ref_v) @ (burn_r - ref_r)
    predicted = cw_displacement_km(n, dt, dv_rtn)
    assert np.linalg.norm(numeric - predicted) < 0.01 * np.linalg.norm(numeric) + 1e-4


def _burn_time(option):
    return datetime.fromisoformat(option["burnAt"].replace("Z", "+00:00"))


def test_plan_contract_and_targets_for_critical_event():
    enc = crossing_encounter()
    plan = plan_maneuvers(enc, now=NOW)
    assert plan.current_pc >= 1e-4  # demo-like critical geometry
    opts = plan.options
    assert opts[-1]["id"] == "no-action" and opts[-1]["direction"] == "none" and opts[-1]["burnAt"] is None
    for o in opts:
        assert set(o) == OPTION_KEYS
    burns = opts[:-1]
    # Role brief: 3-4 prograde/retrograde options at different lead times, plus "do nothing".
    assert 3 <= len(burns) <= 4
    assert [o["label"] for o in burns] == list("ABCD")[: len(burns)]
    assert [o["id"] for o in burns] == [f"option-{x}" for x in "abcd"[: len(burns)]]
    assert {o["direction"] for o in burns} == {"prograde", "retrograde"}
    a, b, c, *rest = burns
    assert a["direction"] != b["direction"] and a["dvMs"] <= b["dvMs"]  # A: cheaper direction, nominal lead
    assert c["direction"] == a["direction"] and _burn_time(c) < _burn_time(a)  # C: early burn
    assert c["dvMs"] <= a["dvMs"]  # earlier burns need less delta-v
    if rest:
        d = rest[0]
        assert d["direction"] == a["direction"] and _burn_time(d) > _burn_time(a) and d["dvMs"] >= a["dvMs"]
    assert sum(o["recommended"] for o in opts) == 1 and a["recommended"]
    for o in burns:
        assert 0 < o["dvMs"] <= 5
        assert o["newPc"] <= 1e-7 and o["newMissM"] >= 1000
        assert NOW + timedelta(hours=2) <= _burn_time(o) < TCA
        assert TCA - _burn_time(o) <= timedelta(hours=24)
        assert o["burnAt"].endswith("Z")
        assert o["propellantKg"] == pytest.approx(propellant_kg(o["dvMs"], propulsion_for(25544, None)), rel=1e-3)
    assert opts[-1]["newMissM"] == pytest.approx(plan.current_miss_m, abs=0.1)
    assert plan.current_miss_m == pytest.approx(math.hypot(120, 50), abs=1)
    # afterSeries is on the rangeSeries grid. The along-track part of the burn shifts TCA by a
    # fraction of a second, and at 14 km/s the 1.5 s grid cannot resolve that shift. So the sampled
    # minimum lies between the true new miss and the miss seen from a half-step offset.
    series = plan.to_contract()["afterSeries"]
    assert len(series) == 81 and series[40]["tSec"] == 0
    new_miss_km = a["newMissM"] / 1000
    rel_speed = float(np.linalg.norm(np.asarray(enc.v_secondary_kms) - np.asarray(enc.v_primary_kms)))
    assert new_miss_km * 0.999 <= min(p["rangeKm"] for p in series) <= math.hypot(new_miss_km, rel_speed * 0.75)
    assert series[0]["rangeKm"] == pytest.approx(rel_speed * 60, rel=0.01)


def test_plan_is_deterministic():
    enc = crossing_encounter()
    assert plan_maneuvers(enc, now=NOW).options == plan_maneuvers(enc, now=NOW).options


def test_low_pc_recommends_no_action_but_still_lists_burns():
    enc = crossing_encounter(miss_r_km=1.6, miss_other_km=0.9)
    plan = plan_maneuvers(enc, now=NOW)
    assert plan.current_pc < 1e-4
    assert plan.options[-1]["recommended"] is True
    assert not any(o["recommended"] for o in plan.options[:-1])
    assert "afterSeries" not in plan.to_contract()
    # The event already meets the targets, so burns show the cost of doubling the miss, never 0 m/s.
    for o in plan.options[:-1]:
        assert o["dvMs"] > 0 and o["newMissM"] >= 2 * plan.current_miss_m - 1


def test_secondary_mover_uses_its_own_propulsion():
    enc = crossing_encounter()
    plan = plan_maneuvers(enc, now=NOW, mover="secondary")
    burns = plan.options[:-1]
    assert burns and all(o["newPc"] <= 1e-7 for o in burns)
    # Default 500 kg / 220 s spacecraft burns far less than the ISS for the same dv.
    expected = propellant_kg(burns[0]["dvMs"], propulsion_for(50870, "COSMOS 1408 DEB"))
    assert burns[0]["propellantKg"] == pytest.approx(expected, rel=1e-3)


def test_tca_too_close_leaves_only_no_action():
    enc = crossing_encounter()
    plan = plan_maneuvers(enc, now=TCA - timedelta(hours=2, minutes=5))
    assert [o["id"] for o in plan.options] == ["no-action"]
    assert plan.options[0]["recommended"] is True


def test_propulsion_table():
    assert propulsion_for(25544, "ISS (ZARYA)").mass_kg == 420_000
    assert propulsion_for(59121, "STARLINK-31502").isp_s == 1500
    assert propulsion_for(1, "CARTOSAT-3").isp_s == 220 and propulsion_for(1, "CARTOSAT-3").mass_kg == 1000
    assert propulsion_for(48840, "ONEWEB-0461").isp_s == 1600  # same as app/ai/profiles.py
    assert propulsion_for(1, "UNKNOWN SAT").mass_kg == 500
    assert propellant_kg(0, propulsion_for(25544, None)) == 0


# --- Adapters from the contract (ConjunctionDetail) ---------------------------------------------
def _ref(norad, name, maneuverable=True, kind="PAYLOAD"):
    return {"noradId": norad, "name": name, "type": kind, "maneuverable": maneuverable}


def _detail(primary, secondary, miss=150.0, pc=3.1e-4, speed=14.2, tca_h=18.0):
    return {
        "id": "test-event", "primary": primary, "secondary": secondary,
        "tca": (NOW + timedelta(hours=tca_h)).isoformat().replace("+00:00", "Z"),
        "missDistanceM": miss, "rtnM": {"r": round(miss * 0.31), "t": round(miss * 0.91), "n": round(miss * 0.273)},
        "relSpeedKms": speed, "pc": pc, "risk": "critical",
        "rangeSeries": [{"tSec": (i - 40) * 1.5, "rangeKm": 0.0} for i in range(81)],
        "covariance": {"sigmaMajorM": 186, "sigmaMinorM": 74, "angleDeg": 32}, "hardBodyRadiusM": 58,
        "options": [], "brief": "",
    }


ISS = _ref(25544, "ISS (ZARYA)")
COSMOS = _ref(50870, "COSMOS 1408 DEB", False, "DEBRIS")
STARLINK = _ref(59121, "STARLINK-31502")
ONEWEB = _ref(48840, "ONEWEB-0461")


def test_encounter_from_detail_reproduces_contract_geometry():
    d = _detail(ISS, COSMOS, miss=412.0)
    enc = encounter_from_detail(d, primary_omm={"MEAN_MOTION": 15.5})
    v_rel = np.asarray(enc.v_secondary_kms) - np.asarray(enc.v_primary_kms)
    assert np.linalg.norm(v_rel) == pytest.approx(14.2, rel=1e-6)
    assert abs(v_rel[0]) < 1e-12  # horizontal relative velocity (no radial part)
    rel = (np.asarray(enc.r_secondary_km) - np.asarray(enc.r_primary_km)) * 1000
    np.testing.assert_allclose(rel, [round(412 * 0.31), round(412 * 0.91), round(412 * 0.273)])
    n = 15.5 * 2 * math.pi / 86400
    assert np.linalg.norm(enc.r_primary_km) == pytest.approx((MU_KM3_S2 / n**2) ** (1 / 3))
    assert enc.range_t_sec[0] == -60 and enc.tca == TCA


def test_options_from_detail_use_screening_numbers_for_no_action():
    opts = options(_detail(ISS, COSMOS), now=NOW)
    assert opts[-1] == {"id": "no-action", "label": "No action", "direction": "none", "dvMs": 0.0, "burnAt": None,
                        "newMissM": 150.0, "newPc": 3.1e-4, "propellantKg": 0.0, "recommended": False}
    assert opts[0]["recommended"] and opts[0]["direction"] in ("prograde", "retrograde")
    plan = plan_for_detail(_detail(ISS, COSMOS), now=NOW)
    assert set(plan.to_contract()) == {"options", "afterSeries"}


def test_options_for_each_negotiating_operator():
    d = _detail(STARLINK, ONEWEB, miss=690.0, pc=8.7e-5, speed=12.8, tca_h=31.4)
    a = options_for(d, 59121, now=NOW)
    b = options_for(d, 48840, now=NOW)
    assert len(a) >= 4 and len(b) >= 4
    # Below the 1e-4 threshold: burns are listed, "No action" is recommended.
    assert a[-1]["recommended"] and b[-1]["recommended"]
    # Mirror geometry: similar delta-v, but each side's propellant follows its own mass/Isp.
    assert a[0]["dvMs"] == pytest.approx(b[0]["dvMs"], abs=0.011)
    starlink, oneweb = propulsion_for(59121, "STARLINK-31502"), propulsion_for(48840, "ONEWEB-0461")
    assert a[0]["propellantKg"] == pytest.approx(propellant_kg(a[0]["dvMs"], starlink), rel=1e-3)
    assert b[0]["propellantKg"] == pytest.approx(propellant_kg(b[0]["dvMs"], oneweb), rel=1e-3)
    assert b[0]["propellantKg"] > 0  # grams, never rounded to zero


def test_encounter_plane_axes_match_screening_convention():
    # Same convention as app/physics/screening.py: x = projected primary radial, y = v_rel_hat x x.
    # LEO crossings have v_rel with a negative along-track part, so y must come out close to +N
    # (the frontend draws N upwards). The old x cross v_rel convention gave -N and mirrored the ellipse.
    enc = crossing_encounter()
    rp, vp = np.asarray(enc.r_primary_km), np.asarray(enc.v_primary_kms)
    v_rel = np.asarray(enc.v_secondary_kms) - vp
    assert np.dot(v_rel, rtn_basis(rp, vp)[1]) < 0
    x, y = encounter_plane_basis(rp / np.linalg.norm(rp), v_rel)
    w = v_rel / np.linalg.norm(v_rel)
    np.testing.assert_allclose(y, np.cross(w, x))
    assert np.dot(y, rtn_basis(rp, vp)[2]) > 0.5


def test_encounter_from_screening_duck_types_screening_output():
    enc = crossing_encounter()

    class Record:
        def __init__(self, norad_id, name):
            self.norad_id, self.catalog = norad_id, {"name": name}

    class Uncertainty:
        hard_body_radius_m = 58.0

    class Screened:  # attribute names of app.physics.screening.Encounter
        tca = enc.tca
        primary, secondary = Record(25544, "ISS (ZARYA)"), Record(50870, "COSMOS 1408 DEB")
        primary_position_km, primary_velocity_km_s = enc.r_primary_km, enc.v_primary_kms
        secondary_position_km, secondary_velocity_km_s = enc.r_secondary_km, enc.v_secondary_kms
        covariance = {"sigmaMajorM": 186.0, "sigmaMinorM": 74.0, "angleDeg": 32.0}
        uncertainty = Uncertainty()

    converted = encounter_from_screening(Screened())
    assert plan_maneuvers(converted, now=NOW).options == plan_maneuvers(enc, now=NOW).options
    assert converted.primary_name == "ISS (ZARYA)" and len(converted.range_t_sec) == 81


def test_non_maneuverable_mover_and_unknown_id():
    d = _detail(ISS, COSMOS)
    debris_only = options_for(d, 50870, now=NOW)
    assert [o["id"] for o in debris_only] == ["no-action"] and debris_only[0]["recommended"] is True
    # Debris primary, maneuverable secondary: the default mover is the secondary.
    plan = plan_for_detail(_detail(COSMOS, ISS), now=NOW)
    assert plan.mover == "secondary" and len(plan.options) >= 4
    with pytest.raises(ValueError):
        options_for(d, 12345, now=NOW)
