"""Exercise the existing FastAPI routes with real catalog data, without sockets."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.main import app
from app.models import CatalogMeta, CatalogObject


class HttpContractTests(unittest.TestCase):
    def test_catalog_and_meta_match_exact_frontend_contract_without_http_refresh(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "CATALOG_CACHE_PATH": str(Path(directory) / "catalog.json"),
                "S3_BUCKET": "", "CATALOG_MANEUVERABLE_IDS": ""}), \
             patch("app.data.refresh._download", side_effect=AssertionError("No upstream call on API requests")), \
             TestClient(app) as client:
            response = client.get("/api/catalog")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("application/json"))
            raw = response.json()
            parsed = TypeAdapter(list[CatalogObject]).validate_python(raw)
            self.assertEqual(set(raw[0]), {"noradId", "name", "type", "active", "maneuverable", "omm"})
            self.assertTrue(all(set(item) == set(raw[0]) for item in raw))
            self.assertTrue(any(item.noradId == 25544 for item in parsed))
            self.assertTrue(any(item.noradId >= 100000 for item in parsed))
            meta_response = client.get("/api/catalog/meta")
            self.assertEqual(meta_response.status_code, 200)
            meta = CatalogMeta.model_validate(meta_response.json())
            self.assertEqual(set(meta_response.json()), {"objectCount", "byType", "syncedAt", "source"})
            self.assertEqual(meta.objectCount, len(parsed))
            self.assertEqual(sum(meta.byType.values()), len(parsed))
            self.assertEqual(set(meta.byType), {"PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN"})
