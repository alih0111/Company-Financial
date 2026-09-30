"""Canonical market-data store for the backtester (canonical-only; PIT-aware).

Signals are reconstructed by the canonical Engine using source_cutoff_at; this
store is used ONLY for execution/exit prices after the signal snapshot is frozen.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))


class PriceStore:
    def __init__(self, rows):
        # rows: (security_id, trade_date, closing_price_rial)
        self.closes = {}
        self._date_cache = {}
        dates = set()
        for sid, d, close in rows:
            self.closes.setdefault(sid, {})[d] = None if close is None else float(close)
            dates.add(d)
        self.dates = sorted(dates)

    def close(self, security_id, d):
        v = self.closes.get(security_id, {}).get(d)
        if v is not None and v > 0:
            return v
        return None

    def last_close_on_or_before(self, security_id, d):
        s = self.closes.get(security_id)
        if not s:
            return None
        cand = [x for x in s if x <= d and s[x] and s[x] > 0]
        return s[max(cand)] if cand else None

    def _valid_dates(self, security_id):
        """Sorted dates with a usable close, cached per security.

        Covariance estimation queries a PIT window per rebalance, so the naive
        dict scan would be O(dates) per call; bisecting a cached sorted list
        keeps it cheap without changing any returned value.
        """
        cached = self._date_cache.get(security_id)
        if cached is None:
            s = self.closes.get(security_id) or {}
            cached = sorted(d for d, v in s.items() if v and v > 0)
            self._date_cache[security_id] = cached
        return cached

    def window_dates(self, security_id, end_date, n):
        """PIT window: last n usable trading dates on or before ``end_date``."""
        dates = self._valid_dates(security_id)
        if not dates:
            return []
        import bisect
        hi = bisect.bisect_right(dates, end_date)
        if hi <= 0:
            return []
        lo = max(0, hi - n) if n and n > 0 else 0
        return dates[lo:hi]

    def window_closes(self, security_id, end_date, n):
        """Closes matching window_dates (oldest→newest)."""
        s = self.closes.get(security_id) or {}
        return [s[d] for d in self.window_dates(security_id, end_date, n)]


def load_price_store(cutoff=None):
    """Load canonical price observations. ``cutoff`` limits loaded trade_date (max)."""
    from common import pg_pilot_conn
    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    if cutoff is None:
        cur.execute("SELECT security_id::text, trade_date, closing_price_rial FROM market.price_observations")
    else:
        cur.execute("SELECT security_id::text, trade_date, closing_price_rial FROM market.price_observations WHERE trade_date <= %s", (cutoff,))
    rows = cur.fetchall()
    pg.close()
    return PriceStore(rows)
