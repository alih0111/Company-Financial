"""Serialize monthly-sales lineage without inventing missing observations."""
import json

import pandas as pd


def encode_sales_lineage(versions, latest_period, known_months, source):
    period = None if latest_period is None or pd.isna(latest_period) else latest_period
    return json.dumps({
        "selected_month_versions": versions,
        "latest_period": period,
        "known_months": known_months,
        "source": source,
        "received_at": None,
        "correction_policy": "V11 verified correction replay; unverified correction masks previous value",
    }, ensure_ascii=False, allow_nan=False)
