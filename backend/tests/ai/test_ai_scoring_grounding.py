import pytest

from app.ai import fmt
from app.ai.generate import clean, problems
from app.ai.grounding import numbers_in, ungrounded_numbers
from app.ai.profiles import estimate_propellant_kg, profile_for
from app.ai.satinfo import build_sat
from app.ai.scoring import TARGET_PC, WEIGHTS, Candidate, criteria, decide, evaluate_split, totals


# ---- scores are computed in Python, with the spec's weights --------------------------------------


def test_weights_are_the_spec_and_sum_to_one():
    assert WEIGHTS == [("Propellant reserve", 0.35), ("Maneuver cost", 0.25), ("Mission impact", 0.20), ("Delta-v", 0.20)]
    assert sum(w for _, w in WEIGHTS) == pytest.approx(1.0)


def test_scores_for_a_hand_checked_example():
    a = Candidate("A", fuel_after_pct=60, propellant_kg=0.2, dv_ms=0.4, mission_impact=0.1, new_pc=1e-8)
    b = Candidate("B", fuel_after_pct=30, propellant_kg=0.1, dv_ms=0.8, mission_impact=0.5, new_pc=1e-8)
    rows = {r["name"]: r for r in criteria(a, b)}
    assert (rows["Propellant reserve"]["a"], rows["Propellant reserve"]["b"]) == (100, 50)   # 60/60, 30/60
    assert (rows["Maneuver cost"]["a"], rows["Maneuver cost"]["b"]) == (50, 100)             # 0.1/0.2, 0.1/0.1
    assert (rows["Mission impact"]["a"], rows["Mission impact"]["b"]) == (90, 50)
    assert (rows["Delta-v"]["a"], rows["Delta-v"]["b"]) == (100, 50)
    ta, tb = totals(criteria(a, b))
    assert ta == pytest.approx(0.35 * 100 + 0.25 * 50 + 0.20 * 90 + 0.20 * 100)  # 85.5
    assert tb == pytest.approx(0.35 * 50 + 0.25 * 100 + 0.20 * 50 + 0.20 * 50)   # 62.5
    assert decide(a, b, criteria(a, b)).mover == "A"


def test_every_score_is_normalised_0_to_100():
    a = Candidate("A", 0, 5.0, 3.0, 1.0, 1e-8)
    b = Candidate("B", 90, 0.0, 0.0, 0.0, 1e-8)
    assert all(0 <= r[k] <= 100 for r in criteria(a, b) for k in ("a", "b"))


def test_tie_goes_to_the_side_with_more_fuel_left():
    a = Candidate("A", 50, 1, 1, 0.3, 1e-8)
    b = Candidate("B", 50, 1, 1, 0.3, 1e-8)
    d = decide(a, b, criteria(a, b))
    assert d.reason == "tie" and d.mover == "A"
    assert decide(Candidate("A", 40, 1, 1, 0.3, 1e-8), b, criteria(Candidate("A", 40, 1, 1, 0.3, 1e-8), b)).mover == "B"


def test_option_that_misses_the_target_pc_loses_regardless_of_score():
    good = Candidate("A", 10, 9.0, 9.0, 0.9, TARGET_PC / 10)
    bad = Candidate("B", 90, 0.1, 0.1, 0.0, TARGET_PC * 100)
    d = decide(good, bad, criteria(good, bad))
    assert d.mover == "A" and d.reason == "only-eligible"


def test_neither_eligible_is_flagged():
    a, b = Candidate("A", 50, 1, 1, 0.3, 1e-3), Candidate("B", 50, 2, 2, 0.3, 1e-3)
    assert decide(a, b, criteria(a, b)).reason == "none-eligible"


# ---- split burn ------------------------------------------------------------------------------------


def test_split_burn_wins_when_a_single_burn_would_drain_a_tank():
    sp = evaluate_split(prop_a=0.9, prop_b=0.9, fuel_kg_a=1.2, fuel_kg_b=1.2, impact_a=0.05, impact_b=0.05, single_mover="A")
    assert sp is not None and sp.share_a == pytest.approx(0.5) and sp.cost_split < sp.cost_best_single


