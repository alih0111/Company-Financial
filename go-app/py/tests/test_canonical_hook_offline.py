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

    def test_facts_from_values_comparatives_map_to_order_2_and_3(self):
        facts = canonical_hook.facts_from_values(values={
            "revenue": 1000, "revenue_last_year": 600, "revenue_fy_prev": 500,
            "operating_profit": 200, "operating_profit_last_year": 120,
            "net_profit_last_year": 90,
            "eps": 255, "eps_last_year": 180, "eps_fy_prev": 150,
            "operating_eps_last_year": 190,
        })
        by_order = {(f["metric_code"], f["period_order"]): f for f in facts}
        self.assertEqual(by_order[("revenue", 2)]["comparison_type"], "prior_year_same_period")
        self.assertEqual(float(by_order[("revenue", 2)]["canonical_value"]), 600 * 1_000_000)
        self.assertEqual(by_order[("revenue", 3)]["comparison_type"], "prior_fiscal_year")
        self.assertEqual(float(by_order[("revenue", 3)]["canonical_value"]), 500 * 1_000_000)
        self.assertEqual(by_order[("operating_profit", 2)]["comparison_type"], "prior_year_same_period")
        self.assertEqual(by_order[("net_profit", 2)]["comparison_type"], "prior_year_same_period")
        self.assertEqual(by_order[("eps", 2)]["canonical_unit"], "rial_per_share")
        self.assertEqual(float(by_order[("eps", 2)]["canonical_value"]), 180)
        self.assertEqual(by_order[("eps", 3)]["comparison_type"], "prior_fiscal_year")
        self.assertEqual(float(by_order[("operating_eps", 2)]["canonical_value"]), 190)
        # current-period facts keep their existing shape
        self.assertEqual(by_order[("revenue", 1)]["comparison_type"], "current")

    def test_facts_from_values_zero_comparative_is_absent_not_zero(self):
        # to_number maps an absent "-" comparative cell to 0.0; a fabricated zero
        # would corrupt the analytics TTM (cur + fy_prev - ly), so it is omitted.
        facts = canonical_hook.facts_from_values(values={
            "revenue": 1000, "revenue_last_year": 0.0, "revenue_fy_prev": 0.0,
            "operating_profit_last_year": 0.0,
        })
        self.assertEqual([f["metric_code"] for f in facts if f["period_order"] != 1], [])
        self.assertEqual(len([f for f in facts if f["metric_code"] == "revenue"]), 1)

    def test_facts_from_values_rejects_non_statement_comparatives(self):
        # only _FACT_MAP metrics accept comparatives; unknown/unsupported keys
        # (e.g. balance-sheet or finance_cost suffixes) are ignored as before
        facts = canonical_hook.facts_from_values(values={
            "total_assets": 100, "total_assets_last_year": 90,
            "finance_cost": -10, "finance_cost_last_year": -5,
            "capital": 625, "capital_last_year": 500,
        })
        # capital is not part of the emitted fact set (pre-existing behavior)
        self.assertEqual([f["period_order"] for f in facts], [1, 1])


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
