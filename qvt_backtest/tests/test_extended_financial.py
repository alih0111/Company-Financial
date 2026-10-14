import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extended_financial as E


def test_expense_legs_need_proven_year_end_and_match_operating_numerator():
    headers = [(1400, 3, 31), (1399, 3, 31), (1399, 12, 30)]
    annual = {"period_end": "2021-03-20", "title": "صورت مالی 12 ماهه", "tracing_no": "annual", "facts": []}
    assert E.ttm({1: -2, 2: -1, 3: -5}, headers, 3, [annual]) == -6e6
    assert E.ttm({1: -2, 2: -1, 3: -5}, headers, 3, []) is None
    current = {"period_end": "2021-06-21", "title": "صورت مالی 3 ماهه", "tracing_no": "current"}
    parsed = {"statements": {"income_statement": {
        "revenue": {1: 200, 2: 100, 3: 300}, "operating_profit": {1: 20, 2: 10, 3: 50},
        "finance_cost": {1: -2, 2: -1, 3: -5}, "other_non_operating": {1: 1, 2: 0, 3: 2}}},
        "period_headers": {"income_statement": headers}}
    with patch.object(E.F, "reconstruct", return_value=None):
        values, reasons, _ = E.derive(current, parsed, [annual], {"operating_profit_ttm": 60e6, "operating_margin": .2})
        assert values["revenue_growth"] == 100
        assert values["interest_coverage"] == 10
        assert values["earnings_quality"] == 5
        values, reasons, _ = E.derive(current, parsed, [annual], {"operating_profit_ttm": 61e6, "operating_margin": .2})
        assert values["interest_coverage"] is None
        assert "different" in reasons["interest_coverage"]
