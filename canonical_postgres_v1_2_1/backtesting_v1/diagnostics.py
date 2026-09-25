"""Cross-sectional diagnostics: IC, quantiles, factor IC, missingness bias, time segments.

Measurement only. No weight/formula/threshold changes.
"""

from __future__ import annotations

import math
from statistics import mean, median, pstdev


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    ra, rb = _rank(a), _rank(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return (num / (da * db)) if da > 0 and db > 0 else None


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    a = [p[0] for p in pairs]; b = [p[1] for p in pairs]
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a)); db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return (num / (da * db)) if da > 0 and db > 0 else None


def ic_by_date(rebalances, ret_key="ret"):
    out = []
    for r in rebalances:
        xs = [c.get("quant_score") for c in r["cross_section"]]
        ys = [c.get(ret_key) for c in r["cross_section"]]
        out.append({"date": r["date"], "ic": spearman(xs, ys),
                    "n": len([1 for x, y in zip(xs, ys) if x is not None and y is not None])})
    return out


def ic_summary(ic_rows):
    vals = [r["ic"] for r in ic_rows if r["ic"] is not None]
    if not vals:
        return {}
    return {"mean_ic": mean(vals), "median_ic": median(vals),
            "ic_std": pstdev(vals) if len(vals) > 1 else 0.0,
            "ic_hit_rate": sum(1 for v in vals if v > 0) / len(vals), "n_periods": len(vals)}


def quantile_diagnostics(rebalances, n_buckets=5, ret_key="ret"):
    rows = []
    spreads = []
    for r in rebalances:
        cs = [c for c in r["cross_section"] if c.get("quant_score") is not None and c.get(ret_key) is not None]
        if len(cs) < n_buckets:
            continue
        cs.sort(key=lambda c: c["quant_score"])
        size = len(cs) / n_buckets
        buckets = []
        for b in range(n_buckets):
            lo = int(b * size)
            hi = int((b + 1) * size) if b < n_buckets - 1 else len(cs)
            seg = cs[lo:hi]
            buckets.append(mean([c[ret_key] for c in seg]) if seg else None)
        spread = (buckets[-1] - buckets[0]) if (buckets[-1] is not None and buckets[0] is not None) else None
        spreads.append(spread)
        rows.append({"date": r["date"], "n": len(cs), **{f"q{b+1}": buckets[b] for b in range(n_buckets)},
                     "top_minus_bottom": spread})
    valid = [s for s in spreads if s is not None]
    return rows, {"mean_top_minus_bottom": mean(valid) if valid else None,
                  "top_minus_bottom_hit_rate": (sum(1 for s in valid if s > 0) / len(valid)) if valid else None}


def factor_ic(rebalances, factor_codes, ret_key="ret"):
    rows = []
    for fc in factor_codes:
        ics = []
        for r in rebalances:
            xs = [(c.get("factor_rank") or {}).get(fc) for c in r["cross_section"]]
            ys = [c.get(ret_key) for c in r["cross_section"]]
            v = spearman(xs, ys)
            if v is not None:
                ics.append(v)
        rows.append({"factor_code": fc,
                     "mean_ic": mean(ics) if ics else None,
                     "ic_std": pstdev(ics) if len(ics) > 1 else None,
                     "ic_hit_rate": (sum(1 for v in ics if v > 0) / len(ics)) if ics else None,
                     "n_periods": len(ics)})
    return rows


def missingness_diagnostics(rebalances, low_max, high_min, ret_key="ret"):
    buckets = {"low": [], "medium": [], "high": []}
    scores = []
    nfactors = []
    for r in rebalances:
        for c in r["cross_section"]:
            nf = c.get("n_factors_available")
            if nf is None:
                continue
            scores.append(c.get("quant_score"))
            nfactors.append(nf)
            b = "low" if nf <= low_max else ("high" if nf >= high_min else "medium")
            buckets[b].append(c.get(ret_key))
    rows = []
    for b, vals in buckets.items():
        vv = [x for x in vals if x is not None]
        rows.append({"coverage_bucket": b, "n_obs": len(vv),
                     "mean_return": mean(vv) if vv else None,
                     "hit_rate": (sum(1 for x in vv if x > 0) / len(vv)) if vv else None})
    return rows, {"pearson_quant_score_vs_n_factors": pearson(scores, nfactors)}


def time_segments(ic_rows, ret_key="ic"):
    seg = {}
    for r in ic_rows:
        y = str(r["date"])[:4]
        if r.get("ic") is not None:
            seg.setdefault(y, []).append(r["ic"])
    return [{"year": y, "mean_ic": mean(v), "n": len(v)} for y, v in sorted(seg.items())]
