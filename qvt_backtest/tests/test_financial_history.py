import datetime as dt
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_financial_history as H
import build_financial_panel as B


class HistoryTests(unittest.TestCase):
    def test_revision_does_not_leak_to_earlier_cutoff(self):
        base = {"company_id": "x", "period_end": "2020-12-31"}
        first = {**base, "tracing_no": "1", "published_at": "2021-02-01T00:00:00+00:00"}
        correction = {**base, "tracing_no": "2", "published_at": "2021-04-01T00:00:00+00:00"}
        self.assertEqual(H.select_asof([correction, first], dt.datetime(2021, 3, 1, tzinfo=dt.timezone.utc)), [first])
        self.assertEqual(H.select_asof([first, correction], dt.datetime(2021, 5, 1, tzinfo=dt.timezone.utc)), [correction])

    def test_only_own_period_column_and_explicit_unit(self):
        parsed = {"statements": {"income_statement": {"net_profit": {1: 10, 2: 9999}, "eps": {1: 5}},
                                 "balance_sheet": {"total_assets": {1: 100}, "total_liabilities": {1: 60}, "total_equity": {1: 90}}},
                  "period_headers": {"income_statement": [(1399, 12, 30)], "balance_sheet": [(1399, 12, 30)]}}
        with patch.object(H.P, "parse_report", return_value=parsed):
            facts = H.own_column("unused", "2021-03-20")
            self.assertEqual({r["metric_code"]: r["value"] for r in facts}, {"net_profit": 10e6, "eps": 5})
            self.assertEqual(H.own_column("unused", "2020-03-20"), [])

    def test_ttm_uses_only_original_own_columns(self):
        def report(period, months, revenue, profit, equity):
            return {"period_end": period, "title": f"صورت های مالی دوره {months} ماهه",
                    "tracing_no": period, "published_at": period + "T00:00:00+00:00",
                    "facts": [{"statement_type": s, "metric_code": k, "value": v} for s, k, v in
                              [("income_statement", "revenue", revenue), ("income_statement", "net_profit", profit),
                               ("balance_sheet", "total_equity", equity)]]}
        result = B.reconstruct([report("2021-06-21", 3, 40, 8, 120),
                                report("2020-06-20", 3, 30, 4, 100),
                                report("2021-03-20", 12, 120, 20, 110)])
        self.assertEqual(result["revenue_ttm"], 130)
        self.assertEqual(result["net_profit_ttm"], 24)
        self.assertAlmostEqual(result["roe_average_equity"], 24 / 110)
        self.assertIsNone(result["cash_conversion"])
        self.assertFalse(result["valuation_ready"])


if __name__ == "__main__":
    unittest.main()
