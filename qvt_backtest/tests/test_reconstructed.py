import datetime as dt
import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reconstructed_replay as B


class ReconstructedTests(unittest.TestCase):
    def test_monthly_observed_sessions_not_skipped_for_day_of_month(self):
        dates = ["2022-05-31", "2022-06-29", "2022-07-31"]
        self.assertEqual(B.decision_schedule(dates, 1), dates)
        self.assertEqual(B.decision_schedule(dates + ["2022-11-30"], 6), ["2022-05-31", "2022-11-30"])

    def test_future_share_evidence_refused_and_identity_checked(self):
        iv = {"company_id": "c", "security_id": "s", "status": "KNOWN", "valid_from": "2020-01-01",
              "valid_to": None, "knowledge_from": "2022-01-01T00:00:00+00:00", "evidence": {"report": "1"}, "shares_outstanding": 100}
        args = ({"A": [iv]}, "A", "c", "s")
        self.assertIsNone(B.resolve_shares(*args, "2021-01-01", "2020-12-30"))
        self.assertIsNotNone(B.resolve_shares(*args, "2023-01-01", "2022-12-31"))
        self.assertIsNone(B.resolve_shares({"A": [iv]}, "A", "other", "s", "2023-01-01", "2022-12-31"))

    def test_final_mark_does_not_trade_and_failed_target_stays_cash(self):
        RA = B.R.V.load_portfolio_engine()
        selected = pd.DataFrame({"as_of": ["2022-01-01", "2022-02-01"], "symbol": ["A", "B"], "ui_score": [10, 20]})
        cal = ["2022-01-02", "2022-02-02"]
        adj = {"A": {"dates": cal, "adj": dict(zip(cal, [10, 20]))}, "B": {"dates": cal, "adj": dict(zip(cal, [10, 10]))}}
        perf, daily, ledger, trades = B.replay(selected, list(selected.as_of), adj, cal, {("2022-01-02", "A")}, 1, .005, RA)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(daily[-1]["nav"], 2 / 1.005)
        self.assertEqual(ledger[0]["exec_date"], "2022-01-02")
        _, cash_daily, failed, _ = B.replay(selected, list(selected.as_of), adj, cal, set(), 1, .005, RA)
        self.assertEqual(cash_daily[-1]["nav"], 1)
        self.assertEqual(failed[0]["failed_targets"], 1)


if __name__ == "__main__":
    unittest.main()
