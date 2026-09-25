"""Forward-return engine. Returns are computed ONLY after the signal snapshot.

Convention (documented, frozen for the baseline): raw price return using canonical
`closing_price_rial`. Entry = next trading day strictly after the signal date
(avoids same-close look-ahead). Exit = entry + H trading days, or a specified
horizon date. corporate_actions is empty in canonical, so adjusted/total returns are
NOT produced (see CORPORATE_ACTION_AUDIT.md).
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right


def resolve_execution_date(calendar_dates, signal_date: dt.date):
    """First trading date strictly after the signal date."""
    i = bisect_right(calendar_dates, signal_date)
    return calendar_dates[i] if i < len(calendar_dates) else None


def exit_after(calendar_dates, entry_date: dt.date, horizon_days: int):
    """The H-th trading date strictly after entry_date (entry+H)."""
    i = bisect_right(calendar_dates, entry_date)
    j = i + horizon_days - 1
    return calendar_dates[j] if j < len(calendar_dates) else None


def forward_return(price_store, security_id, entry_date, exit_date):
    if entry_date is None or exit_date is None:
        return None
    p0 = price_store.close(security_id, entry_date)
    p1 = price_store.close(security_id, exit_date)
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def compute_forward_returns(price_store, calendar_dates, signals, horizons):
    """signals: list of dicts with security_id + signal_date. Returns list of rows."""
    out = []
    for s in signals:
        entry = resolve_execution_date(calendar_dates, s["signal_date"])
        row = {"company_id": s["company_id"], "security_id": s["security_id"],
               "symbol": s.get("symbol"), "signal_date": s["signal_date"],
               "execution_date": entry, "entry_price": price_store.close(s["security_id"], entry) if entry else None}
        for h in horizons:
            ex = exit_after(calendar_dates, entry, h) if entry else None
            row[f"exit_{h}"] = ex
            row[f"ret_{h}"] = forward_return(price_store, s["security_id"], entry, ex)
        out.append(row)
    return out
