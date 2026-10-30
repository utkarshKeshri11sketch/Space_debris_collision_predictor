"""Analytic and real-SGP4 checks. All crossing orbits are synthetic fixtures."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math

import numpy as np
import pytest

from app.physics import screening as screening_module
from app.physics.screening import (
    EncounterUncertainty,
    ScreeningConfig,
    ScreeningError,
    collision_probability,
    record_from_catalog,
    rtn_basis,
    screen_catalog,
    state_at,
)

EPOCH = datetime(2026, 10, 30, tzinfo=timezone.utc)
DAY = 86400


def object_fixture(number, *, radius_km=7000, inclination=55, crossing_seconds=30):
    # Circular Keplerian rate sets an approximate node crossing. The actual
    # SGP4/J2 minimum is independently found by the screening implementation.
    motion = math.sqrt(398600.8 / radius_km**3) * DAY / (2 * math.pi)
    return {
        "noradId": number, "name": f"SYNTHETIC-{number}", "type": "PAYLOAD",
        "active": True, "maneuverable": True,
        "omm": {
            "NORAD_CAT_ID": number, "OBJECT_NAME": f"SYNTHETIC-{number}",
            "EPOCH": EPOCH.isoformat(), "MEAN_MOTION": motion,
            "ECCENTRICITY": 0, "INCLINATION": inclination, "RA_OF_ASC_NODE": 0,
            "ARG_OF_PERICENTER": 0,
            "MEAN_ANOMALY": (-motion * 360 * crossing_seconds / DAY) % 360,
            "BSTAR": 0, "MEAN_MOTION_DOT": 0, "MEAN_MOTION_DDOT": 0,
        },
    }


def crossing_catalog(crossing_seconds=30):
    return [
        object_fixture(25544, crossing_seconds=crossing_seconds),
        object_fixture(123456789, radius_km=7000.4, inclination=125,
                       crossing_seconds=crossing_seconds),
    ]


def illustrative_model(primary, secondary, tca):
    return EncounterUncertainty(
        np.diag([200**2, 400**2, 200**2]),
        np.diag([200**2, 400**2, 200**2]),
        hard_body_radius_m=10,
        source="TEST ONLY: assumed 200/400/200 m RTN sigmas, combined radius 10 m",
        illustrative=True,
    )


def screen(catalog=None, **kwargs):
    return screen_catalog(
        crossing_catalog() if catalog is None else catalog,
        25544, start=EPOCH, risk_model=illustrative_model,
        **{"days": 120 / DAY, "min_pc": 0, **kwargs},
    )


@pytest.mark.parametrize("ratio", [0.01, 0.5, 5, 100])
def test_centered_isotropic_pc_matches_exact_disk_probability(ratio):
    sigma = 50
    actual = collision_probability([0, 0], np.eye(2) * sigma**2, sigma * ratio)
    expected = -math.expm1(-0.5 * ratio**2)
    assert actual == pytest.approx(expected, rel=2e-7, abs=1e-12)


def test_anisotropic_pc_matches_independent_polar_integral_and_rotations():
    mean = np.array([120.0, -70.0])
    covariance = np.array([[40000.0, 7000.0], [7000.0, 10000.0]])
    radius = 20
    # Independent midpoint polar area integration; no reuse of the Pc
    # routine's eigenaxes, Cartesian conditional CDF, or quadrature nodes.
    angles = (np.arange(720) + 0.5) * 2 * math.pi / 720
    radii = (np.arange(300) + 0.5) * radius / 300
    points = np.stack((radii[:, None] * np.cos(angles), radii[:, None] * np.sin(angles)), axis=-1)
    offsets = points - mean
    density = np.exp(-0.5 * np.einsum("...i,ij,...j->...", offsets, np.linalg.inv(covariance), offsets))
    expected = float(np.sum(density * radii[:, None]) * (radius / 300) * (2 * math.pi / 720)
                     / (2 * math.pi * math.sqrt(np.linalg.det(covariance))))
    actual = collision_probability(mean, covariance, radius)
    assert actual == pytest.approx(expected, rel=1e-6)
    angle = 0.79
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    assert collision_probability(rotation @ mean, rotation @ covariance @ rotation.T, radius) == pytest.approx(actual, rel=1e-7)
    assert collision_probability(-mean, covariance, radius) == pytest.approx(actual, rel=1e-7)


def test_pc_retains_tiny_tail_probabilities():
    pc = collision_probability([8, 0], np.eye(2), 0.1)
    assert 1e-18 < pc < 1e-15


@pytest.mark.parametrize("matrix", [np.zeros((2, 2)), [[1, 2], [2, 1]], [[1, 0.5], [0, 1]], [[1, 0], [0, float("nan")]]])
def test_invalid_covariance_is_never_turned_into_zero_pc(matrix):
    with pytest.raises(ScreeningError):
        collision_probability([0, 0], matrix, 10)


def test_rtn_is_orthonormal_right_handed_and_uses_transverse_not_velocity():
    position = np.array([7000.0, 400.0, 200.0])
    velocity = np.array([2.0, 7.0, 1.0])  # Includes radial motion.
    basis = rtn_basis(position, velocity)
    np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-14)
    assert np.linalg.det(basis) == pytest.approx(1)
    np.testing.assert_allclose(basis @ position, [np.linalg.norm(position), 0, 0], atol=1e-12)
    assert not np.allclose(basis[1], velocity / np.linalg.norm(velocity))


def test_native_omm_matches_published_sgp4_iss_example():
    # Reference: python-sgp4 README example at 2019-12-09 20:42 UTC.
    # Rounded reference output is accurate to 0.01 km / 0.001 km/s.
    catalog = object_fixture(25544)
    catalog["omm"].update({
        "EPOCH": "2019-12-09T16:38:29.363423", "MEAN_MOTION": 15.50103472,
        "ECCENTRICITY": 0.0007417, "INCLINATION": 51.6439,
        "RA_OF_ASC_NODE": 211.2001, "ARG_OF_PERICENTER": 17.6667,
        "MEAN_ANOMALY": 85.6398, "BSTAR": 3.8792e-5,
        "MEAN_MOTION_DOT": 1.764e-5,
    })
    position, velocity = state_at(record_from_catalog(catalog), "2019-12-09T20:42:00Z")
    np.testing.assert_allclose(position, [-6088.92, -936.13, -2866.44], atol=0.01, rtol=0)
    np.testing.assert_allclose(velocity, [-1.525, -5.538, 5.068], atol=0.001, rtol=0)


@pytest.mark.parametrize("number", [25544, 100001, 339999, 340000, 123456789, 999999999])
def test_large_omm_ids_preserve_identity_without_affecting_dynamics(number):
    reference = record_from_catalog(object_fixture(25544))
    record = record_from_catalog(object_fixture(number))
    assert record.norad_id == number
    assert record.object_ref()["noradId"] == number
    np.testing.assert_array_equal(state_at(record, EPOCH), state_at(reference, EPOCH))


@pytest.mark.parametrize("mutation", [
    {"NORAD_CAT_ID": 123}, {"REF_FRAME": "GCRF"}, {"CENTER_NAME": "MARS"},
    {"TIME_SYSTEM": "TAI"}, {"MEAN_ELEMENT_THEORY": "OTHER"},
    {"ECCENTRICITY": 1.1}, {"BSTAR": float("nan")}, {"MEAN_MOTION": 0},
])
def test_conflicting_or_invalid_omm_is_rejected(mutation):
    catalog = object_fixture(25544)
    catalog["omm"].update(mutation)
    with pytest.raises(ScreeningError):
        record_from_catalog(catalog)


def test_missing_dynamic_field_is_not_silently_filled():
    catalog = object_fixture(25544)
    del catalog["omm"]["BSTAR"]
    with pytest.raises(ScreeningError, match="BSTAR"):
        record_from_catalog(catalog)


def test_omm_timezone_normalization_and_pydantic_style_input():
    catalog = object_fixture(25544)
    catalog["omm"]["EPOCH"] = "2026-10-30T05:30:00+05:30"

    class Model:
        def model_dump(self, **kwargs):
            assert kwargs == {"mode": "json", "by_alias": True}
            return catalog

    first, second = record_from_catalog(Model()), record_from_catalog(object_fixture(25544))
    assert first.epoch == EPOCH
    np.testing.assert_array_equal(state_at(first, EPOCH), state_at(second, EPOCH))


def test_fast_crossing_between_samples_is_found_and_matches_dense_reference():
    catalog = crossing_catalog()
    primary, secondary = map(record_from_catalog, catalog)
    for seconds in [0, 60]:
        at = EPOCH + timedelta(seconds=seconds)
        assert np.linalg.norm(state_at(primary, at)[0] - state_at(secondary, at)[0]) > 100
    run = screen(catalog)
    assert run.complete, run.issues
    assert len(run.encounters) == 1
    encounter = run.encounters[0]
    assert 28 < (encounter.tca - EPOCH).total_seconds() < 32
    # Independent exhaustive 10-ms SGP4 sample search over the whole minute.
    grid = np.arange(0, 60.01, 0.01)
    reference_ranges = np.array([
        np.linalg.norm(state_at(primary, EPOCH + timedelta(seconds=float(t)))[0]
                       - state_at(secondary, EPOCH + timedelta(seconds=float(t)))[0])
        for t in grid
    ])
    best = float(grid[np.argmin(reference_ranges)])
    assert abs((encounter.tca - EPOCH).total_seconds() - best) < 0.02
    assert encounter.as_conjunction()["missDistanceM"] <= reference_ranges.min() * 1000 + 1


def test_frontend_list_and_detail_contract_units_and_provenance():
    run = screen()
    event = run.conjunctions[0]
    assert set(event) == {"id", "primary", "secondary", "tca", "missDistanceM", "rtnM", "relSpeedKms", "pc", "risk"}
    for key in ["primary", "secondary"]:
        assert set(event[key]) == {"noradId", "name", "type", "maneuverable"}
    assert event["secondary"]["noradId"] == 123456789
    assert event["tca"].endswith("Z")
    assert event["missDistanceM"] == pytest.approx(math.sqrt(sum(v**2 for v in event["rtnM"].values())), rel=1e-12)
    assert 100 < event["missDistanceM"] < 2000
    assert 5 < event["relSpeedKms"] < 16
    assert 0 <= event["pc"] <= 1 and event["risk"] in {"critical", "high", "watch"}
    detail = run.get_detail(event["id"], brief="Computed assessment.")
    assert set(detail) == set(event) | {"rangeSeries", "covariance", "hardBodyRadiusM", "options", "brief"}
    assert detail["options"] == [] and detail["hardBodyRadiusM"] == 10
    assert len(detail["rangeSeries"]) == 81
    assert detail["rangeSeries"][40]["tSec"] == 0
    assert detail["rangeSeries"][40]["rangeKm"] * 1000 == pytest.approx(event["missDistanceM"], abs=1e-6)
    assert detail["rangeSeries"][0]["tSec"] == -60
    assert detail["rangeSeries"][-1]["tSec"] == 60
    assert detail["covariance"]["sigmaMajorM"] >= detail["covariance"]["sigmaMinorM"] > 0
    assert 0 <= detail["covariance"]["angleDeg"] < 180
    assert detail["brief"].startswith("Computed assessment.")
    assert "ILLUSTRATIVE" in detail["brief"] and "TEST ONLY" in detail["brief"]
    json.dumps(detail, allow_nan=False)
    with pytest.raises(KeyError):
        run.get_detail("not-in-this-run")


def test_repeat_passes_are_retained_and_ids_are_stable_across_chunks_and_batches():
    catalog = crossing_catalog()
    catalog.append(object_fixture(300001, radius_km=7100, inclination=125))
    one = screen(catalog, days=0.15,
                 config=ScreeningConfig(time_chunk_intervals=1, satellite_batch_size=1))
    two = screen(catalog, days=0.15,
                 config=ScreeningConfig(time_chunk_intervals=31, satellite_batch_size=4))
    assert one.complete and two.complete
    assert len(one.encounters) >= 3
    assert [e.id for e in one.encounters] == [e.id for e in two.encounters]
    assert one.conjunctions == two.conjunctions
    times = sorted(e.tca for e in one.encounters)
    assert all((b - a).total_seconds() > 100 for a, b in zip(times, times[1:]))
    assert [e.pc for e in one.encounters] == sorted([e.pc for e in one.encounters], reverse=True)


def test_distance_pc_and_zero_day_filters():
    assert not screen(days=0).conjunctions
    assert not screen(min_pc=1).conjunctions
    assert not screen(config=ScreeningConfig(max_miss_distance_m=1)).conjunctions


@pytest.mark.parametrize("boundary", ["start", "end"])
def test_closed_window_boundary_minima(boundary):
    # Move the window around the measured SGP4 encounter rather than assume
    # the Keplerian node-crossing estimate has no J2/short-period shift.
    actual_tca = screen().encounters[0].tca
    begin = (actual_tca + timedelta(seconds=0.5) if boundary == "start"
             else actual_tca - timedelta(seconds=120.5))
    run = screen_catalog(crossing_catalog(), 25544, start=begin, days=120 / DAY,
                         min_pc=0, risk_model=illustrative_model)
    assert run.complete, run.issues
    assert len(run.encounters) == 1
    assert run.encounters[0].tca == (begin if boundary == "start" else run.end)


def test_secondary_validation_failure_marks_run_incomplete():
    catalog = crossing_catalog()
    bad = object_fixture(555555)
    bad["omm"]["EPOCH"] = "2025-01-01T00:00:00Z"
    catalog.append(bad)
    run = screen(catalog)
    assert not run.complete
    assert len(run.encounters) == 1
    assert run.issues[0].norad_id == 555555
    assert "age limit" in run.issues[0].message


def test_mid_window_propagation_failure_is_reported_even_when_other_intervals_succeed(monkeypatch):
    real_array = screening_module.SatrecArray

    class PartiallyFailedArray:
        def __init__(self, satellites):
            self.array = real_array(satellites)

        def sgp4(self, jd, fraction):
            errors, positions, velocities = self.array.sgp4(jd, fraction)
            errors[0, -1] = 6  # SGP4 decay error after the valid first pass.
            positions[0, -1] = np.nan
            return errors, positions, velocities

    monkeypatch.setattr(screening_module, "SatrecArray", PartiallyFailedArray)
    run = screen()
    assert not run.complete and len(run.encounters) == 1
    assert any(issue.code == "propagation" and issue.norad_id == 123456789 for issue in run.issues)


def test_tca_on_chunk_boundary_is_not_duplicated():
    actual_tca = screen().encounters[0].tca
    begin = actual_tca - timedelta(seconds=60)
    run = screen_catalog(crossing_catalog(), 25544, start=begin, days=120 / DAY,
                         min_pc=0, risk_model=illustrative_model,
                         config=ScreeningConfig(time_chunk_intervals=1))
    assert run.complete and len(run.encounters) == 1
    assert abs((run.encounters[0].tca - actual_tca).total_seconds()) < 0.002


def test_primary_invalid_and_duplicate_ids_fail_entire_run():
    catalog = crossing_catalog()
    bad = deepcopy(catalog)
    bad[0]["omm"]["ECCENTRICITY"] = 2
    with pytest.raises(ScreeningError):
        screen(bad)
    with pytest.raises(ScreeningError, match="duplicate NORAD"):
        screen(catalog + [deepcopy(catalog[1])])
    with pytest.raises(ScreeningError, match="not found"):
        screen([])


def test_slow_coorbital_event_is_flagged_not_given_fake_zero_probability():
    catalog = [object_fixture(25544), object_fixture(123456)]
    run = screen(catalog)
    assert not run.complete and not run.encounters
    assert any("too low" in issue.message for issue in run.issues)


def test_explicit_uncertainty_is_required_and_provider_failures_propagate():
    with pytest.raises(TypeError, match="risk_model"):
        screen_catalog(crossing_catalog(), 25544)

    def no_data(*args):
        raise RuntimeError("No TCA covariance supplied")

    with pytest.raises(RuntimeError, match="No TCA covariance"):
        screen_catalog(crossing_catalog(), 25544, start=EPOCH, days=120 / DAY, risk_model=no_data)


@pytest.mark.parametrize("kwargs", [{"days": -1}, {"days": 8}, {"days": float("nan")},
                                     {"min_pc": -1}, {"min_pc": float("inf")}])
def test_invalid_search_parameters_fail(kwargs):
    with pytest.raises(ScreeningError):
        screen(**kwargs)


def test_naive_request_time_is_rejected():
    with pytest.raises(ScreeningError, match="UTC offset"):
        screen_catalog(crossing_catalog(), 25544, start=datetime(2026, 10, 30),
                       risk_model=illustrative_model)
