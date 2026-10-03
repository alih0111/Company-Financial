"""RESEARCH PROGRAM DECISION — supplementary diagnostic panel (Development only).

Completes the Part-2 panel columns that the base script did not persist, and adds a
permutation/hypergeometric significance test for the Part-3 regime question:

  per-date factor rank correlations (mean pairwise + LowVol|PERank + LowVol|growth family)
  LowVolatilityRank composite weight share per date
  cross-sectional composite dispersion (EX-ANTE: scores are known at the signal close)
  cross-sectional factor-IC dispersion (descriptive)
  hypergeometric p-values for negative-date concentration in the HIGH half of every
  ex-ante state variable.

Diagnostic only. No candidate is built, no factor removed/reweighted, no threshold moved,
no return-derived label, no 2024/2025/2026 input, no external macro variable.
Writes output/research_decision_panel_ext.json (does not touch the frozen base panel).
"""
from __future__ import annotations

import bisect
import datetime as dt
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_v2 as M  # noqa: E402
import model_v2_1 as V  # noqa: E402
from model_v2_direct_rebaseline_v2 import direct_ranks, rows_with_direct, symbol_map  # noqa: E402

ADJUSTED = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals_adjusted_v1.csv")
PE2 = Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output\pe_direct_universe_v2.jsonl")
RAW = Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output\raw_closing_universe")
OUT = HERE / "output" / "research_decision_panel_ext.json"
W = 1.0 / len(V.ROBUST)


def robust_score(r):
    num = den = 0.0
    for f in V.ROBUST:
        if r["avail"].get(f) and r["ranks"].get(f) is not None:
            num += W * float(r["ranks"][f])
            den += W
    return num / den if den > 0 else None


def hv(x):
    return f"{x[:4]}-{x[4:6]}-{x[6:8]}"


