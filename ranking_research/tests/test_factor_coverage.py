import pandas as pd
import pytest

from scripts.build_factor_coverage import UNITS, coverage_rows


def test_factor_coverage_preserves_missing_and_rejected_values_without_scoring():
    factors = list(UNITS)
    panel_row = {key: 1.0 for key in factors}
    panel_row.update(company_id="one", symbol="TEST", pe=100.0,
                     volatility_30d=float("nan"), sales_growth_12m=float("nan"))
    observed = {key: True for key in factors}
    observed.update(pe=False, volatility_30d=False, sales_growth_12m=False)
    raw = {key: (None if pd.isna(value) else value) for key, value in panel_row.items() if key in UNITS}
    method = {"score": None, "financial_factor_coverage": 0.4, "scoreability_reason": "fixture insufficient data"}
    ranking_row = {"company_id": "one", "symbol": "TEST", "raw_factors": raw,
                   "observed_factors": observed, "masked_factors": ["pe"],
                   "defaulted_factors": ["pe", "sales_growth_12m"],
                   "methods": {"P1": method, "P3": method}}
    rank = {"rows": [ranking_row], "evaluation_date": "2026-10-21", "artifact_sha256": "a" * 64}
    contract = {"factor_order": factors,
                "methods": [{"method_id": "P1", "weights": [1.0] * len(factors)},
                            {"method_id": "P3", "weights": [2.0] * len(factors)}]}
    extraction = {"factors": {"volatility_30d": "masked: incomplete corporate actions"}}
    rows = {r["factor"]: r for r in coverage_rows(pd.DataFrame([panel_row]), rank, contract, extraction)}
    assert len(rows) == 21
    assert rows["pe"]["value"] == 100 and rows["pe"]["missing_reason"] == "VALUE_REJECTED_BY_MODEL_MASK"
    assert rows["volatility_30d"]["value"] is None
    assert rows["volatility_30d"]["missing_reason"] == "CORPORATE_ACTION_CHAIN_NOT_VERIFIED_AFTER_2026_09_30"
    assert rows["volatility_30d"]["included_in_financial_coverage"] is False
    assert rows["volatility_30d"]["p1_missing_coverage_weight"] == 0
    assert rows["sales_growth_12m"]["missing_reason"] == "MISSING_REASON_NOT_RECORDED"
    assert rows["sales_growth_12m"]["p3_missing_weight"] == 2.0
    assert rows["sales_growth_12m"]["p1_score"] is None
    assert rows["sales_growth_12m"]["p1_financial_coverage"] == 0.4
    assert rows["sales_growth_12m"]["received_at_status"] == "NOT_PROVEN_PER_FACTOR"
    ranking_row["raw_factors"]["pe"] = 7.0
    with pytest.raises(ValueError, match="COVERAGE_VALUE_MISMATCH"):
        coverage_rows(pd.DataFrame([panel_row]), rank, contract, extraction)
