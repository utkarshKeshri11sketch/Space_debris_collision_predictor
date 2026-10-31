"""Rewind 2009 (Iridium 33 x Cosmos 2251): API shape and the invariants the page relies on."""
import os

os.environ.setdefault("SCREENING_WARMUP", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app.casestudy import collision  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CollisionStudy  # noqa: E402

client = TestClient(app)


def test_list_and_detail():
    assert client.get("/api/collision-studies").json() == [collision.summary()]
    study = CollisionStudy.model_validate(client.get(f"/api/collision-studies/{collision.ID}").json())
    assert study.id == collision.ID
    assert client.get("/api/collision-studies/nope").status_code == 404


def test_every_fact_cites_a_listed_source():
    study = collision.build()
    keys = {s.key for s in study.sources}
    cited = [f.source for f in study.facts + study.aftermath] + [study.pcSource, study.publicWarning.source,
                                                                 study.debris.knockOnSource]
    cited += [c.source for c in study.debris.counts]
    assert set(cited) <= keys


def test_only_iridium_moves_and_the_burn_clears_the_policy():
    study = collision.build()
    decision = study.orbitSentinel
    movers = [o.noradId for o in study.objects if o.maneuverable]
    assert movers == [decision.moverNoradId] == [24946]
    # On the planned (collision) trajectory the planner must call for a burn...
    assert decision.pc >= study.pcThreshold
    assert decision.maneuver.recommended and decision.maneuver.direction != "none"
    # ...that meets the live policy, for grams of hydrazine.
    assert decision.maneuver.newMissM >= 1000 and decision.maneuver.newPc <= 1e-7
    assert 0 < decision.maneuver.propellantKg < 0.1
    assert 0 < decision.causePropellantKg < 0.01


def test_debris_model_and_catalogue_counts():
    debris = collision.build().debris
    # Catastrophic NSBM collision of 556 + 900 kg: ~0.1 * 1456^0.75 * 0.1^-1.71 fragments >= 10 cm.
    assert 1100 < debris.modelFragments < 1300
    counts = [c.catalogued for c in debris.counts]
    assert counts == sorted(counts) and counts[-1] == 2201
    assert all(c.inOrbit is None or c.inOrbit <= c.catalogued for c in debris.counts)
