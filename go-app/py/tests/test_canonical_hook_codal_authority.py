"""Codal authority-mode tests for canonical_hook (no DB required)."""

import os
import tempfile
import unittest
from unittest import mock
import pathlib

import canonical_hook


class CodalAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self._out = canonical_hook._OUT_DIR
        canonical_hook._OUT_DIR = pathlib.Path(self.tmp)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        canonical_hook._OUT_DIR = self._out

    def _letter(self):
        return {"TracingNo": 1, "CompanyName": "x", "Symbol": "y", "Url": None, "Title": "t"}

    def test_default_codal_authority_legacy(self):
        os.environ.pop("CDF_CODAL_INGESTION_AUTHORITY", None)
        self.assertEqual(canonical_hook.codal_authority(), "legacy")
        self.assertFalse(canonical_hook.codal_canonical_authority())

    def test_canonical_selection(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        self.assertTrue(canonical_hook.codal_canonical_authority())

    def test_legacy_path(self):
        os.environ.pop("CDF_CODAL_INGESTION_AUTHORITY", None)
        calls = []
        with mock.patch.object(canonical_hook, "_canonical_codal_write",
                               return_value={"status": "written", "inserted": 1, "skipped": 0}):
            res = canonical_hook.ingest_codal_authoritative(self._letter(), fetch_body=False,
                                                            legacy_writer=lambda: calls.append(1))
        self.assertEqual(res["outcome"], "LEGACY_AUTHORITATIVE")
        self.assertEqual(calls, [1])

    def test_canonical_success(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_codal_write",
                               return_value={"status": "written", "inserted": 2, "skipped": 0}):
            res = canonical_hook.ingest_codal_authoritative(self._letter(), fetch_body=False)
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_SUCCESS")

    def test_canonical_success_mirror_failure(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_codal_write",
                               return_value={"status": "written", "inserted": 2, "skipped": 0}):
            res = canonical_hook.ingest_codal_authoritative(
                self._letter(), fetch_body=False,
                legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("mirror down")))
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED")

    def test_quarantine_outcome(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_codal_write",
                               return_value={"status": "quarantined", "inserted": 0, "skipped": 0}):
            res = canonical_hook.ingest_codal_authoritative(self._letter(), fetch_body=False)
        self.assertEqual(res["outcome"], "QUARANTINED_IDENTITY")
        self.assertEqual(res["health"], "IDENTITY_QUARANTINE")

    def test_canonical_failure_retry(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        with mock.patch.object(canonical_hook, "_canonical_codal_write",
                               return_value={"status": "canonical_error", "inserted": 0, "skipped": 0,
                                             "error": "pg down", "tracing_no": "1"}):
            res = canonical_hook.ingest_codal_authoritative(self._letter(), fetch_body=False, legacy_writer=lambda: None)
        self.assertEqual(res["outcome"], "CANONICAL_FAILED_LEGACY_FALLBACK_USED")
        self.assertEqual(canonical_hook.retry_backlog_count("codal_report"), 1)

    def test_authorities_independent(self):
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"
        os.environ.pop("CDF_MARKET_INGESTION_AUTHORITY", None)
        os.environ.pop("CDF_MONTHLY_INGESTION_AUTHORITY", None)
        os.environ.pop("CDF_FINANCIAL_INGESTION_AUTHORITY", None)
        self.assertTrue(canonical_hook.codal_canonical_authority())
        self.assertFalse(canonical_hook.market_canonical_authority())
        self.assertFalse(canonical_hook.monthly_canonical_authority())
        self.assertFalse(canonical_hook.financial_canonical_authority())


if __name__ == "__main__":
    unittest.main()
