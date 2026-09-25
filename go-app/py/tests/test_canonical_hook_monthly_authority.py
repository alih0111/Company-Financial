"""Monthly authority-mode tests for canonical_hook (no DB required)."""

import json
import os
import tempfile
import unittest
from unittest import mock

import pathlib

import canonical_hook


class MonthlyAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self._out = canonical_hook._OUT_DIR
        canonical_hook._OUT_DIR = pathlib.Path(self.tmp)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        canonical_hook._OUT_DIR = self._out

    def test_default_monthly_authority_legacy(self):
        os.environ.pop("CDF_MONTHLY_INGESTION_AUTHORITY", None)
        self.assertEqual(canonical_hook.monthly_authority(), "legacy")
        self.assertFalse(canonical_hook.monthly_canonical_authority())

    def test_canonical_selection(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        self.assertTrue(canonical_hook.monthly_canonical_authority())

    def test_legacy_authority_path(self):
        os.environ.pop("CDF_MONTHLY_INGESTION_AUTHORITY", None)
        calls = []
        with mock.patch.object(canonical_hook, "dual_write_monthly_values",
                               return_value={"status": "written", "inserted": 1, "skipped": 0}):
            res = canonical_hook.ingest_monthly_authoritative("c1", "x", "1405/06/31", [0, 0, 1],
                                                              legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "LEGACY_AUTHORITATIVE")
        self.assertEqual(calls, [1])

    def test_canonical_success_legacy_success(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_monthly_write",
                               return_value={"status": "written", "inserted": 1, "skipped": 0}):
            res = canonical_hook.ingest_monthly_authoritative("c1", "x", "1405/06/31", [0, 0, 1],
                                                              legacy_writer=lambda: None)
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_SUCCESS")

    def test_mirror_failure_isolated(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_monthly_write",
                               return_value={"status": "written", "inserted": 1, "skipped": 0}):
            res = canonical_hook.ingest_monthly_authoritative(
                "c1", "x", "1405/06/31", [0, 0, 1],
                legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("mirror down")))
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED")
        self.assertEqual(res["health"], "DEGRADED_LEGACY_MIRROR")

    def test_canonical_failure_fallback_and_retry(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_monthly_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0, "error": "pg down"}):
            res = canonical_hook.ingest_monthly_authoritative("c1", "x", "1405/06/31", [0, 0, 1],
                                                              legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "CANONICAL_FAILED_LEGACY_FALLBACK_USED")
        self.assertEqual(calls, [1])
        self.assertEqual(canonical_hook.retry_backlog_count("monthly_activity"), 1)
        manifest = (canonical_hook._OUT_DIR / "canonical_retry_manifest.jsonl").read_text(encoding="utf-8")
        self.assertIn('"monthly_activity"', manifest)

    def test_fallback_disabled(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        os.environ["CDF_MONTHLY_FALLBACK_LEGACY"] = "false"
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_monthly_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0, "error": "pg down"}):
            res = canonical_hook.ingest_monthly_authoritative("c1", "x", "1405/06/31", [0, 0, 1],
                                                              legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "CANONICAL_FAILED")
        self.assertEqual(calls, [])

    def test_quarantine_health(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_monthly_write",
                               return_value={"status": "quarantined", "inserted": 0, "skipped": 0}):
            res = canonical_hook.ingest_monthly_authoritative("unknown", "x", "1405/06/31", [0, 0, 1],
                                                              legacy_writer=lambda: None)
        self.assertEqual(res["health"], "IDENTITY_QUARANTINE")

    def test_market_authority_independent_of_monthly(self):
        os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
        os.environ.pop("CDF_MARKET_INGESTION_AUTHORITY", None)
        self.assertTrue(canonical_hook.monthly_canonical_authority())
        self.assertFalse(canonical_hook.market_canonical_authority())


if __name__ == "__main__":
    unittest.main()
