"""Market authority-mode tests for canonical_hook (no DB required)."""

import json
import os
import tempfile
import unittest
from unittest import mock

import canonical_hook


def _rows():
    return [{"company_id": "c1", "symbol": "x", "gregorian_date": "2026-09-25",
             "closing_price": 100, "volume": 5}]


class AuthorityModeTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self._out = canonical_hook._OUT_DIR
        canonical_hook._OUT_DIR = __import__("pathlib").Path(self.tmp)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        canonical_hook._OUT_DIR = self._out

    def test_authority_defaults_to_legacy(self):
        os.environ.pop("CDF_MARKET_INGESTION_AUTHORITY", None)
        self.assertEqual(canonical_hook.market_authority(), "legacy")
        self.assertFalse(canonical_hook.market_canonical_authority())

    def test_authority_canonical_selection(self):
        os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "CANONICAL"
        self.assertTrue(canonical_hook.market_canonical_authority())

    def test_legacy_authority_path(self):
        os.environ.pop("CDF_MARKET_INGESTION_AUTHORITY", None)
        calls = []
        with mock.patch.object(canonical_hook, "dual_write_market_rows",
                               return_value={"status": "success", "inserted": 1, "skipped": 0, "errors": 0}):
            res = canonical_hook.ingest_market_authoritative(_rows(), legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "LEGACY_AUTHORITATIVE")
        self.assertEqual(calls, [1])

    def test_canonical_success_legacy_success(self):
        os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "success", "inserted": 1, "skipped": 0, "errors": 0,
                                             "attempted": 1, "quarantined": 0}):
            res = canonical_hook.ingest_market_authoritative(_rows(), legacy_writer=lambda: None)
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_SUCCESS")

    def test_canonical_success_mirror_failure_isolated(self):
        os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
        def boom():
            raise RuntimeError("mirror down")
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "success", "inserted": 1, "skipped": 0, "errors": 0,
                                             "attempted": 1, "quarantined": 0}):
            res = canonical_hook.ingest_market_authoritative(_rows(), legacy_writer=boom)
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED")
        self.assertEqual(res["health"], "DEGRADED_LEGACY_MIRROR")

    def test_canonical_failure_uses_fallback_and_queues_retry(self):
        os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0,
                                             "errors": 1, "attempted": 1, "quarantined": 0, "error": "pg down"}):
            res = canonical_hook.ingest_market_authoritative(_rows(), legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "CANONICAL_FAILED_LEGACY_FALLBACK_USED")
        self.assertEqual(calls, [1])
        manifest = (canonical_hook._OUT_DIR / "canonical_retry_manifest.jsonl").read_text(encoding="utf-8")
        self.assertIn('"pending"', manifest)
        self.assertEqual(canonical_hook.retry_backlog_count("market_price"), 1)

    def test_retry_backlog_dedups_done_entries(self):
        p = canonical_hook._OUT_DIR / "canonical_retry_manifest.jsonl"
        keys = {"companies": ["c1"]}
        p.write_text(json.dumps({"status": "pending", "domain": "market_price", "keys": keys}) + "\n"
                     + json.dumps({"status": "done", "domain": "market_price", "keys": keys}) + "\n", encoding="utf-8")
        self.assertEqual(canonical_hook.retry_backlog_count("market_price"), 0)
        self.assertEqual(canonical_hook.retry_backlog_count(), 0)

    def test_fallback_can_be_disabled(self):
        os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
        os.environ["CDF_MARKET_FALLBACK_LEGACY"] = "false"
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0,
                                             "errors": 1, "attempted": 1, "quarantined": 0, "error": "pg down"}):
            res = canonical_hook.ingest_market_authoritative(_rows(), legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "CANONICAL_FAILED")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
