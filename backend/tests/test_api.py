"""Fast in-process contract tests. Run from backend/: python -m pytest"""
import json

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app import mock_data
from app.main import app
from app.models import CascadeResult, CatalogObject, Conjunction, ConjunctionDetail, NegotiationEvent

client = TestClient(app)


def sse(response) -> list:
    chunks = [b.strip() for b in response.text.split("\n\n") if b.strip()]
    assert chunks[-1] == "data: [DONE]"
    return [json.loads(c[5:]) for c in chunks[:-1]]


def test_mulberry32_matches_frontend():
    # First values of seededRandom(712635) computed with frontend/src/lib/random.ts
    rnd = mock_data.seeded_random(712635)
    assert [rnd() for _ in range(3)] == [0.7585798201616853, 0.19677913701161742, 0.4911742121912539]
    last = mock_data.get_catalog()[-1].omm
    assert (last["INCLINATION"], last["MEAN_ANOMALY"]) == (51.575696907471865, 316.5997308958322)


def test_catalog_and_meta():
    items = TypeAdapter(list[CatalogObject]).validate_python(client.get("/api/catalog").json())
    assert len(items) == mock_data.OBJECT_COUNT
    meta = client.get("/api/catalog/meta").json()
    assert sum(meta["byType"].values()) == meta["objectCount"]


def test_conjunctions_list_and_detail():
    items = TypeAdapter(list[Conjunction]).validate_python(client.get("/api/conjunctions?days=7&minPc=1e-6").json())
    assert [i.id for i in items][0] == "iss-cosmos"
    ConjunctionDetail.model_validate(client.get("/api/conjunctions/iss-cosmos").json())
    assert client.get("/api/conjunctions/nope").status_code == 404


def test_negotiation_stream():
    assert client.post("/api/negotiations", json={"conjunctionId": "iss-cosmos"}).status_code == 422
    r = client.post("/api/negotiations", json={"conjunctionId": "starlink-oneweb"})
    assert r.status_code == 201
    events = sse(client.get(f"/api/negotiations/{r.json()['negotiationId']}/stream"))
    parsed = [TypeAdapter(NegotiationEvent).validate_python(e) for e in events]
    assert parsed[-1].type == "agreement"
    assert client.get("/api/negotiations/unknown/stream").status_code == 404


def test_cascade():
    body = {"noradId": 22285, "event": "collision", "years": 25, "includeLaunches": True}
    res = CascadeResult.model_validate(client.post("/api/cascade", json=body).json())
    assert len(res.secondaryCollisions) == 2
    assert client.post("/api/cascade", json={**body, "noradId": 1}).status_code == 404
    assert client.post("/api/cascade", json={**body, "event": "boom"}).status_code == 400


def test_ask():
    tokens = sse(client.post("/api/ask", json={"question": "Is the ISS safe?"}))
    assert all(t["type"] == "token" for t in tokens)
    assert "ISS" in "".join(t["text"] for t in tokens)
    assert client.post("/api/ask", json={"question": " "}).status_code == 400
