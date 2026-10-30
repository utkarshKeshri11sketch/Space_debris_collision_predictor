import math

import numpy as np
import pytest

from app.physics import cascade as c
from catalog_fixture import NAMED, make_catalog

YEAR_KEYS = {"year", "trackedTotal", "baselineTotal", "extraConjunctionsPct", "satellitesAtRisk"}
EVENT_KEYS = {"year", "latDeg", "lonDeg", "altKm", "fragments"}


@pytest.fixture(scope="module")
def catalog():
    return make_catalog(8000)


@pytest.fixture(scope="module")
def env(catalog):
    return c.build_environment(catalog)


def named(name):
    return next(o for o in NAMED if o["name"] == name)


# --- NSBM ---------------------------------------------------------------------------------------
def test_nsbm_yields():
    assert c.explosion_fragment_yield() == pytest.approx(6 * 10**1.6, rel=1e-9)  # ~239
    # 10 kg at 10 km/s on the 8.9 t SL-16: EMR = 56 J/g, so catastrophic with M = 8910 kg.
    assert c.collision_fragment_yield(10, 8900) == pytest.approx(0.1 * 8910**0.75 * 0.1**-1.71, rel=1e-9)
    # A 30 g fragment on an 800 kg satellite is non-catastrophic: M = m * v^2 = 3 kg.
    assert c.collision_fragment_yield(0.03, 800) == pytest.approx(0.1 * 3**0.75 * 0.1**-1.71, rel=1e-9)
    np.testing.assert_allclose(c.collision_fragment_yield(np.array([10.0, 0.03]), 800),
                               [c.collision_fragment_yield(10.0, 800), c.collision_fragment_yield(0.03, 800)])


def test_fragment_sampling_respects_size_range_and_mass_budget():
    frags = c.sample_fragments(np.random.default_rng(1), 5000, "collision", True, mass_budget_kg=1e9)
    assert frags.lc_m.size == 5000
    assert frags.lc_m.min() >= c.LC_MIN_M and frags.lc_m.max() <= c.LC_MAX_M
    assert np.median(frags.lc_m) < 0.2  # power law: most fragments sit near the 10 cm floor
    assert 50 < np.median(frags.dv_ms) < 600  # NSBM collision kicks: ~100 m/s scale
    small = c.sample_fragments(np.random.default_rng(2), 239, "explosion", False, mass_budget_kg=1.0)
    assert small.mass_kg.sum() <= 1.0 or small.mass_kg.size == 1


# --- Atmosphere and decay -----------------------------------------------------------------------
def test_atmosphere_matches_table_and_is_monotonic():
    rho, scale = c.atmosphere(np.array([400.0, 800.0]))
    assert rho[0] == pytest.approx(3.725e-12) and scale[1] == pytest.approx(124.64)
    assert np.all(np.diff(c.atmosphere(np.linspace(100, 1500, 500))[0]) < 0)


def test_scaled_bessel_matches_numpy():
    x = np.linspace(0, 60, 2000)
    np.testing.assert_allclose(c._i0e(x), np.exp(-x) * np.i0(x), rtol=1e-6)


def _years_to_reentry(alt_km, ballistic, max_years=30):
    r = np.array([c.R_E_KM + alt_km])
    pop = c._Population(r, r.copy(), np.array([ballistic]), np.zeros(1))
    for year in range(1, max_years + 1):
        pop.decay(1.0)
        if pop.rp.size == 0:
            return year
    return math.inf


def test_decay_lifetimes_are_physical():
    assert _years_to_reentry(300, 0.02) <= 1  # light object at 300 km: months
    assert _years_to_reentry(840, 0.005) == math.inf  # SL-16 altitude: decades to centuries
    # ISS-like ballistic coefficient at 418 km without reboosts: a few km per month.
    r = np.array([c.R_E_KM + 418])
    pop = c._Population(r, r.copy(), np.array([0.005]), np.zeros(1))
    pop.decay(30 / 365.25)
    assert 0.5 < 418 - (pop.rp[0] - c.R_E_KM) < 10


def test_eccentric_orbits_lose_apogee_first():
    rp, ra = c.decay_step(np.array([c.R_E_KM + 300.0]), np.array([c.R_E_KM + 1500.0]), np.array([0.05]), 864000.0)
    assert rp[0] == pytest.approx(c.R_E_KM + 300.0)
    assert ra[0] < c.R_E_KM + 1500.0


# --- Shell densities ----------------------------------------------------------------------------
def test_residence_weights_sum_to_one_and_favour_apogee():
    edges = c._shell_edges_r_km()
    rp = np.array([c.R_E_KM + 550.0, c.R_E_KM + 400.0])
    ra = np.array([c.R_E_KM + 550.0, c.R_E_KM + 1400.0])
    w = c._residence_weights(rp, ra, edges)
    np.testing.assert_allclose(w.sum(axis=1), 1.0, atol=1e-5)
    assert np.count_nonzero(w[0] > 1e-6) == 1  # a circular orbit sits in one shell
    alt = 0.5 * (edges[1:] + edges[:-1]) - c.R_E_KM
    assert w[1][(alt > 1300) & (alt < 1400)].sum() > w[1][(alt > 400) & (alt < 500)].sum()


