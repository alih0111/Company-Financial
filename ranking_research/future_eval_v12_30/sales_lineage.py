"""Serialize monthly-sales lineage without inventing missing observations."""
import json
import math

import pandas as pd


def monthly_missing_reasons(month_row, values):
    keys = {"sales_growth_12m": "missing_reason_12m", "sales_growth_3m": "missing_reason_3m",
            "sales_stability": "missing_reason_stability"}
    result = {}
    for factor, key in keys.items():
        value = values.get(factor)
        if value is not None and pd.notna(value) and math.isfinite(float(value)):
            continue
        reason = month_row.get(key) if month_row is not None else None
        result[factor] = str(reason) if reason is not None and pd.notna(reason) else "reason_not_recorded"
    return result


def encode_sales_lineage(versions, latest_period, known_months, source, missing_reasons=None):
    period = None if latest_period is None or pd.isna(latest_period) else latest_period
    return json.dumps({
        "selected_month_versions": versions,
        "latest_period": period,
        "known_months": known_months,
        "source": source,
        "received_at": None,
        "missing_reasons": missing_reasons or {},
        "correction_policy": "V11 verified correction replay; unverified correction masks previous value",
    }, ensure_ascii=False, allow_nan=False)
