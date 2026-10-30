"""Data tests use unittest too, so the offline suite needs no pytest plugins."""
from __future__ import annotations

import gzip
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sgp4.api import Satrec

from app.data import catalog, storage
from app.data.storage import Settings, Snapshot


def real_omm() -> dict:
    # Real July 2025 Space-Track OMM record, retained in satellite.js test archive.
    # Values are copied from our committed provenance-tracked archive, not mocks.
    with gzip.open(storage.BUNDLED_SNAPSHOT, "rb") as stream:
        return json.load(stream)["records"][0]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = real_omm()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "catalog.json"
        self.env = patch.dict(os.environ, {"CATALOG_CACHE_PATH": str(self.path),
                             "S3_BUCKET": "", "CATALOG_MANEUVERABLE_IDS": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        storage._remote_cache.clear()

    def snapshot(self, records=None, stamp="2026-10-30T12:00:00Z", **kwargs):
        return Snapshot(stamp, "test fixture using real OMM", tuple(records or [self.raw]), **kwargs)

    def test_exact_frontend_fields_and_all_metadata_types(self):
        snapshot = self.snapshot(satcat={"5": {"OBJECT_TYPE": "PAY"}})
        storage.atomic_write(self.path, snapshot.to_bytes())
        items = catalog.load_catalog()
        self.assertEqual(set(items[0].model_dump()),
                         {"noradId", "name", "type", "active", "maneuverable", "omm"})
        self.assertEqual(items[0].type, "PAYLOAD")
        meta = catalog.catalog_meta()
        self.assertEqual(meta.objectCount, len(items))
        self.assertEqual(set(meta.byType), set(catalog.OBJECT_TYPES))
        self.assertEqual(sum(meta.byType.values()), len(items))
        self.assertEqual(meta.syncedAt, snapshot.synced_at)

    def test_six_digit_id_uses_native_omm_without_tle_truncation(self):
        # Synthetic identifier only: dynamics remain the real Vanguard OMM.
        raw = dict(self.raw, NORAD_CAT_ID=123456, OBJECT_ID="")
        record = catalog.parse_record(raw, {}, frozenset(), frozenset())
        self.assertIsInstance(record.satrec, Satrec)
        self.assertEqual(record.norad_id, 123456)
        self.assertEqual(record.satrec.satnum, 123456)
        self.assertEqual(record.omm["NORAD_CAT_ID"], 123456)
        original = catalog.parse_record(self.raw, {}, frozenset(), frozenset())
        _, pos, _ = record.satrec.sgp4(record.satrec.jdsatepoch, record.satrec.jdsatepochF)
        _, reference, _ = original.satrec.sgp4(original.satrec.jdsatepoch, original.satrec.jdsatepochF)
        for value, expected in zip(pos, reference):
            self.assertAlmostEqual(value, expected, places=8)

    def test_epoch_suffix_and_offset_are_normalized_to_utc(self):
        epoch = str(self.raw["EPOCH"])
        a = catalog.normalize_omm(dict(self.raw, EPOCH=epoch + "Z"))
        b = catalog.normalize_omm(dict(self.raw, EPOCH="2025-07-08T18:54:04.201344+05:30"))
        self.assertEqual(a["EPOCH"], b["EPOCH"])
        self.assertEqual(a["EPOCH"], epoch)

    def test_omitted_convention_fields_are_supported(self):
        raw = {key: value for key, value in self.raw.items() if key not in
               {"OBJECT_ID", "EPHEMERIS_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH", "CLASSIFICATION_TYPE"}}
        item = catalog.parse_record(raw, {}, frozenset(), frozenset())
        self.assertEqual(item.satrec.intldesg, "")
        self.assertEqual(item.omm["EPHEMERIS_TYPE"], 0)

    def test_invalid_dynamics_and_unsupported_frames_are_rejected(self):
        bad = [("MEAN_MOTION", 0), ("MEAN_MOTION", math.inf), ("ECCENTRICITY", 1),
               ("INCLINATION", -1), ("EPOCH", "bad"), ("BSTAR", math.nan),
               ("NORAD_CAT_ID", 1.5), ("NORAD_CAT_ID", 0), ("EPHEMERIS_TYPE", 4),
               ("REF_FRAME", "J2000"), ("TIME_SYSTEM", "TAI"), ("MEAN_ANOMALY", 361)]
        for key, value in bad:
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, KeyError, TypeError)):
                catalog.normalize_omm(dict(self.raw, **{key: value}))
        for key in catalog.REQUIRED_NUMBERS:
            with self.subTest(missing=key), self.assertRaises(KeyError):
                catalog.normalize_omm({k: v for k, v in self.raw.items() if k != key})

    def test_authoritative_types_and_conservative_capability(self):
        for source, expected in catalog.TYPE_MAP.items():
            with self.subTest(source=source):
                record = catalog.parse_record(self.raw, {"OBJECT_TYPE": source, "OPS_STATUS_CODE": "+"},
                                               frozenset(), frozenset({5}))
                self.assertEqual(record.type, expected)
                self.assertEqual(record.catalog.active, expected == "PAYLOAD")
                self.assertEqual(record.catalog.maneuverable, expected == "PAYLOAD")
        unknown = catalog.parse_record(self.raw, {}, frozenset(), frozenset({5}))
        self.assertFalse(unknown.catalog.active)
        self.assertFalse(unknown.catalog.maneuverable)
        active = catalog.parse_record(self.raw, {}, frozenset({5}), frozenset())
        self.assertTrue(active.catalog.active)
        self.assertFalse(active.catalog.maneuverable)
        inactive = catalog.parse_record(self.raw, {"OBJECT_TYPE": "PAY", "OPS_STATUS_CODE": "-"},
                                        frozenset({5}), frozenset({5}))
        self.assertFalse(inactive.catalog.active)

    def test_name_inference_and_owner_do_not_invent_country(self):
        for name, kind in (("SL-16 R/B", "ROCKET_BODY"), ("COSMOS 1408 DEB", "DEBRIS"),
                           ("UNCLASSIFIED", "UNKNOWN")):
            record = catalog.parse_record(dict(self.raw, OBJECT_NAME=name), {"OWNER": "CIS"},
                                           frozenset(), frozenset())
            self.assertEqual(record.type, kind)
            self.assertEqual(record.owner, "CIS")
            self.assertIsNone(record.country)

    def test_same_second_cache_order_uses_time_not_string_sort(self):
        older = self.snapshot(stamp="2026-10-30T12:00:00Z")
        newer = self.snapshot(stamp="2026-10-30T12:00:00.500000Z")
        storage.atomic_write(self.path, older.to_bytes())
        fallback = Path(self.temp.name) / "bundle.json"
        storage.atomic_write(fallback, newer.to_bytes())
        with patch.object(storage, "BUNDLED_SNAPSHOT", fallback):
            self.assertEqual(storage.read_snapshot(Settings(self.path)).synced_at, newer.synced_at)

    def test_local_changes_invalidate_cache_and_newest_duplicate_wins(self):
        newer = dict(self.raw, EPOCH="2025-07-09T13:24:04.201344")
        snapshot = self.snapshot([newer, self.raw], satcat={"5": {"OBJECT_TYPE": "PAY"}})
        storage.atomic_write(self.path, snapshot.to_bytes())
        self.assertEqual(catalog.load_catalog()[0].omm["EPOCH"], newer["EPOCH"])
        changed = dict(newer, OBJECT_NAME="Renamed upstream object")
        storage.atomic_write(self.path, self.snapshot([changed]).to_bytes())
        self.assertEqual(catalog.load_catalog()[0].name, changed["OBJECT_NAME"])

    def test_corrupt_local_cache_falls_back_without_upstream_calls(self):
        self.path.write_text("not JSON")
        fallback = Path(self.temp.name) / "bundle.json"
        storage.atomic_write(fallback, self.snapshot().to_bytes())
        with patch.object(storage, "BUNDLED_SNAPSHOT", fallback), patch("urllib.request.OpenerDirector.open",
                side_effect=AssertionError("Catalog API must never fetch CelesTrak")):
            self.assertEqual(len(catalog.load_catalog()), 1)

    def test_invalid_orbits_cannot_displace_valid_fallback(self):
        storage.atomic_write(self.path, self.snapshot([dict(self.raw, MEAN_MOTION=0)]).to_bytes())
        fallback = Path(self.temp.name) / "bundle.json"
        storage.atomic_write(fallback, self.snapshot(stamp="2026-10-29T12:00:00Z").to_bytes())
        with patch.object(storage, "BUNDLED_SNAPSHOT", fallback):
            self.assertEqual(len(catalog.load_catalog()), 1)

    def test_bundled_archive_contains_real_mixed_catalog_and_native_propagators(self):
        items = catalog.load_catalog()
        meta = catalog.catalog_meta()
        self.assertEqual(meta.objectCount, 28124)
        self.assertEqual(meta.byType, {"PAYLOAD": 14468, "DEBRIS": 10419,
                                     "ROCKET_BODY": 2173, "UNKNOWN": 1064})
        self.assertIn("Historical", meta.source)
        orbits = catalog.load_orbit_catalog()
        self.assertEqual(orbits[25544].name, "ISS (ZARYA)")
        self.assertEqual(orbits[22285].type, "ROCKET_BODY")
        self.assertTrue(any(record.noradId >= 100000 for record in items))
        self.assertTrue(all(not record.maneuverable for record in items))
        self.assertEqual(orbits[25544].epoch.year, 2025)
        # Native propagation must succeed at its REAL element epoch, not today.
        sat = orbits[25544].satrec
        error, position, velocity = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF)
        self.assertEqual(error, 0)
        self.assertTrue(all(math.isfinite(value) for value in (*position, *velocity)))
        self.assertGreater(orbits[25544].altitude_km, 350)
        self.assertLess(orbits[25544].altitude_km, 450)


if __name__ == "__main__":
    unittest.main()
