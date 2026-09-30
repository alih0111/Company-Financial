"""Risk-based weighting for the frozen PIT backtest.

Deterministic and solver-free, mirroring go-app/quant/portfolio.go so the live
assistant and the backtest speak the same language:

  * equal          → equal weights, then capped (transparent rules baseline)
  * inverse_vol    → w ∝ 1/σ, capped
  * min_variance   → projected-gradient minimisation of wᵀΣw on the simplex
                     {w ≥ 0, Σw = 1, w ≤ cap}, no external solver

Point-in-time discipline: weights for a rebalance on signal date T use only
closing prices with trade_date ≤ T, so nothing from the holding period leaks in.
Covariance is estimated on the PIT window, shrunk toward its diagonal, and
annualized with 250 trading days.
"""

from __future__ import annotations

import math

DEFAULT_CAP = 0.15
DEFAULT_WINDOW = 250
SHRINKAGE = 0.3
MIN_OBSERVATIONS = 120
TRADING_DAYS = 250


def daily_returns(closes):
    out = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev and cur and prev > 0 and cur > 0:
            out.append((cur - prev) / prev)
        else:
            out.append(None)
    return out


def aligned_returns(series_by_key, min_obs=MIN_OBSERVATIONS):
    """series_by_key: {date -> close} per key (already PIT-filtered).

    Returns (keys, matrix, start_row) where matrix[k] is the return series on the
    union calendar; start_row is the first column where every series has a real
    observation (columns before that are pre-listing padding and are excluded
    from covariance).
    """
    keys = sorted(series_by_key)
    calendar = sorted({d for s in series_by_key.values() for d in s})
    if not calendar:
        return [], [], 0
    matrix = []
    starts = []
    for k in keys:
        s = series_by_key[k]
        closes = []
        last = None
        for d in calendar:
            px = s.get(d)
            if px is not None and px > 0:
                last = px
            closes.append(last)
        rets = []
        first = -1
        valid = 0
        for i in range(1, len(closes)):
            a, b = closes[i - 1], closes[i]
            if a and b and a > 0 and b > 0:
                rets.append((b - a) / a)
                valid += 1
                if first < 0:
                    first = i - 1
            else:
                rets.append(0.0)
        matrix.append(rets)
        starts.append(first)
        if valid < min_obs:
            return [], [], 0
    return keys, matrix, max(starts)


def covariance(matrix, start_row, annualize=TRADING_DAYS):
    n = len(matrix)
    if n == 0:
        return []
    rows = min(len(r) for r in matrix)
    if rows - start_row < 2:
        return [[0.0] * n for _ in range(n)]
    count = float(rows - start_row)
    means = [sum(matrix[i][start_row:rows]) / count for i in range(n)]
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = 0.0
            for t in range(start_row, rows):
                s += (matrix[i][t] - means[i]) * (matrix[j][t] - means[j])
            c = s / (count - 1)
            if annualize:
                c *= annualize
            cov[i][j] = c
            cov[j][i] = c
    return cov


def shrink(cov, lam=SHRINKAGE):
    n = len(cov)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            out[i][j] = cov[i][j] if i == j else (1 - lam) * cov[i][j]
    return out


def apply_cap(w, cap):
    n = len(w)
    if n == 0:
        return w
    if cap <= 0 or cap > 1:
        cap = 1.0
    if n * cap < 1:
        return [1.0 / n] * n
    out = [min(max(x, 0.0), cap) for x in w]
    for _ in range(100):
        diff = 1.0 - sum(out)
        if abs(diff) < 1e-12:
            break
        free = [i for i, v in enumerate(out) if (v < cap if diff > 0 else v > 0)]
        if not free:
            break
        share = diff / len(free)
        for i in free:
            out[i] = min(max(out[i] + share, 0.0), cap)
    return out


def equal_weights(n, cap=DEFAULT_CAP):
    if n == 0:
        return []
    return apply_cap([1.0 / n] * n, cap)


def inverse_vol(cov, cap=DEFAULT_CAP):
    n = len(cov)
    if n == 0:
        return []
    raw = []
    for i in range(n):
        v = cov[i][i]
        raw.append(1.0 / math.sqrt(v) if v > 0 else 0.0)
    total = sum(raw)
    if total <= 0:
        return equal_weights(n, cap)
    return apply_cap([x / total for x in raw], cap)


def min_variance(cov, cap=DEFAULT_CAP, iterations=1200):
    n = len(cov)
    if n == 0:
        return []
    w = equal_weights(n, cap)
    lipschitz = max((sum(abs(cov[i][j]) for j in range(n)) for i in range(n)), default=0.0)
    if lipschitz <= 0:
        return w
    step = 1.0 / lipschitz
    for _ in range(iterations):
        grad = [sum(cov[i][j] * w[j] for j in range(n)) for i in range(n)]
        mb = sum(grad) / n
        w = [w[i] - 2 * step * (grad[i] - mb) for i in range(n)]
        w = apply_cap(w, cap)
    return w


def weights_for(price_store, members, signal_date, method, window=DEFAULT_WINDOW, cap=DEFAULT_CAP):
    """PIT weights for one rebalance.

    members: iterable of signal dicts with company_id + security_id.
    signal_date: the date the decision is made; only closes ≤ it are used.

    Returns (weights_by_company_id, info). Companies with insufficient PIT price
    history are dropped from the weighted basket (reported in info), never
    filled with fabricated data.
    """
    series = {}
    meta = {}
    dropped = []
    for m in members:
        sid = m.get("security_id")
        cid = m.get("company_id")
        if not sid:
            dropped.append(cid)
            continue
        closes = price_store.window_closes(sid, signal_date, window)
        if len(closes) < MIN_OBSERVATIONS + 1:
            dropped.append(cid)
            continue
        series[cid] = closes
        meta[cid] = {"dates": price_store.window_dates(sid, signal_date, window)}
    if len(series) < 3:
        return {}, {"method": method, "reason": "not enough PIT history", "dropped": dropped}

    by_key = {}
    for cid, closes in series.items():
        by_key[cid] = dict(zip(meta[cid]["dates"], closes))
    keys, matrix, start_row = aligned_returns(by_key)
    if not keys:
        return {}, {"method": method, "reason": "insufficient aligned history", "dropped": dropped}

    cov = shrink(covariance(matrix, start_row))
    if method == "inverse_vol":
        w = inverse_vol(cov, cap)
    elif method == "min_variance":
        w = min_variance(cov, cap)
    else:
        method = "equal"
        w = equal_weights(len(keys), cap)
    weights = {k: w[i] for i, k in enumerate(keys)}
    info = {"method": method, "n_weighted": len(keys), "n_observations": max(len(matrix[0]) - start_row, 0),
            "dropped": dropped}
    return weights, info
