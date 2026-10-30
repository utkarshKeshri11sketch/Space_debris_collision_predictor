"""In-process contract tests against the real catalog snapshot. Run from backend/: python -m pytest

These must hold on any snapshot, so they check shapes and invariants, not specific events.
"""
import json
import os

os.environ.setdefault("SCREENING_WARMUP", "0")

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

from app.main import app  # noqa: E402
from app.models import CascadeResult, CatalogObject, Conjunction, ConjunctionDetail  # noqa: E402

client = TestClient(app)


def sse(response) -> list:
    chunks = [b.strip() for b in response.text.split("\n\n") if b.strip()]
    assert chunks[-1] == "data: [DONE]"
    return [json.loads(c[5:]) for c in chunks[:-1]]


def test_catalog_and_meta():
    items = TypeAdapter(list[CatalogObject]).validate_python(client.get("/api/catalog").json())
    meta = client.get("/api/catalog/meta").json()
    assert items and len(items) == meta["objectCount"] == sum(meta["byType"].values())
    assert set(meta["byType"]) == {"PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN"}
    assert any(o.noradId == 25544 for o in items)


def test_catalog_is_gzipped():
    response = client.get("/api/catalog", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"


def test_conjunctions_list_and_detail():
    response = client.get("/api/conjunctions?days=7&minPc=1e-6")
    if response.status_code == 400:  # bundled July 2025 archive is too old to propagate to "now"
        assert "age limit" in response.json()["message"]
        return
    items = TypeAdapter(list[Conjunction]).validate_python(response.json())
    for item in items[:3]:
        detail = ConjunctionDetail.model_validate(client.get(f"/api/conjunctions/{item.id}").json())
        assert any(o.direction == "none" for o in detail.options)
    assert client.get("/api/conjunctions/nope").status_code == 404


def test_negotiation_errors():
    assert client.post("/api/negotiations", json={"conjunctionId": "nope"}).status_code == 404
    assert client.get("/api/negotiations/unknown/stream").status_code == 404


def test_cascade():
    body = {"noradId": 22285, "event": "collision", "years": 25, "includeLaunches": True}
    res = CascadeResult.model_validate(client.post("/api/cascade", json=body).json())
    assert len(res.years) == 26 and res.years[0].year == 0 and res.fragmentCount > 0
    assert client.post("/api/cascade", json={**body, "noradId": 1}).status_code == 404
    assert client.post("/api/cascade", json={**body, "event": "boom"}).status_code == 400


def test_ask_validation():
    assert client.post("/api/ask", json={"question": " "}).status_code == 400


def test_ask_answers_when_screening_is_unavailable(monkeypatch):
    from fastapi import HTTPException

    from app.physics import screening

    def stale(*_args, **_kwargs):
        raise HTTPException(400, "element epoch outside configured age limit for requested window")

    monkeypatch.setattr(screening, "screen", stale)
    response = client.post("/api/ask", json={"question": "What is the best pizza recipe?"})
    assert response.status_code == 200
    assert "".join(t["text"] for t in sse(response)).startswith("I can only help with")
