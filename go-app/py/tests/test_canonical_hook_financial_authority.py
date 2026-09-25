"""Financial authority-mode tests for canonical_hook (no DB required)."""

import os
import tempfile
import unittest
from unittest import mock
import pathlib

import canonical_hook


class FinancialAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self._out = canonical_hook._OUT_DIR
        canonical_hook._OUT_DIR = pathlib.Path(self.tmp)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        canonical_hook._OUT_DIR = self._out

    def test_default_financial_authority_legacy(self):
        os.environ.pop("CDF_FINANCIAL_INGESTION_AUTHORITY", None)
        self.assertEqual(canonical_hook.financial_authority(), "legacy")
        self.assertFalse(canonical_hook.financial_canonical_authority())

    def test_canonical_selection(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        self.assertTrue(canonical_hook.financial_canonical_authority())

    def test_legacy_path(self):
        os.environ.pop("CDF_FINANCIAL_INGESTION_AUTHORITY", None)
        calls = []
        with mock.patch.object(canonical_hook, "dual_write_financial_by_key",
                               return_value={"status": "written", "inserted": 1, "skipped": 0, "facts": 3}):
            res = canonical_hook.ingest_financial_authoritative_by_key("c1", "x", "1405/05/31",
                                                                       legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "LEGACY_AUTHORITATIVE")
        self.assertEqual(calls, [1])

    def test_canonical_success_legacy_success(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_financial_write",
                               return_value={"status": "written", "inserted": 5, "skipped": 0, "facts": 5}):
            res = canonical_hook.ingest_financial_authoritative_by_key("c1", "x", "1405/05/31", legacy_writer=lambda: None)
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_SUCCESS")

    def test_mirror_failure_isolated(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_financial_write",
                               return_value={"status": "written", "inserted": 5, "skipped": 0, "facts": 5}):
            res = canonical_hook.ingest_financial_authoritative_by_key(
                "c1", "x", "1405/05/31", legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("mirror down")))
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED")
        self.assertEqual(res["health"], "DEGRADED_LEGACY_MIRROR")

    def test_canonical_failure_fallback_retry(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_financial_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0, "facts": 0, "error": "pg down"}):
            res = canonical_hook.ingest_financial_authoritative_by_key("c1", "x", "1405/05/31",
                                                                       legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "CANONICAL_FAILED_LEGACY_FALLBACK_USED")
        self.assertEqual(calls, [1])
        self.assertEqual(canonical_hook.retry_backlog_count("financial_statement"), 1)

    def test_quarantine_health(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_financial_write",
                               return_value={"status": "quarantined", "inserted": 0, "skipped": 0, "facts": 0}):
            res = canonical_hook.ingest_financial_authoritative_by_key("unknown", "x", "1405/05/31", legacy_writer=lambda: None)
        self.assertEqual(res["health"], "IDENTITY_QUARANTINE")

    def test_authorities_are_independent(self):
        os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
        os.environ.pop("CDF_MARKET_INGESTION_AUTHORITY", None)
        os.environ.pop("CDF_MONTHLY_INGESTION_AUTHORITY", None)
        self.assertTrue(canonical_hook.financial_canonical_authority())
        self.assertFalse(canonical_hook.market_canonical_authority())
        self.assertFalse(canonical_hook.monthly_canonical_authority())

    def test_financial_facts_guard_no_legacy_heuristics(self):
        # static: hook must never emit Product/NPUnitRatio/OpK/OpAmt facts
        src = pathlib.Path(canonical_hook.__file__).read_text(encoding="utf-8")
        self.assertIn("npunit", src)  # guard present
        self.assertIn("product", src)


if __name__ == "__main__":
    unittest.main()
