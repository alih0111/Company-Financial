import pandas as pd
import pytest
import jdatetime

from ranking_research.future_eval_v12_30.monthly_sales_replay import build_monthly


def test_monthly_growth_requires_contiguous_comparable_periods_and_verified_corrections():
    events = []
    for index, period in enumerate(pd.date_range("2024-01-31", periods=24, freq="ME")):
        publication = period + pd.Timedelta(days=1)
        events.append({"event_id": f"original-{index:02d}", "company_id": "one", "period_end": period,
                       "signal_entry_date": publication, "published_at": publication.isoformat() + "+00:00",
                       "is_correction": False, "current_value_version_known": True,
                       "CURRENT_PERIOD_SALES": 100.0 if index < 12 else 200.0})
    corrected_period = pd.Timestamp("2025-03-31")
    events.extend([
        {"event_id": "correction-unverified", "company_id": "one", "period_end": corrected_period,
         "signal_entry_date": None, "published_at": "2026-01-11T08:00:00+00:00", "is_correction": True,
         "current_value_version_known": False, "CURRENT_PERIOD_SALES": None},
        {"event_id": "correction-verified", "company_id": "one", "period_end": corrected_period,
         "signal_entry_date": None, "published_at": "2026-01-13T08:00:00+00:00", "is_correction": True,
         "current_value_version_known": True, "CURRENT_PERIOD_SALES": 180.0},
    ])
    days = ["2026-01-10", "2026-01-12", "2026-01-14"]
    result = build_monthly(pd.DataFrame(events), pd.DataFrame([{"company_id": "one", "symbol": "TEST"}]),
                           days, [], keep_corrections=True).set_index("decision_time")
    assert result.loc[days[0], "sales_growth_12m"] == pytest.approx(100.0)
    assert result.loc[days[0], "sales_growth_3m"] == pytest.approx(0.0)
    assert pd.isna(result.loc[days[1], "sales_growth_12m"])
    assert result.loc[days[1], "missing_reason_12m"] == "insufficient_or_noncontiguous_24m"
    assert result.loc[days[1], "sales_growth_3m"] == pytest.approx(0.0)
    assert result.loc[days[2], "sales_growth_12m"] == pytest.approx((2380 - 1200) / 1200 * 100)


def test_monthly_growth_uses_jalali_periods_across_new_year():
    events = []
    for year in (1403, 1404):
        for month in range(1, 13):
            period = pd.Timestamp(jdatetime.date(year, month, 29).togregorian())
            publication = period + pd.Timedelta(days=1)
            events.append({"event_id": f"{year}-{month:02d}", "company_id": "one", "period_end": period,
                           "signal_entry_date": publication, "published_at": publication.isoformat() + "+00:00",
                           "is_correction": False, "current_value_version_known": True,
                           "CURRENT_PERIOD_SALES": 100.0 if year == 1403 else 200.0})
    result = build_monthly(pd.DataFrame(events), pd.DataFrame([{"company_id": "one", "symbol": "TEST"}]),
                           ["2026-04-01"], [], jalali=True, keep_corrections=True).iloc[0]
    assert result["latest_period"] == "1404-12"
    assert result["sales_growth_12m"] == pytest.approx(100.0)
    assert result["sales_growth_3m"] == pytest.approx(0.0)
