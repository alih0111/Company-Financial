"""Trading calendar from canonical market observations (no calendar-day assumptions)."""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right


class TradingCalendar:
    def __init__(self, dates):
        self.dates = sorted(set(dates))
        self._set = set(self.dates)

    def is_trading_day(self, d: dt.date) -> bool:
        return d in self._set

    def next_trading_day(self, d: dt.date):
        i = bisect_right(self.dates, d)
        return self.dates[i] if i < len(self.dates) else None

    def prev_trading_day(self, d: dt.date):
        i = bisect_right(self.dates, d) - 1
        return self.dates[i] if i >= 0 else None

    def add_trading_days(self, d: dt.date, n: int):
        i = bisect_right(self.dates, d) - 1  # index of d or previous
        j = i + n
        return self.dates[j] if 0 <= j < len(self.dates) else None

    def between(self, start: dt.date, end: dt.date):
        return [d for d in self.dates if start <= d <= end]


def month_end_rebalance_dates(cal: TradingCalendar, start: dt.date, end: dt.date):
    """Last trading day of each calendar month in [start, end]."""
    out = []
    by_month = {}
    for d in cal.between(start, end):
        by_month[(d.year, d.month)] = d
    for k in sorted(by_month):
        out.append(by_month[k])
    return out


def week_end_rebalance_dates(cal: TradingCalendar, start: dt.date, end: dt.date):
    out = []
    by_week = {}
    for d in cal.between(start, end):
        iso = d.isocalendar()
        by_week[(iso[0], iso[1])] = d
    for k in sorted(by_week):
        out.append(by_week[k])
    return out


def quarter_end_rebalance_dates(cal: TradingCalendar, start: dt.date, end: dt.date):
    out = []
    by_q = {}
    for d in cal.between(start, end):
        by_q[(d.year, (d.month - 1) // 3)] = d
    for k in sorted(by_q):
        out.append(by_q[k])
    return out


def rebalance_dates(cal: TradingCalendar, freq: str, start: dt.date, end: dt.date):
    f = freq.upper()
    if f == "W":
        return week_end_rebalance_dates(cal, start, end)
    if f == "Q":
        return quarter_end_rebalance_dates(cal, start, end)
    return month_end_rebalance_dates(cal, start, end)
