"""Point-in-time universe policy (no survivorship leakage).

At each rebalance date T the eligible universe is exactly the set of companies the
canonical Engine scores using only data visible at T. No modern/universe list is
used. Tradability is evaluated only at the (future) execution date and never fed
back into signal construction.
"""

from __future__ import annotations


def evaluate_universe(signals, price_store, execution_date):
    """Split eligible signals into tradable vs excluded, with explicit reasons."""
    eligible = [s for s in signals if s.get("security_id")]
    tradable, excluded = [], []
    for s in signals:
        if not s.get("security_id"):
            excluded.append({"company_id": s["company_id"], "symbol": s.get("symbol"),
                             "reason": "no_security"})
            continue
        px = price_store.close(s["security_id"], execution_date) if execution_date else None
        if px is None:
            excluded.append({"company_id": s["company_id"], "symbol": s.get("symbol"),
                             "reason": "no_price_on_execution_date"})
        else:
            tradable.append(s)
    return {"eligible": len(signals), "with_security": len(eligible),
            "tradable": tradable, "excluded": excluded}


def track_changes(prev_ids, cur_ids):
    prev_ids, cur_ids = set(prev_ids), set(cur_ids)
    return {"additions": sorted(cur_ids - prev_ids), "removals": sorted(prev_ids - cur_ids),
            "n_prev": len(prev_ids), "n_cur": len(cur_ids)}