def test_environment_counts(catalog, env):
    assert env.object_count == len(catalog)
    assert env.survivors_by_year[0] == len(catalog)
    assert np.all(np.diff(env.survivors_by_year) <= 0)
    assert env.active_weights.shape[0] == sum(o["type"] == "PAYLOAD" and o["active"] for o in catalog)
    assert (env.density_all >= env.density_intact).all()


# --- Contract -----------------------------------------------------------------------------------
def test_collision_result_matches_contract(env):
    parent = named("SL-16 R/B")
    result = c.simulate_cascade(parent, event="collision", years=25, include_launches=True, environment=env)
    assert set(result) == {"parent", "fragmentCount", "spreadDvMs", "seed", "years", "secondaryCollisions"}
    assert result["parent"] == {"noradId": 22285, "name": "SL-16 R/B", "type": "ROCKET_BODY",
                                "maneuverable": False, "omm": parent["omm"]}
    assert 4000 < result["fragmentCount"] < 5200  # NSBM: 0.1 * 8910^0.75 * 10^1.71 ~ 4690
    assert set(result["spreadDvMs"]) == {"mean", "sd"} and result["spreadDvMs"]["sd"] > 0
    assert isinstance(result["seed"], int)
    years = result["years"]
    assert [row["year"] for row in years] == list(range(26))
    for row in years:
        assert set(row) == YEAR_KEYS
        assert row["trackedTotal"] >= row["baselineTotal"]
        assert isinstance(row["trackedTotal"], int) and isinstance(row["satellitesAtRisk"], int)
        assert row["extraConjunctionsPct"] >= 0
    assert years[0]["trackedTotal"] > years[0]["baselineTotal"]
    assert years[0]["satellitesAtRisk"] > 0 and years[0]["extraConjunctionsPct"] > 0
    events = result["secondaryCollisions"]
    for event in events:
        assert set(event) == EVENT_KEYS
        assert 0 < event["year"] <= 25 and event["fragments"] > 0
        assert abs(event["latDeg"]) <= 71.1  # bounded by the parent's inclination
        assert -180 <= event["lonDeg"] <= 180 and 100 < event["altKm"] < 2000
    assert [e["year"] for e in events] == sorted(e["year"] for e in events)


def test_launch_baseline_horizon_and_determinism(env):
    parent = named("SL-16 R/B")

    def run(**overrides):
        args = {"event": "collision", "years": 10, "include_launches": True, **overrides}
        return c.simulate_cascade(parent, environment=env, **args)

    with_launches, without = run(), run(include_launches=False)
    assert len(with_launches["years"]) == 11
    gap = with_launches["years"][10]["baselineTotal"] - without["years"][10]["baselineTotal"]
    assert gap == 10 * c.LAUNCH_RATE_PER_YEAR
    assert all(e["year"] <= 10 for e in with_launches["secondaryCollisions"])
    assert run() == with_launches  # same request, same answer (cacheable)
    assert len(run(years=0)["years"]) == 2 and len(run(years=40)["years"]) == 26  # clamped to 1..25
    assert len(run(years=7.6)["years"]) == 9


def test_explosion_vs_collision_and_debris_mass_cap(env):
    rb = named("SL-16 R/B")
    explosion = c.simulate_cascade(rb, event="explosion", years=5, include_launches=False, environment=env)
    collision = c.simulate_cascade(rb, event="collision", years=5, include_launches=False, environment=env)
    assert explosion["fragmentCount"] == round(c.explosion_fragment_yield())  # 239; mass is not limiting
    assert explosion["fragmentCount"] < collision["fragmentCount"]
    assert explosion["seed"] != collision["seed"]
    # A 1 kg fragment cannot shed 239 pieces of >= 10 cm: mass conservation caps it.
    tiny = c.simulate_cascade(named("IRIDIUM 33 DEB"), event="explosion", years=5, include_launches=False, environment=env)
    assert 1 <= tiny["fragmentCount"] < 50
    # Debris striking an 800 kg satellite is catastrophic: ~770 fragments.
    debris = c.simulate_cascade(named("FENGYUN 1C DEB"), event="collision", years=5, include_launches=False, environment=env)
    assert 500 < debris["fragmentCount"] < 900


def test_catalog_or_environment_and_validation(catalog, env):
    parent = named("SL-16 R/B")
    direct = c.simulate_cascade(parent, catalog, event="explosion", years=3, include_launches=True)
    assert direct == c.simulate_cascade(parent, event="explosion", years=3, include_launches=True, environment=env)
    with pytest.raises(ValueError):
        c.simulate_cascade(parent, event="implosion", years=3, include_launches=True, environment=env)
    with pytest.raises(ValueError):
        c.simulate_cascade({**parent, "omm": {}}, event="collision", years=3, include_launches=True, environment=env)
    with pytest.raises(ValueError):
        c.simulate_cascade(parent, event="collision", years=3, include_launches=True)


def test_accepts_attribute_objects(env):
    class Obj:
        def __init__(self, data):
            self.__dict__.update(data)

    parent = named("SL-16 R/B")
    as_object = c.simulate_cascade(Obj(parent), event="explosion", years=2, include_launches=True, environment=env)
    assert as_object == c.simulate_cascade(parent, event="explosion", years=2, include_launches=True, environment=env)
