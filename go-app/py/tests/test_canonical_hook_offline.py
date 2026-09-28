"""Offline decoupling tests for canonical ingestion (no DB / no SQL Server)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

GO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GO not in sys.path:
    sys.path.insert(0, GO)

os.environ["CDF_INGESTION_MODE"] = "dual_write"
os.environ["CDF_SQLSERVER_MODE"] = "offline_expected"
os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"

import canonical_hook  # noqa: E402


class OfflineModeTests(unittest.TestCase):
    def test_canonical_only_offline_true(self):
        os.environ["CDF_SQLSERVER_MODE"] = "offline_expected"
        os.environ["CDF_INGESTION_MODE"] = "dual_write"
        self.assertTrue(canonical_hook.canonical_only_offline())
        self.assertEqual(canonical_hook.mirror_status_for_sql(), "offline_expected")

    def test_sql_required_when_active_legacy_authority(self):
        os.environ["CDF_SQLSERVER_MODE"] = "active"
        prev = os.environ.get("CDF_CODAL_INGESTION_AUTHORITY")
        os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "legacy"
        try:
            self.assertTrue(canonical_hook.sql_connection_required())
        finally:
            if prev is None:
                os.environ.pop("CDF_CODAL_INGESTION_AUTHORITY", None)
            else:
                os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = prev
        os.environ["CDF_SQLSERVER_MODE"] = "offline_expected"

    def test_facts_from_values_units_and_no_forbidden(self):
        facts = canonical_hook.facts_from_values(values={
            "eps": 255, "revenue": 1000, "net_profit": -5,
        })
        by = {f["metric_code"]: f for f in facts}
        self.assertEqual(by["eps"]["canonical_unit"], "rial_per_share")
        self.assertEqual(by["revenue"]["canonical_unit"], "rial")
        self.assertEqual(float(by["revenue"]["canonical_value"]), 1000 * 1_000_000)
        for f in facts:
            self.assertNotIn(f["metric_code"].lower(), ("product1", "product2", "product3"))


class MirrorVsCanonicalFailureTests(unittest.TestCase):
    def test_mirror_failure_is_canonical_success(self):
        payload = [{"company_id": "x", "gregorian_date": "2026-01-01", "closing_price": 1}]
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "success", "attempted": 1, "inserted": 1,
                                             "skipped": 0, "quarantined": 0, "errors": 0}), \
             mock.patch.object(canonical_hook, "_retry_record") as retry:
            res = canonical_hook.ingest_market_authoritative(
                payload, legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("sql offline")))
        self.assertEqual(res["outcome"], "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED")
        retry.assert_not_called()  # mirror failure must NOT enqueue a canonical retry

    def test_canonical_failure_enqueues_retry(self):
        payload = [{"company_id": "x", "gregorian_date": "2026-01-01", "closing_price": 1}]
        with mock.patch.object(canonical_hook, "_canonical_market_write",
                               return_value={"status": "canonical_error", "attempted": 1, "inserted": 0,
                                             "skipped": 0, "quarantined": 0, "errors": 1, "error": "pg down"}), \
             mock.patch.object(canonical_hook, "_retry_record") as retry:
            res = canonical_hook.ingest_market_authoritative(payload, legacy_writer=None)
        self.assertEqual(res["outcome"], "CANONICAL_FAILED")
        retry.assert_called_once()  # canonical failure DOES enqueue a canonical retry


if __name__ == "__main__":
    unittest.main()
