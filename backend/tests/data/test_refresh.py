"""No live HTTP/AWS: test durable cooldowns, cache preservation and S3 conditions."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.data import refresh, storage
from app.data.storage import Settings, Snapshot
from tests.data.test_catalog import real_omm

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc).timestamp()


class S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class MemoryS3:
    """Implements the actual If-Match/If-None-Match object-store semantics."""
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.gets = []

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        if Key not in self.objects:
            raise S3Error("NoSuchKey")
        body = self.objects[Key]
        return {"Body": io.BytesIO(body), "ETag": self.etag(body)}

    @staticmethod
    def etag(body):
        return '"' + hashlib.sha256(body).hexdigest() + '"'

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts.append((Key, kwargs))
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise S3Error("PreconditionFailed")
        if "IfMatch" in kwargs:
            if Key not in self.objects or kwargs["IfMatch"] != self.etag(self.objects[Key]):
                raise S3Error("PreconditionFailed")
        self.objects[Key] = Body
        return {"ETag": self.etag(Body)}


class RefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = real_omm()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.json"
        self.bundle = Path(self.temp.name) / "bundle.json"
        self.old = Snapshot("2025-07-10T18:06:17Z", "historical test fixture", (self.raw,))
        storage.atomic_write(self.path, self.old.to_bytes())
        storage.atomic_write(self.bundle, self.old.to_bytes())
        patches = [patch.dict(os.environ, {"CATALOG_CACHE_PATH": str(self.path), "S3_BUCKET": "",
                   "CATALOG_S3_KEY": "catalog.json", "CATALOG_MIN_REFRESH_SECONDS": "1",
                   "CATALOG_MANEUVERABLE_IDS": "", "CELESTRAK_URL": ""}),
                   patch.object(storage, "BUNDLED_SNAPSHOT", self.bundle),
                   patch.object(refresh.time, "time", return_value=NOW)]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        storage._remote_cache.clear()
        self.settings = Settings.from_env()

    def download(self, url):
        # Synthetic fixtures based on a real OMM, specifically for request merging.
        if url == refresh.DEFAULT_URLS[0]:
            return json.dumps([self.raw]).encode()
        if url == refresh.DEFAULT_URLS[1]:
            return json.dumps([dict(self.raw, NORAD_CAT_ID=99, OBJECT_NAME="TEST DEB"),
                               dict(self.raw, EPOCH="2025-07-09T13:24:04.201344"),
                               {"invalid": "row"}]).encode()
        if url == refresh.DEFAULT_URLS[2]:
            return json.dumps([dict(self.raw, NORAD_CAT_ID=12, OBJECT_NAME="TEST R/B")]).encode()
        if url == refresh.SATCAT_URL:
            return b"NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,OWNER\n5,PAY,+,US\n99,DEB,-,CIS\n12,R/B,-,US\n"
        raise AssertionError(f"Unexpected upstream URL {url}")

    def test_success_merges_newest_epoch_and_atomically_replaces_local(self):
        with patch.object(refresh, "_download", side_effect=self.download) as download:
            result = refresh.fetch_catalog()
        self.assertEqual(result.status, "updated")
        self.assertEqual(result.object_count, 3)
        self.assertEqual(download.call_count, 4)
        saved = storage.parse_snapshot(self.path.read_bytes())
        self.assertEqual(saved.records[0]["EPOCH"], "2025-07-09T13:24:04.201344")
        self.assertEqual(saved.active_ids, frozenset({5}))
        self.assertEqual(saved.satcat["99"]["OBJECT_TYPE"], "DEB")
        self.assertEqual(saved.synced_at, "2026-10-30T12:00:00Z")
        self.assertFalse(self.settings.lock_path.exists())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_two_hour_floor_survives_new_function_invocations(self):
        with patch.object(refresh, "_download", side_effect=self.download) as download:
            self.assertEqual(refresh.fetch_catalog().status, "updated")
            storage._local_snapshot.cache_clear()
            self.assertEqual(refresh.fetch_catalog().status, "skipped")
            with patch.object(refresh.time, "time", return_value=NOW + 7199):
                self.assertEqual(refresh.fetch_catalog().status, "skipped")
            self.assertEqual(download.call_count, 4)
            with patch.object(refresh.time, "time", return_value=NOW + 7200):
                self.assertEqual(refresh.fetch_catalog().status, "updated")
            # SATCAT is cached for a day: second batch has only three GP requests.
            self.assertEqual(download.call_count, 7)

    def test_recent_snapshot_without_attempt_state_prevents_fetch(self):
        stamp = datetime.fromtimestamp(NOW - 1, timezone.utc).isoformat()
        storage.atomic_write(self.path, Snapshot(stamp, "recent", (self.raw,)).to_bytes())
        with patch.object(refresh, "_download") as download:
            self.assertEqual(refresh.fetch_catalog().status, "skipped")
        download.assert_not_called()

    def test_explicit_refresh_can_bootstrap_when_all_snapshots_are_missing(self):
        self.path.unlink()
        self.bundle.unlink()
        with patch.object(refresh, "_download", side_effect=self.download):
            self.assertEqual(refresh.fetch_catalog().status, "updated")
        self.assertTrue(self.path.exists())

    def test_s3_reader_selects_newest_snapshot_and_limits_object_reads(self):
        s3 = MemoryS3()
        recent = Snapshot("2026-10-30T11:00:00Z", "newer S3", (self.raw,))
        s3.objects["catalog.json"] = recent.to_bytes()
        settings = Settings(self.path, "test-bucket", "catalog.json")
        with patch.object(storage, "s3_client", return_value=s3):
            self.assertEqual(storage.read_snapshot(settings).source, "newer S3")
            self.assertEqual(storage.read_snapshot(settings).source, "newer S3")
        self.assertEqual(s3.gets.count("catalog.json"), 1)

    def test_s3_reader_retains_valid_remote_cache_after_network_error(self):
        s3 = MemoryS3()
        recent = Snapshot("2026-10-30T11:00:00Z", "retained S3", (self.raw,))
        s3.objects["catalog.json"] = recent.to_bytes()
        settings = Settings(self.path, "test-bucket", "catalog.json")
        with patch.object(storage, "s3_client", return_value=s3):
            self.assertEqual(storage.read_snapshot(settings).source, "retained S3")
            checked, _ = storage._remote_cache[(settings.bucket, settings.key)]
            with patch.object(storage.time, "monotonic", return_value=checked + 301), \
                 patch.object(s3, "get_object", side_effect=OSError("network unavailable")):
                self.assertEqual(storage.read_snapshot(settings).source, "retained S3")

    def test_failed_atomic_replacement_preserves_original_and_cleans_temporary(self):
        original = self.path.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                storage.atomic_write(self.path, b"replacement")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_http_403_stops_batch_preserves_cache_and_blocks_later(self):
        original = self.path.read_bytes()
        error = HTTPError(refresh.DEFAULT_URLS[0], 403, "Blocked", Message(), None)
        with patch.object(refresh, "_download", side_effect=error) as download:
            self.assertEqual(refresh.fetch_catalog().status, "error")
            self.assertEqual(download.call_count, 1)
            with patch.object(refresh.time, "time", return_value=NOW + 86400):
                self.assertEqual(refresh.fetch_catalog().status, "skipped")
            self.assertEqual(download.call_count, 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(json.loads(self.settings.state_path.read_bytes())["blocked"])

    def test_429_retry_after_extends_cooldown(self):
        headers = Message()
        headers["Retry-After"] = "14400"
        error = HTTPError(refresh.DEFAULT_URLS[0], 429, "Rate limited", headers, None)
        with patch.object(refresh, "_download", side_effect=error) as download:
            self.assertEqual(refresh.fetch_catalog().status, "error")
            with patch.object(refresh.time, "time", return_value=NOW + 10000):
                self.assertEqual(refresh.fetch_catalog().status, "skipped")
            self.assertEqual(download.call_count, 1)
        self.assertEqual(json.loads(self.settings.state_path.read_bytes())["nextAllowedAt"], NOW + 14400)

    def test_timeout_json_html_and_empty_data_never_overwrite_good_cache(self):
        for failure in (TimeoutError("unreachable"), b"<html>error</html>", b"[]", b"{}",
                        b'[{"NORAD_CAT_ID": 1}]'):
            with self.subTest(failure=str(failure)):
                self.settings.state_path.unlink(missing_ok=True)
                original = self.path.read_bytes()
                options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch.object(refresh, "_download", **options) as download:
                    self.assertEqual(refresh.fetch_catalog().status, "error")
                    self.assertEqual(refresh.fetch_catalog().status, "skipped")
                self.assertEqual(download.call_count, 1)
                self.assertEqual(self.path.read_bytes(), original)

    def test_corrupt_refresh_state_fails_closed(self):
        for state in ("bad state", '{"nextAllowedAt":NaN}', '{"nextAllowedAt":true}'):
            with self.subTest(state=state):
                self.settings.state_path.write_text(state)
                with patch.object(refresh, "_download") as download:
                    self.assertEqual(refresh.fetch_catalog().status, "error")
                download.assert_not_called()

    def test_local_processes_cannot_refresh_at_the_same_time(self):
        entered = threading.Event()
        release = threading.Event()
        results = []

        def delayed(url):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test synchronization")
            return self.download(url)

        with patch.object(refresh, "_download", side_effect=delayed):
            thread = threading.Thread(target=lambda: results.append(refresh.fetch_catalog()))
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=3))
                self.assertEqual(refresh.fetch_catalog().status, "skipped")
            finally:
                release.set()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, "updated")

    def test_s3_persists_snapshot_and_claims_only_with_conditionals(self):
        s3 = MemoryS3()
        with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}), \
             patch.object(storage, "s3_client", return_value=s3), \
             patch.object(refresh, "_download", side_effect=self.download):
            self.assertEqual(refresh.fetch_catalog().status, "updated")
        self.assertIn("catalog.json", s3.objects)
        self.assertIn("catalog.json.refresh.json", s3.objects)
        self.assertEqual(s3.puts[0][1]["IfNoneMatch"], "*")
        self.assertEqual(self.path.read_bytes(), s3.objects["catalog.json"])

    def test_s3_cooldown_covers_cold_starts_without_local_state(self):
        s3 = MemoryS3()
        s3.objects["catalog.json.refresh.json"] = json.dumps({"nextAllowedAt": NOW + 7200}).encode()
        with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}), \
             patch.object(storage, "s3_client", return_value=s3), patch.object(refresh, "_download") as download:
            self.assertEqual(refresh.fetch_catalog().status, "skipped")
        download.assert_not_called()
        self.assertEqual(s3.puts, [])

    def test_s3_compare_and_swap_renews_an_expired_lease(self):
        s3 = MemoryS3()
        s3.objects["catalog.json.refresh.json"] = json.dumps({"nextAllowedAt": NOW - 1}).encode()
        etag = s3.etag(s3.objects["catalog.json.refresh.json"])
        with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}), \
             patch.object(storage, "s3_client", return_value=s3), \
             patch.object(refresh, "_download", side_effect=self.download):
            self.assertEqual(refresh.fetch_catalog().status, "updated")
        self.assertEqual(s3.puts[0][1]["IfMatch"], etag)

    def test_s3_denied_or_lost_claim_prevents_upstream_requests(self):
        for code in ("AccessDenied", "PreconditionFailed"):
            with self.subTest(code=code):
                self.settings.state_path.unlink(missing_ok=True)
                s3 = MemoryS3()
                with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}), \
                     patch.object(storage, "s3_client", return_value=s3), \
                     patch.object(s3, "put_object", side_effect=S3Error(code)), \
                     patch.object(refresh, "_download") as download:
                    self.assertEqual(refresh.fetch_catalog().status, "error")
                download.assert_not_called()

    def test_s3_failure_state_and_http_block_are_shared(self):
        s3 = MemoryS3()
        error = HTTPError(refresh.DEFAULT_URLS[0], 404, "Bad query", Message(), None)
        with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}), \
             patch.object(storage, "s3_client", return_value=s3), \
             patch.object(refresh, "_download", side_effect=error):
            self.assertEqual(refresh.fetch_catalog().status, "error")
        shared = json.loads(s3.objects["catalog.json.refresh.json"])
        self.assertTrue(shared["blocked"])
        self.assertIn("IfMatch", s3.puts[-1][1])

    def test_metadata_reused_for_24h_and_old_env_active_override_keeps_all_feeds(self):
        old = Snapshot("2026-10-30T06:00:00Z", "cached", (self.raw,), satcat={"5": {"OBJECT_TYPE": "PAY"}},
                       satcat_synced_at="2026-10-30T06:00:00Z")
        with patch.object(refresh, "_download", side_effect=self.download) as download:
            snapshot = refresh._download_catalog(NOW, old)
        self.assertEqual(download.call_count, 3)
        self.assertEqual(snapshot.satcat_synced_at, old.satcat_synced_at)
        with patch.dict(os.environ, {"CELESTRAK_URL": refresh.DEFAULT_URLS[0]}):
            self.assertEqual(refresh._urls(), refresh.DEFAULT_URLS)

    def test_redirects_are_not_followed_and_unsafe_formats_fail(self):
        self.assertIsNone(refresh.NoRedirect().redirect_request(None, None, 301, "moved", {}, "https://example.com"))
        for url in ("http://celestrak.org/?FORMAT=JSON", "https://example.com/?FORMAT=JSON",
                    "https://celestrak.org/?FORMAT=TLE"):
            with patch.dict(os.environ, {"CELESTRAK_URL": url}), self.assertRaises(ValueError):
                refresh._urls()

    def test_eventbridge_entrypoint_is_json_serializable_and_never_throws_http_error(self):
        with patch.object(refresh, "_download", side_effect=self.download):
            result = refresh.refresh_handler({"source": "aws.events"}, None)
        self.assertEqual(json.loads(json.dumps(result))["status"], "updated")


if __name__ == "__main__":
    unittest.main()
