"""RESEARCH PROGRAM DECISION — Development-only diagnostic panel + regime test.

Answers ONE question: is there genuinely new, ex-ante-observable, Development-supported
evidence for a NEW model family, or should the research program stop?

Uses ONLY Development 2021-2023 and information available BEFORE each return outcome:
  ex-ante state variables (computed at the signal-date close from cached raw pClosing,
  PERank_DIRECT_V2 availability/PE, and market.corporate_actions trailing events):
    breadth          = fraction of universe with positive trailing-21d return
    mkt_ret21_med    = median trailing-21d return (reversal state)
    xsec_disp21      = cross-sectional std of trailing-21d returns (dispersion)
    vol_level        = cross-sectional median of trailing-21d daily-return std
    neg_pe_frac      = fraction of scored rows with PE <= 0 (negative earnings)
    pe_disp          = std of log(PE) among valid (0,60] PEs
    recent_capital   = fraction of scored symbols with a capital event ex-date in the
                       trailing 63 days
Outcome-side panel columns (composite IC, factor ICs, ret_21 dispersion, turnover) are
DESCRIPTIVE ONLY and never used to define states.

REGIME_MECHANISM_EVIDENCE rubric (stated BEFORE computing):
  concentration c = share of the 10 negative composite dates falling in the HIGH half of
  an ex-ante variable (expected 0.5 under no association); gap = pos-frac(low) - pos-frac(high).
  STRONG   : c >= 0.8 and gap >= 0.30 for BOTH vol_level and xsec_disp21
  MODERATE : c >= 0.7 and gap >= 0.20 for at least one of them, sign-consistent in the family
  WEAK     : c >= 0.6 for some variable, or mixed/inconsistent signs
  NONE     : otherwise
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import gzip
import json
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
OUT = HERE / "output" / "research_decision_panel.json"


def main() -> int:
    rows = M.load_signals(ADJUSTED)
    dmap, smap = direct_ranks(), symbol_map()
    rows_direct, _, _ = rows_with_direct(rows, dmap, smap)
    dev = M.period_rows(rows_direct, "development")
    w6 = {f: 1/6 for f in V.ROBUST}
    scorer = robust_score(w6)

    cs = {}
    for r in dev:
        s = scorer(r)
        if s is not None:
            cs.setdefault(r["signal_date"], []).append(r)
    dates = sorted(cs)

    # ---------- outcome-side panel ----------
    panel = {}
    prev_top = set()
    for d in dates:
        rs = cs[d]
        ic = ic_of([(scorer(r), r["ret_21"]) for r in rs if r["ret_21"] is not None])
        rets = [r["ret_21"] for r in rs if r["ret_21"] is not None]
        fac_ic = {f: ic_of([(r["ranks"].get(f), r["ret_21"]) for r in rs
                            if r["avail"].get(f) and r["ranks"].get(f) is not None and r["ret_21"] is not None])
                  for f in V.ROBUST}
        top = {r["company_id"] for r in rs if r["ret_21"] is not None}
        top = set(sorted(top)[:0])  # placeholder no-op to keep structure clear
        elig = sorted([r for r in rs if r["ret_21"] is not None], key=lambda r: -scorer(r))
        top = {r["company_id"] for r in elig[:20]}
        turn = (1.0 - len(top & prev_top) / len(top | prev_top)) if prev_top else None
        prev_top = top
        panel[d] = {"ic21": ic, "fac_ic": fac_ic, "n": len(rs),
                    "ret21_std": float(np.std(rets, ddof=1)) if len(rets) > 1 else None,
                    "ret21_med": float(np.median(rets)) if rets else None,
                    "perank_avail": float(np.mean([bool(r["avail"].get("PERank")) for r in rs])),
                    "turnover": turn}

    # ---------- ex-ante state variables from raw caches ----------
    syms = [s for s in (Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output") /
                        "research_symbols_238.txt").read_text(encoding="utf-8").split("\n") if s.strip()]
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
        ds, ps = [], []
        for r in recs:
            s = str(r["dEven"])
            ds.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
            ps.append(float(r["pClosing"]))
        series[sym] = (ds, ps)

    # PERank-side ex-ante from the v2 jsonl
    pe = {}
    for line in PE2.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        pe.setdefault(r["signal_date"], []).append(r.get("PE_DIRECT"))

    # recent capital events (trailing 63d) from corporate_actions
    sys.path.insert(0, r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\analytics_canonical_v1")
    import os
    os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
    import psycopg
    DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT s.codal_symbol, ca.action_date FROM market.corporate_actions ca
                       JOIN core.securities s ON s.id=ca.security_id
                       WHERE ca.source='tsetmc_gap_rule_v1' AND ca.action_type IN
                       ('capital_increase','rights_issue','reverse_split','stock_dividend')""")
        ev = {}
        for sym, d in cur.fetchall():
            ev.setdefault(sym, set()).add(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)))

    state = {}
    for d in dates:
        dd = dt.date.fromisoformat(d)
        r21s, vols = [], []
        for sym, (ds, ps) in series.items():
            i = bisect.bisect_right(ds, d) - 1
            if i < 21:
                continue
            r21 = ps[i] / ps[i - 21] - 1.0
            rets = [ps[j] / ps[j - 1] - 1.0 for j in range(i - 20, i + 1)]
            if ps[i] > 0 and ps[i - 21] > 0:
                r21s.append(r21)
                vols.append(float(np.std(rets, ddof=1)))
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

    # ---------- assemble panel + Part 3 test ----------
    ics = [panel[d]["ic21"] for d in dates]
    neg_dates = [d for d in dates if panel[d]["ic21"] is not None and panel[d]["ic21"] < 0]
    variables = ["breadth", "mkt_ret21_med", "xsec_disp21", "vol_level",
                 "neg_pe_frac", "pe_disp", "recent_capital_frac"]
    split_test = {}
    for v in variables:
        xs = [(d, state[d][v]) for d in dates if state[d][v] is not None and panel[d]["ic21"] is not None]
        xs.sort(key=lambda x: x[1])
        half = len(xs) // 2
        low = [d for d, _ in xs[:half]]
        high = [d for d, _ in xs[half:]]
        ic_low = [panel[d]["ic21"] for d in low]
        ic_high = [panel[d]["ic21"] for d in high]
        corr = np.corrcoef([state[d][v] for d, _ in xs], [panel[d]["ic21"] for d, _ in xs])[0, 1] if len(xs) > 2 else None
        split_test[v] = {
            "n_dates": len(xs),
            "mean_ic_low_half": float(np.mean(ic_low)), "mean_ic_high_half": float(np.mean(ic_high)),
            "pos_frac_low": float(np.mean([x > 0 for x in ic_low])),
            "pos_frac_high": float(np.mean([x > 0 for x in ic_high])),
            "neg_dates_in_high_half": sum(1 for d in high if d in neg_dates),
            "neg_dates_total": len(neg_dates),
            "corr_variable_vs_ic": float(corr) if corr is not None else None,
        }

    def grade(v):
        t = split_test[v]
        c = t["neg_dates_in_high_half"] / t["neg_dates_total"]
        gap = t["pos_frac_low"] - t["pos_frac_high"]
        return c, gap
    c_vol, g_vol = grade("vol_level")
    c_disp, g_disp = grade("xsec_disp21")
    if c_vol >= 0.8 and g_vol >= 0.30 and c_disp >= 0.8 and g_disp >= 0.30:
        evidence = "STRONG"
    elif (c_vol >= 0.7 and g_vol >= 0.20) or (c_disp >= 0.7 and g_disp >= 0.20):
        consistent = (c_vol - 0.5) * (c_disp - 0.5) > 0
        evidence = "MODERATE" if consistent else "WEAK"
    elif max(c_vol, c_disp, grade("breadth")[0], grade("mkt_ret21_med")[0]) >= 0.6:
        evidence = "WEAK"
    else:
        evidence = "NONE"

    # ---------- Part 4: LowVolatilityRank ----------
    lv = {d: panel[d]["fac_ic"]["LowVolatilityRank"] for d in dates}
    lv_vals = [v for v in lv.values() if v is not None]
    pos_d = [d for d in dates if panel[d]["ic21"] is not None and panel[d]["ic21"] > 0]
    neg_d = [d for d in dates if panel[d]["ic21"] is not None and panel[d]["ic21"] < 0]
    lv_on_pos = [lv[d] for d in pos_d if lv[d] is not None]
    lv_on_neg = [lv[d] for d in neg_d if lv[d] is not None]
    turnover_by_date = {d: panel[d]["turnover"] for d in dates}
    lv_turn = corr_pair([lv[d] for d in dates if lv[d] is not None and turnover_by_date[d] is not None],
                        [turnover_by_date[d] for d in dates if lv[d] is not None and turnover_by_date[d] is not None])
    lv_cov = corr_pair([lv[d] for d in dates if lv[d] is not None], [panel[d]["perank_avail"] for d in dates if lv[d] is not None])
    pair = mean_pairwise_corr(cs, "LowVolatilityRank", "PERank")
    pair_g = mean_pairwise_corr(cs, "LowVolatilityRank", "NetProfitGrowthRank")
    lv_vol_state = corr_pair([lv[d] for d in dates if lv[d] is not None and state[d]["vol_level"] is not None],
                             [state[d]["vol_level"] for d in dates if lv[d] is not None and state[d]["vol_level"] is not None])
    lv_year = {}
    for y in (2021, 2022, 2023):
        vals = [lv[d] for d in dates if lv[d] is not None and d[:4] == str(y)]
        lv_year[y] = {"n": len(vals), "mean": float(np.mean(vals)), "positive": sum(1 for v in vals if v > 0)}
    lowvol = {"ic_by_year": lv_year, "positive_fraction": float(np.mean([v > 0 for v in lv_vals])),
              "mean_ic_on_positive_composite_dates": float(np.mean(lv_on_pos)),
              "mean_ic_on_negative_composite_dates": float(np.mean(lv_on_neg)),
              "corr_lowvol_ic_vs_turnover": lv_turn, "corr_lowvol_ic_vs_perank_coverage": lv_cov,
              "mean_rank_corr_with_PERank": pair, "mean_rank_corr_with_NPGX": pair_g,
              "corr_lowvol_ic_vs_exante_vol_level": lv_vol_state}

    # ---------- Part 5: PERank ----------
    pr = {d: panel[d]["fac_ic"]["PERank"] for d in dates}
    pr_neg = [d for d in dates if pr[d] is not None and pr[d] < 0]
    pr_vol = corr_pair([pr[d] for d in dates if pr[d] is not None and state[d]["vol_level"] is not None],
                       [state[d]["vol_level"] for d in dates if pr[d] is not None and state[d]["vol_level"] is not None])
    pr_rev = corr_pair([pr[d] for d in dates if pr[d] is not None and state[d]["mkt_ret21_med"] is not None],
                       [state[d]["mkt_ret21_med"] for d in dates if pr[d] is not None and state[d]["mkt_ret21_med"] is not None])
    pr_negpe = corr_pair([pr[d] for d in dates if pr[d] is not None and state[d]["neg_pe_frac"] is not None],
                         [state[d]["neg_pe_frac"] for d in dates if pr[d] is not None and state[d]["neg_pe_frac"] is not None])
    pr_cap = corr_pair([pr[d] for d in dates if pr[d] is not None and state[d]["recent_capital_frac"] is not None],
                       [state[d]["recent_capital_frac"] for d in dates if pr[d] is not None and state[d]["recent_capital_frac"] is not None])
    pr_n = corr_pair([pr[d] for d in dates if pr[d] is not None], [panel[d]["n"] for d in dates if pr[d] is not None])
    mean_state_neg = {v: float(np.mean([state[d][v] for d in pr_neg if state[d][v] is not None]))
                      for v in ("neg_pe_frac", "pe_disp", "recent_capital_frac", "mkt_ret21_med")}
    mean_state_all = {v: float(np.mean([state[d][v] for d in dates if state[d][v] is not None]))
                      for v in ("neg_pe_frac", "pe_disp", "recent_capital_frac", "mkt_ret21_med")}
    perank_diag = {"negative_dates": pr_neg,
                   "corr_perank_ic_vs_vol_level": pr_vol, "corr_perank_ic_vs_mkt_reversal": pr_rev,
                   "corr_perank_ic_vs_neg_pe_frac": pr_negpe,
                   "corr_perank_ic_vs_recent_capital_frac": pr_cap,
                   "corr_perank_ic_vs_cross_section_size": pr_n,
                   "mean_state_on_perank_negative_dates": mean_state_neg,
                   "mean_state_all_dev_dates": mean_state_all,
                   "industry_domination": "NOT DERIVABLE — no industry/sector columns exist in core.securities"}

    doc = {"world": "v2.1-a composite, PERank_DIRECT_V2, FORWARD_RETURN_ADJUSTED_V1, Dev only",
           "rubric": __doc__.split("REGIME_MECHANISM_EVIDENCE rubric")[1].split('"""')[0],
           "panel": {d: {**panel[d], **state[d]} for d in dates},
           "negative_dates": neg_dates,
           "split_tests": split_test,
           "REGIME_MECHANISM_EVIDENCE": evidence,
           "lowvol_diagnosis": lowvol,
           "perank_diagnosis": perank_diag}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("REGIME_MECHANISM_EVIDENCE =", evidence)
    for v in variables:
        t = split_test[v]
        print(f"  {v:20} meanIC low/high={t['mean_ic_low_half']:+.3f}/{t['mean_ic_high_half']:+.3f} "
              f"pf low/high={t['pos_frac_low']:.2f}/{t['pos_frac_high']:.2f} "
              f"negInHigh={t['neg_dates_in_high_half']}/{t['neg_dates_total']} corr={t['corr_variable_vs_ic']:+.3f}")
    print("LowVol:", json.dumps(lowvol, ensure_ascii=False, default=str))
    print("PERank:", json.dumps(perank_diag, ensure_ascii=False, default=str))
    return 0


def robust_score(weights):
    def fn(r):
        num = den = 0.0
        for code, w in weights.items():
            if r["avail"].get(code) and r["ranks"].get(code) is not None:
                num += w * float(r["ranks"][code])
                den += w
        return num / den if den > 0 else None
    return fn


def ic_of(pairs):
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    return M.spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 5 else None


def corr_pair(xs, ys):
    if len(xs) > 2 and np.std(xs) > 0 and np.std(ys) > 0:
        return float(np.corrcoef(xs, ys)[0, 1])
    return None


def mean_pairwise_corr(cs, f, g):
    per = []
    for d, rs in cs.items():
        pairs = [(r["ranks"].get(f), r["ranks"].get(g)) for r in rs
                 if r["avail"].get(f) and r["avail"].get(g)
                 and r["ranks"].get(f) is not None and r["ranks"].get(g) is not None]
        if len(pairs) >= 5:
            per.append(M.spearman([p[0] for p in pairs], [p[1] for p in pairs]))
    return round(float(np.mean(per)), 4) if per else None


if __name__ == "__main__":
    raise SystemExit(main())
