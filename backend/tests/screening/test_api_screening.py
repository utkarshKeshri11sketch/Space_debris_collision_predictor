"""Computed conjunction API checks using explicit synthetic orbital fixtures."""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import json

from fastapi.testclient import TestClient
import pytest

from app.data import catalog as data_catalog
from app.main import app
from app.models import Conjunction, ConjunctionDetail
from app.physics import screening
from .test_screening import crossing_catalog


@pytest.fixture
def api(monkeypatch):
    catalog = crossing_catalog(crossing_seconds=900)
    now = datetime.now(timezone.utc)
    for obj in catalog:
        obj["omm"]["EPOCH"] = now.isoformat()
    monkeypatch.delenv("SCREENING_CATALOG_PATH", raising=False)
    monkeypatch.setenv("SCREENING_TARGET_IDS", "25544")
    monkeypatch.setattr(data_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(data_catalog, "catalog_meta", lambda: SimpleNamespace(source="TEST synthetic OMM"))
    screening._RUN_CACHE.clear()
    screening._DETAIL_CACHE.clear()
    yield TestClient(app), catalog
    screening._RUN_CACHE.clear()
    screening._DETAIL_CACHE.clear()


def test_real_computation_reaches_list_detail_and_selected_target_routes(api):
    client, _ = api
    response = client.get("/api/conjunctions?noradId=25544&days=0.02&minPc=0")
    assert response.status_code == 200
    assert response.headers["X-Screening-Complete"] == "true"
    assert response.headers["X-Screening-Issues"] == "0"
    assert len(response.json()) == 1
    event = Conjunction.model_validate(response.json()[0])
    assert event.primary.noradId == 25544 and event.id != "iss-cosmos"
    detail_response = client.get(f"/api/conjunctions/{event.id}")
    assert detail_response.status_code == 200
    detail = ConjunctionDetail.model_validate(detail_response.json())
    assert len(detail.rangeSeries) == 81
    assert "ASSUMED" in detail.brief and "TEST synthetic OMM" in detail.brief
    assert detail.options[0].direction == "none"
    assert client.get("/api/conjunctions/no-such-event").status_code == 404
    reversed_response = client.get("/api/conjunctions?noradId=123456789&days=0.02&minPc=0")
    assert reversed_response.json()[0]["primary"]["noradId"] == 123456789


def test_pc_filter_uses_cached_propagation_and_snapshot_change_invalidates(api, monkeypatch):
    client, catalog = api
    first = client.get("/api/conjunctions?days=0.02&minPc=0").json()
    real_engine = screening.screen_catalog
    calls = []

    def tracked(*args, **kwargs):
        calls.append(True)
        return real_engine(*args, **kwargs)

    monkeypatch.setattr(screening, "screen_catalog", tracked)
    assert client.get("/api/conjunctions?days=0.02&minPc=1").json() == []
    assert not calls
    catalog[1]["omm"]["BSTAR"] = 0.0001
    second = client.get("/api/conjunctions?days=0.02&minPc=0").json()
    assert calls and first[0]["id"] != second[0]["id"]


def test_detail_can_be_reconstructed_in_a_cold_lambda_with_same_snapshot(api):
    client, _ = api
    event = client.get("/api/conjunctions?days=0.02&minPc=0").json()[0]
    screening._DETAIL_CACHE.clear()
    screening._RUN_CACHE.clear()
    rebuilt = client.get(f"/api/conjunctions/{event['id']}")
    assert rebuilt.status_code == 200
    assert rebuilt.json()["id"] == event["id"]
    assert rebuilt.json()["missDistanceM"] == pytest.approx(event["missDistanceM"], abs=1e-5)


def test_incomplete_catalog_does_not_return_a_clean_run_header(api):
    client, catalog = api
    invalid = dict(catalog[1], noradId=555555, omm={})
    catalog.append(invalid)
    response = client.get("/api/conjunctions?days=0.02&minPc=0")
    assert response.status_code == 200 and response.json()
    assert response.headers["X-Screening-Complete"] == "false"
    assert response.headers["X-Screening-Issues"] == "1"


def test_local_snapshot_override_and_no_fallback_on_missing_file(api, tmp_path, monkeypatch):
    client, catalog = api
    path = tmp_path / "real-format.json"
    path.write_text(json.dumps({"catalog": catalog, "source": "Fixture local snapshot"}))
    monkeypatch.setenv("SCREENING_CATALOG_PATH", str(path))
    response = client.get("/api/conjunctions?days=0.02&minPc=0")
    assert response.status_code == 200 and response.json()
    monkeypatch.setenv("SCREENING_CATALOG_PATH", str(tmp_path / "missing.json"))
    response = client.get("/api/conjunctions?days=0.02&minPc=0")
    assert response.status_code == 503


@pytest.mark.parametrize("query", ["days=-1", "days=8", "minPc=-1", "minPc=2", "noradId=0"])
def test_invalid_api_inputs_return_contract_errors(api, query):
    response = api[0].get(f"/api/conjunctions?{query}")
    assert response.status_code == 400 and isinstance(response.json()["message"], str)


def test_missing_target_is_404_and_zero_horizon_is_empty(api):
    client, _ = api
    assert client.get("/api/conjunctions?noradId=999&days=0.02").status_code == 404
    assert client.get("/api/conjunctions?days=0").json() == []