def main() -> int:
    rows = M.load_signals(ADJUSTED)
    dmap, smap = direct_ranks(), symbol_map()
    rows_direct, _, _ = rows_with_direct(rows, dmap, smap)
    dev = M.period_rows(rows_direct, "development")

    cs = {}
    for r in dev:
        s = robust_score(r)
        if s is not None:
            cs.setdefault(r["signal_date"], []).append((s, r))
    dates = sorted(cs)

    # ---------- ex-ante state variables (identical construction to base script) ----------
    syms = [s for s in (RAW.parent / "research_symbols_238.txt").read_text(encoding="utf-8").split("\n") if s.strip()]
    idx = json.loads((RAW.parent / "tsetmc_share" / "index.json").read_text(encoding="utf-8"))
    series = {}
    for sym in syms:
        ins = (idx.get(sym) or {}).get("ins_code")
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        series[sym] = ([hv(str(r["dEven"])) for r in recs], [float(r["pClosing"]) for r in recs])
    pe = {}
    for line in PE2.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            pe.setdefault(r["signal_date"], []).append(r.get("PE_DIRECT"))
    ev = {}
    import os
    os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
    import psycopg
    with psycopg.connect("postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121") as pg, pg.cursor() as cur:
        cur.execute("""SELECT s.codal_symbol, ca.action_date FROM market.corporate_actions ca
                       JOIN core.securities s ON s.id=ca.security_id
                       WHERE ca.source='tsetmc_gap_rule_v1' AND ca.action_type IN
                       ('capital_increase','rights_issue','reverse_split','stock_dividend')""")
        for sym, d in cur.fetchall():
            ev.setdefault(sym, set()).add(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)))

    state = {}
    for d in dates:
        dd = dt.date.fromisoformat(d)
        r21s, vols = [], []
        for sym, (ds, ps) in series.items():
            i = bisect.bisect_right(ds, d) - 1
            if i < 21 or ps[i] <= 0 or ps[i - 21] <= 0:
                continue
            r21s.append(ps[i] / ps[i - 21] - 1.0)
            vols.append(float(np.std([ps[j] / ps[j - 1] - 1.0 for j in range(i - 20, i + 1)], ddof=1)))
        pl = pe.get(d, [])
        valid = [x for x in pl if x and 0 < x <= 60]
        neg = [x for x in pl if x is not None and x <= 0]
        n_cap = sum(1 for sym, exs in ev.items() if any(dd - 63 * dt.timedelta(days=1) < x <= dd for x in exs))
        state[d] = {
            "breadth": float(np.mean([x > 0 for x in r21s])) if r21s else None,
            "mkt_ret21_med": float(np.median(r21s)) if r21s else None,
            "xsec_disp21": float(np.std(r21s, ddof=1)) if len(r21s) > 1 else None,
            "vol_level": float(np.median(vols)) if vols else None,
            "neg_pe_frac": (len(neg) / (len(neg) + len(valid))) if (neg or valid) else None,
            "pe_disp": float(np.std([np.log(x) for x in valid], ddof=1)) if len(valid) > 1 else None,
            "recent_capital_frac": n_cap / len(r21s) if r21s else None,
        }

    # ---------- per-date extended panel ----------
    pair_keys = [(a, b) for i, a in enumerate(V.ROBUST) for b in V.ROBUST[i + 1:]]
    growth = [f for f in V.ROBUST if f != "PERank" and f != "LowVolatilityRank"]
    panel = {}
    for d in dates:
        rs = [r for _, r in cs[d]]
        scored = [robust_score(r) for r in rs]
        ic = None
        pairs = [(robust_score(r), r["ret_21"]) for r in rs if r["ret_21"] is not None]
        if len(pairs) >= 5:
            ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])

        def fac_ic(f):
            pr = [(r["ranks"].get(f), r["ret_21"]) for r in rs
                  if r["avail"].get(f) and r["ranks"].get(f) is not None and r["ret_21"] is not None]
            return M.spearman([p[0] for p in pr], [p[1] for p in pr]) if len(pr) >= 5 else None

        fics = {f: fac_ic(f) for f in V.ROBUST}

        # per-date mean pairwise factor rank correlation + key pairs
        pcs = []
        for a, b in pair_keys:
            pr = [(r["ranks"].get(a), r["ranks"].get(b)) for r in rs
                  if r["avail"].get(a) and r["avail"].get(b)
                  and r["ranks"].get(a) is not None and r["ranks"].get(b) is not None]
            if len(pr) >= 5:
                pcs.append(M.spearman([p[0] for p in pr], [p[1] for p in pr]))

        def pair_corr(a, b):
            pr = [(r["ranks"].get(a), r["ranks"].get(b)) for r in rs
                  if r["avail"].get(a) and r["avail"].get(b)
                  and r["ranks"].get(a) is not None and r["ranks"].get(b) is not None]
            return M.spearman([p[0] for p in pr], [p[1] for p in pr]) if len(pr) >= 5 else None

        lv_growth = [pair_corr("LowVolatilityRank", g) for g in growth]
        lv_growth = [x for x in lv_growth if x is not None]

        # LowVol composite weight share (ex-ante; how much of the score LowVol carries)
        shares = []
        for r in rs:
            den = sum(W for f in V.ROBUST if r["avail"].get(f) and r["ranks"].get(f) is not None)
            if den > 0 and r["avail"].get("LowVolatilityRank") and r["ranks"].get("LowVolatilityRank") is not None:
                shares.append(W / den)
        fics_v = [v for v in fics.values() if v is not None]
        panel[d] = {
            "ic21": ic,
            "n": len(rs),
            "composite_disp": float(np.std([s for s in scored if s is not None], ddof=1)),
            "fac_ic": fics,
            "fac_ic_disp": float(np.std(fics_v, ddof=1)) if len(fics_v) > 1 else None,
            "factor_rank_corr_mean": float(np.mean(pcs)) if pcs else None,
            "corr_LowVol_PERank": pair_corr("LowVolatilityRank", "PERank"),
            "corr_LowVol_growth_family": float(np.mean(lv_growth)) if lv_growth else None,
            "lowvol_weight_share": float(np.mean(shares)) if shares else None,
            "turnover": None,  # populated below (needs chronological order)
            **state[d],
        }

    # turnover (top-20 overlap), chronological
    prev_top = set()
    for d in dates:
        rs = [r for _, r in cs[d]]
        elig = sorted([r for r in rs if r["ret_21"] is not None], key=lambda r: -robust_score(r))
        top = {r["company_id"] for r in elig[:20]}
        panel[d]["turnover"] = (1.0 - len(top & prev_top) / len(top | prev_top)) if prev_top and top else None
        prev_top = top

    # ---------- Part 3: hypergeometric significance of negative-date concentration ----------
    ics = {d: panel[d]["ic21"] for d in dates if panel[d]["ic21"] is not None}
    neg_dates = [d for d in dates if ics.get(d) is not None and ics[d] < 0]
    neg_total = len(neg_dates)
    variables = ["breadth", "mkt_ret21_med", "xsec_disp21", "vol_level", "neg_pe_frac",
                 "pe_disp", "recent_capital_frac", "composite_disp"]

    def hyper_ge(k, N, K, n):
        return sum(math.comb(K, i) * math.comb(N - K, n - i) / math.comb(N, n)
                   for i in range(k, min(K, n) + 1) if 0 <= n - i <= N - K)

    tests = {}
    for v in variables:
        xs = sorted(((d, panel[d][v]) for d in dates if panel[d].get(v) is not None and ics.get(d) is not None),
                    key=lambda x: x[1])
        n = len(xs)
        half = n // 2
        low, high = [d for d, _ in xs[:half]], [d for d, _ in xs[half:]]
        obs = sum(1 for d in high if d in neg_dates)
        expected = neg_total * len(high) / n if n else float("nan")
        p_ge = hyper_ge(obs, n, neg_total, len(high)) if neg_total and n else None
        ics_v = [panel[d][v] for d in dates if panel[d].get(v) is not None and ics.get(d) is not None]
        corr = float(np.corrcoef(ics_v, [ics[d] for d in dates if panel[d].get(v) is not None and ics.get(d) is not None])[0, 1]) if len(ics_v) > 2 else None
        tests[v] = {
            "n_dates": n,
            "mean_ic_low_half": float(np.mean([ics[d] for d in low])),
            "mean_ic_high_half": float(np.mean([ics[d] for d in high])),
            "pos_frac_low": float(np.mean([ics[d] > 0 for d in low])),
            "pos_frac_high": float(np.mean([ics[d] > 0 for d in high])),
            "neg_dates_in_high_half": obs,
            "neg_dates_expected_by_chance": round(expected, 2),
            "p_hyper_ge_observed": p_ge,
            "corr_variable_vs_ic": corr,
        }

    doc = {
        "world": "v2.1-a composite, PERank_DIRECT_V2, FORWARD_RETURN_ADJUSTED_V1, Dev 2021-2023 only",
        "note": "Part-2 supplementary columns + Part-3 hypergeometric test. Diagnostic only.",
        "n_dates": len(dates),
        "negative_dates": neg_dates,
        "panel": panel,
        "part3_tests": tests,
        "max_abs_corr_var_vs_ic": max((abs(t["corr_variable_vs_ic"]) for t in tests.values() if t["corr_variable_vs_ic"] is not None), default=None),
    }
    OUT.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    print("dates:", len(dates), "negatives:", neg_total)
    for v in variables:
        t = tests[v]
        print(f"  {v:20} n={t['n_dates']} meanIC {t['mean_ic_low_half']:+.3f}/{t['mean_ic_high_half']:+.3f} "
              f"pf {t['pos_frac_low']:.2f}/{t['pos_frac_high']:.2f} negHigh={t['neg_dates_in_high_half']}"
              f"(exp {t['neg_dates_expected_by_chance']}) p_ge={t['p_hyper_ge_observed']:.3f} corr={t['corr_variable_vs_ic']:+.3f}")
    print("max |corr(var, IC)| over all ex-ante vars:", doc["max_abs_corr_var_vs_ic"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
