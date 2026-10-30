import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.physics.maneuver import (
    MU_KM3_S2,
    Encounter,
    collision_probability,
    cw_displacement_km,
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


def test_plan_contract_and_targets_for_critical_event():
    enc = crossing_encounter()
    plan = plan_maneuvers(enc, now=NOW)
    assert plan.current_pc >= 1e-4  # demo-like critical geometry
    opts = plan.options
    assert opts[-1]["id"] == "no-action" and opts[-1]["direction"] == "none" and opts[-1]["burnAt"] is None
    assert 2 <= len(opts) <= 4
    for o in opts:
        assert set(o) == OPTION_KEYS
    burns = opts[:-1]
    assert [o["label"] for o in burns] == list("ABC")[: len(burns)]
    assert [o["dvMs"] for o in burns] == sorted(o["dvMs"] for o in burns)
    assert len({o["direction"] for o in burns}) == len(burns)
    assert sum(o["recommended"] for o in opts) == 1 and burns[0]["recommended"]
    for o in burns:
        assert 0 < o["dvMs"] <= 5
        assert o["newPc"] <= 1e-7 and o["newMissM"] >= 1000
        burn_at = datetime.fromisoformat(o["burnAt"].replace("Z", "+00:00"))
        assert NOW + timedelta(hours=2) <= burn_at < TCA
        assert o["burnAt"].endswith("Z")
        # ISS mass makes propellant tens of kilograms for ~0.1-1 m/s.
        assert o["propellantKg"] == pytest.approx(propellant_kg(o["dvMs"], propulsion_for(25544, None)), abs=1e-3)
    assert opts[-1]["newMissM"] == pytest.approx(plan.current_miss_m, abs=0.1)
    assert plan.current_miss_m == pytest.approx(math.hypot(120, 50), abs=1)
    # afterSeries is on the rangeSeries grid. The along-track part of the burn shifts TCA by a
    # fraction of a second, and at 14 km/s the 1.5 s grid cannot resolve that shift. So the sampled
    # minimum lies between the true new miss and the miss seen from a half-step offset.
    series = plan.to_contract()["afterSeries"]
    assert len(series) == 81 and series[40]["tSec"] == 0
    new_miss_km = burns[0]["newMissM"] / 1000
    rel_speed = float(np.linalg.norm(np.asarray(enc.v_secondary_kms) - np.asarray(enc.v_primary_kms)))
    assert new_miss_km * 0.999 <= min(p["rangeKm"] for p in series) <= math.hypot(new_miss_km, rel_speed * 0.75)
    assert series[0]["rangeKm"] == pytest.approx(rel_speed * 60, rel=0.01)


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
    assert burns[0]["propellantKg"] == pytest.approx(propellant_kg(burns[0]["dvMs"], propulsion_for(50870, "COSMOS 1408 DEB")), abs=1e-3)


def test_tca_too_close_leaves_only_no_action():
    enc = crossing_encounter()
    plan = plan_maneuvers(enc, now=TCA - timedelta(hours=2, minutes=5))
    assert [o["id"] for o in plan.options] == ["no-action"]
    assert plan.options[0]["recommended"] is True


def test_propulsion_table():
    assert propulsion_for(25544, "ISS (ZARYA)").mass_kg == 420_000
    assert propulsion_for(59121, "STARLINK-31502").isp_s == 1500
    assert propulsion_for(1, "CARTOSAT-3").isp_s == 220
    assert propellant_kg(0, propulsion_for(25544, None)) == 0
