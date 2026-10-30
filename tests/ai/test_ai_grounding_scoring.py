import pytest

from app.ai import fmt
from app.ai.grounding import numbers_in, ungrounded_numbers
from app.ai.profiles import estimate_propellant_kg, profile_for
from app.ai.scoring import Candidate, criteria, decide, totals


def test_numbers_in_parses_scientific_notations_and_strips_names():
    nums = numbers_in("STARLINK-31502 Pc 3.1 × 10⁻⁴ and 2.3e-8 at 4,200 m, 0.42 m/s", ["STARLINK-31502"])
    assert nums == pytest.approx([3.1e-4, 2.3e-8, 4200.0, 0.42])
    assert 31502.0 not in nums


def test_numbers_in_ignores_iso_timestamps():
    assert numbers_in("closest approach 2026-10-31T06:00:00Z") == []


def test_grounding_accepts_unit_conversions_and_rounding():
    facts = {"missDistanceM": 4200, "pc": 2.3e-8, "dv": 0.42}
    assert not ungrounded_numbers("separation of 4.2 km, Pc 2.3 × 10⁻⁸, burn 0.4 m/s", facts)


def test_grounding_rejects_invented_numbers():
    assert ungrounded_numbers("a 0.99 m/s burn", {"dv": 0.42}) == [0.99]


def test_small_whole_numbers_are_free_unless_they_carry_a_unit():
    assert not ungrounded_numbers("round 2 of 3", {})
    assert ungrounded_numbers("a 5 m approach", {"x": 412}) == [5.0]
    assert ungrounded_numbers("burn in 3 hours", {"x": 412}) == [3.0]


def test_formatters_match_frontend():
    assert fmt.probability(3.1e-4) == "3.1 × 10⁻⁴"
    assert fmt.distance(412) == "412 m" and fmt.distance(4200) == "4.20 km"
    assert fmt.short_name("ISS (ZARYA)") == "ISS" and fmt.short_name("STARLINK-31502") == "STARLINK"


def test_rocket_equation_matches_hand_calculation():
    prof = profile_for("STARLINK-1")  # 800 kg, Isp 1500 s
    assert abs(estimate_propellant_kg(prof, 0.42) - 800 * (1 - 2.718281828 ** (-0.42 / (1500 * 9.80665)))) < 1e-6
    assert estimate_propellant_kg(prof, 0) == 0


def test_profile_override_marks_not_assumed():
    p = profile_for("STARLINK-1", {"reserveKg": 1.5})
    assert p.reserve_kg == 1.5 and p.assumed is False


def test_scores_weighted_total_and_tie_break():
    a = Candidate("A", 10, 1, 1, 0.3, 1e-8)
    b = Candidate("B", 10, 1, 1, 0.3, 1e-8)
    rows = criteria(a, b)
    assert totals(rows) == (rows and totals(rows)[0], totals(rows)[0])  # identical sides tie exactly
    assert decide(a, b, rows).reason == "tie"


def test_no_eligible_option_is_flagged():
    a = Candidate("A", 10, 1, 1, 0.3, 1e-3)
    b = Candidate("B", 10, 2, 2, 0.3, 1e-3)
    assert decide(a, b, criteria(a, b)).reason == "none-eligible"