def test_no_split_when_the_burn_is_cheap_or_impacts_are_high():
    assert evaluate_split(0.1, 0.1, 10, 10, 0.05, 0.05, "A") is None            # under the 25% trigger
    assert evaluate_split(0.9, 0.9, 1.2, 1.2, 0.5, 0.5, "A") is None            # two interruptions cost more than they save


# ---- satellite inputs ------------------------------------------------------------------------------


def test_missing_inputs_are_filled_and_flagged_as_assumed():
    s = build_sat({"fuel_reserve_pct": 80}, {"noradId": 1, "name": "STARLINK-1", "type": "PAYLOAD", "maneuverable": True})
    assert s.fuel_pct == 80 and "STARLINK-1 mission impact" in s.assumed and "STARLINK-1 fuel reserve" not in s.assumed
    assert profile_for("ONEWEB-0461").mission_impact == 0.45


def test_mission_impact_accepts_float_note_or_dict():
    ref = {"noradId": 1, "name": "X", "maneuverable": True}
    assert build_sat({"mission_impact": 0.2}, ref).mission_impact == 0.2
    assert build_sat({"mission_impact": {"score": 0.7, "note": "imaging pass"}}, ref).mission_note == "imaging pass"
    assert build_sat({"mission_impact": "imaging pass in 3 hours"}, ref).mission_note == "imaging pass in 3 hours"


def test_rocket_equation():
    p = profile_for("STARLINK-1")
    import math
    assert estimate_propellant_kg(p, 0.42) == pytest.approx(800 * (1 - math.exp(-0.42 / (1500 * 9.80665))))
    assert estimate_propellant_kg(p, 0) == 0


# ---- grounding -------------------------------------------------------------------------------------


def test_numbers_in_parses_scientific_notation_and_strips_names():
    nums = numbers_in("STARLINK-31502 Pc 3.1 × 10⁻⁴ and 2.3e-8 at 4,200 m, 0.42 m/s", ["STARLINK-31502"])
    assert nums == pytest.approx([3.1e-4, 2.3e-8, 4200.0, 0.42])
    assert numbers_in("closest approach 2026-10-31T06:00:00Z") == []
    assert numbers_in("a 4 200 m miss") == [4200.0]  # thin-space thousands separators


def test_grounding_accepts_unit_conversion_and_rejects_invented_numbers():
    facts = {"missDistanceM": 4200, "pc": 2.3e-8, "dv": 0.42}
    assert not ungrounded_numbers("separation of 4.2 km, Pc 2.3 × 10⁻⁸, burn 0.4 m/s", facts)
    assert ungrounded_numbers("a 0.99 m/s burn", {"dv": 0.42}) == [0.99]


def test_numbers_quoted_inside_fact_strings_count_as_facts():
    assert not ungrounded_numbers("an imaging pass in 3 hours", {"note": "imaging pass in 3 hours"})


def test_small_whole_numbers_are_free_unless_they_carry_a_unit():
    assert not ungrounded_numbers("round 2 of 3", {})
    assert ungrounded_numbers("a 5 m approach", {"x": 412}) == [5.0]
    assert ungrounded_numbers("burn in 3 hours", {"x": 412}) == [3.0]


def test_problems_flags_truncation_missing_content_and_long_text():
    facts = {"n": 1.5}
    assert problems("It was cut off mid", facts, []) == ["the answer was cut off; finish the last sentence"]
    assert problems("Fine.", facts, [], must_include=["human"]) == ["it must mention: human"]
    assert any("longer than" in p for p in problems("word " * 130 + ".", facts, []))
    assert problems("A human decides.", facts, [], must_include=["human"]) == []


def test_clean_fixes_odd_unicode_and_role_prefixes():
    assert clean("**Agent A:** STARLINK‑31502 has 78 % fuel") == "STARLINK-31502 has 78 % fuel"


def test_formatters_match_the_frontend():
    assert fmt.probability(3.1e-4) == "3.1 × 10⁻⁴" and fmt.odds(3.1e-4) == "1 in 3,226"
    assert fmt.distance(412) == "412 m" and fmt.distance(4200) == "4.20 km"
    assert fmt.short_name("ISS (ZARYA)") == "ISS" and fmt.short_name("STARLINK-31502") == "STARLINK"
