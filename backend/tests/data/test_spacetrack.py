"""Space-Track refresh source. No live HTTP: the session's _fetch is replaced."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.data import catalog, refresh, spacetrack, storage
from app.data.storage import Settings, Snapshot, read_snapshot
from tests.data.test_catalog import real_omm
from tests.data.test_refresh import NOW


class SpaceTrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = real_omm()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.json"
        self.bundle = Path(self.temp.name) / "bundle.json"
        old = Snapshot("2025-07-10T18:06:17Z", "historical test fixture", (self.raw,))
        storage.atomic_write(self.bundle, old.to_bytes())
        patches = [patch.dict(os.environ, {"CATALOG_CACHE_PATH": str(self.path), "S3_BUCKET": "",
                   "CATALOG_MIN_REFRESH_SECONDS": "1", "CATALOG_MANEUVERABLE_IDS": "",
                   "CATALOG_SOURCE": "", "SPACETRACK_USERNAME": "user@example.com",
                   "SPACETRACK_PASSWORD": "secret"}),
                   patch.object(storage, "BUNDLED_SNAPSHOT", self.bundle),
                   patch.object(refresh.time, "time", return_value=NOW)]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        storage._remote_cache.clear()
        self.requests = []

    def gp_rows(self):
        # Space-Track GP rows: real OMM values plus the extra columns Space-Track adds.
        extra = {"TLE_LINE1": "1 ...", "GP_ID": "1", "COUNTRY_CODE": "US", "OBJECT_TYPE": "PAYLOAD"}
        return [dict(self.raw, **extra),
                dict(self.raw, **extra, NORAD_CAT_ID="44713", OBJECT_NAME="STARLINK-1007"),
                dict(self.raw, **dict(extra, OBJECT_TYPE="DEBRIS"), NORAD_CAT_ID="99", OBJECT_NAME="TEST DEB"),
                dict(self.raw, **dict(extra, OBJECT_TYPE="TBA"), NORAD_CAT_ID="77", OBJECT_NAME="OBJECT A"),
                {"NORAD_CAT_ID": "1", "OBJECT_NAME": "BROKEN"}]

    def fake_fetch(self, login=b'""'):
        def fetch(opener, url, data=None, timeout=45):
            self.requests.append((url, data))
            if url == spacetrack.LOGIN_URL:
                return login
            if url == spacetrack.GP_URL:
                return json.dumps(self.gp_rows()).encode()
            if url == spacetrack.LOGOUT_URL:
                return b""
            raise AssertionError(f"Unexpected URL {url}")
        return fetch

    def test_credentials_select_space_track_and_explicit_source_wins(self):
        self.assertEqual(refresh.source(), "spacetrack")
        with patch.dict(os.environ, {"CATALOG_SOURCE": "celestrak"}):
            self.assertEqual(refresh.source(), "celestrak")
        with patch.dict(os.environ, {"SPACETRACK_USERNAME": ""}):
            self.assertEqual(refresh.source(), "celestrak")

    def test_refresh_logs_in_downloads_gp_and_never_contacts_celestrak(self):
        with patch.object(spacetrack, "_fetch", side_effect=self.fake_fetch()), \
             patch.object(refresh, "_download", side_effect=AssertionError("CelesTrak contacted")):
            result = refresh.fetch_catalog()
            refresh._refresh_watchlist()
        self.assertEqual(result.status, "updated")
        self.assertEqual([url for url, _ in self.requests],
                         [spacetrack.LOGIN_URL, spacetrack.GP_URL, spacetrack.LOGOUT_URL])
        self.assertIn(b"identity=user%40example.com", self.requests[0][1])
        snapshot = read_snapshot(Settings.from_env())
        self.assertIn("Space-Track", snapshot.source)
        self.assertEqual(len(snapshot.records), 4)  # the broken row is dropped
        self.assertNotIn("TLE_LINE1", snapshot.records[0])
        records = catalog.load_orbit_catalog()
        # Only propulsive-fleet payloads are marked active (Space-Track has no ops status).
        self.assertTrue(records[44713].catalog.active and records[44713].catalog.maneuverable)
        self.assertFalse(records[5].catalog.active)
        self.assertEqual(records[99].type, "DEBRIS")
        self.assertEqual(records[77].type, "UNKNOWN")

    def test_old_celestrak_block_does_not_stop_space_track(self):
        blocked = {"attemptedAt": NOW - 10, "nextAllowedAt": NOW + 9999, "blocked": True}
        storage.atomic_write(Settings.from_env().state_path, json.dumps(blocked).encode())
        with patch.object(spacetrack, "_fetch", side_effect=self.fake_fetch()):
            self.assertEqual(refresh.fetch_catalog().status, "updated")

    def test_rejected_login_keeps_cache_and_allows_a_retry_after_five_minutes(self):
        with patch.object(spacetrack, "_fetch", side_effect=self.fake_fetch(b'{"Login":"Failed"}')):
            result = refresh.fetch_catalog()
        self.assertEqual(result.status, "error")
        self.assertIn("rejected the login", result.message)
        self.assertNotIn(spacetrack.GP_URL, [url for url, _ in self.requests])
        self.assertFalse(self.path.exists())
        state = json.loads(self.path.with_suffix(".json.spacetrack.refresh.json").read_text())
        self.assertEqual(state["nextAllowedAt"], NOW + refresh.LOGIN_RETRY_SECONDS)

    def test_dotenv_fills_missing_variables_only(self):
        env_file = Path(self.temp.name) / ".env"
        env_file.write_text("# comment\nSPACETRACK_USERNAME=from-file\nNEW_KEY='quoted'\n")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEW_KEY", None)
            refresh.load_dotenv(env_file)
            self.assertEqual(os.environ["SPACETRACK_USERNAME"], "user@example.com")
            self.assertEqual(os.environ["NEW_KEY"], "quoted")


if __name__ == "__main__":
    unittest.main()
