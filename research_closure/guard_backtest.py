"""LIQUIDITY GUARD DESCRIPTIVE BACKTEST (research_closure) — Parts 2,4,5,6,7.

FROZEN definitions: research_closure/LIQUIDITY_GUARD_DEFS_FROZEN.md
(SHA 5a3b454de6fa793fe61fdc9ed595fd7c8b704dcee89106f4e3f1cbe171e43bc4), frozen BEFORE
this run. No threshold search: each guard runs exactly once.

READ-ONLY: certified engine imported UNMODIFIED (rebalance_accounts / price_at /
simulate reused as-is); frozen panel SHA-checked via v3lib.verify_inputs. The L0 runs
are asserted numerically identical to RA.simulate and to the frozen trackA_monthly.csv
BASE rows BEFORE any guarded result is produced. Guards act ONLY on portfolio selection
(same frozen ranking, skip guard-failing names); scores are untouched, so per-date
cross-sectional ICs are mathematically identical to L0 (reported once, not recomputed).

Outputs -> research_closure/: guard_variants.csv, guard_substitutions.csv,
guard_substitution_events.csv, part2_liquidity_evidence.csv, part2_summary.json,
part6_episode_guard.csv, part6_summary.json, part7_era_deltas.csv,
guard_backtest_summary.json
"""
from __future__ import annotations
import json, sys
from bisect import bisect_right
import numpy as np
import pandas as pd

ROOT = r"D:\RFA\Company-Financial"
HERE = ROOT + r"\research_closure"
AUD = ROOT + r"\score_v3_minimal_research"
sys.path.insert(0, AUD)
import v3lib as L  # noqa: E402
import v2lib as V  # noqa: E402

RATE = 0.005                 # BASE cost (frozen trackA convention)
C_TOMAN = 1_000_000_000      # L4 reference portfolio size (frozen: grid midpoint)
PART = 0.05                  # L4 participation cap (frozen: conventional heuristic)

info = L.verify_inputs()
assert info["pit_status"] == "PASS"
panel = pd.read_parquet(L.V2 / "pit_feature_panel.parquet")
dates = sorted(panel["as_of"].unique())
idx = {d: g.index.to_numpy() for d, g in panel.groupby("as_of", sort=True)}
RA, adj, cal, tk = L.load_engine()

FEATS = L.combo_features("B"); W = L.combo_weights("B", "W1")
sp3 = L.score_panel(panel, FEATS, W).rename(columns={"score": "ui_score"})
sp1 = panel[["as_of", "symbol"]].copy()
sp1["ui_score"] = panel["ui_score"].to_numpy()


def exec_of(T):
    i = bisect_right(cal, str(T)[:10])
    return cal[i] if i < len(cal) else None


# ---------------- guard metrics for every panel row (frozen definitions) ----------
print("computing TD60 / TV30 for all panel rows (certified raw-PIT chain) ...")
syms_all = sorted(panel["symbol"].unique())
ref = V.load_reference_data()
md = V.MarketData(ref, symbols=syms_all)
td_arr = np.full(len(panel), np.nan)
tv_arr = np.full(len(panel), np.nan)
tech_cache = {}
p_asof = panel["as_of"].to_numpy()
p_sym = panel["symbol"].to_numpy()
for i in range(len(panel)):
    s = p_sym[i]
    tf = tech_cache.get(s)
    if tf is None:
        if s not in md.data:
            tech_cache[s] = False
            continue
        tf = V.compute_symbol_technicals(md, s)
        tech_cache[s] = tf
    if tf is False:
        continue
    k = md.idx_at(s, str(p_asof[i])[:10])
    if k < 0:
        continue
    td_arr[i] = tf["t_traded_days_ratio_60"].iloc[k]
    tv_arr[i] = tf["t_trade_value_30d"].iloc[k]
ptd = np.full(len(panel), np.nan)
ptv = np.full(len(panel), np.nan)
for d, ii in idx.items():
    ptd[ii] = V.midrank_pct(td_arr[ii], True)
    ptv[ii] = V.midrank_pct(tv_arr[ii], True)
n_nan_td = int(np.isnan(td_arr).sum()); n_nan_tv = int(np.isnan(tv_arr).sum())
print(f"guard metrics done: TD60 missing {n_nan_td}/{len(panel)} rows, "
      f"TV30 missing {n_nan_tv}/{len(panel)} rows")

GMASK = {
    "L1": np.isnan(ptd) | (ptd < 0.10),
    "L2": np.isnan(ptv) | (ptv < 0.10),
    "L3": np.isnan(ptd) | np.isnan(ptv) | ((ptd < 0.15) & (ptv < 0.15)),
}
nan_fail = {"L1": int(np.isnan(ptd).sum()), "L2": int(np.isnan(ptv).sum()),
            "L3": int((np.isnan(ptd) | np.isnan(ptv)).sum())}

# frozen ranking per date per model (identical for L0 and all guards: same scores)
RANKS, ORDERED, POS0 = {}, {}, {}
for MODEL, SP in (("V1", sp1), ("V3", sp3)):
    RANKS[MODEL], ORDERED[MODEL], POS0[MODEL] = {}, {}, {}
    for d in dates:
        g = SP.loc[idx[d]]
        gs = g.sort_values(["ui_score", "symbol"], ascending=[False, True])
        ordered = list(gs["symbol"])
        ORDERED[MODEL][d] = ordered
        RANKS[MODEL][d] = {s: i for i, s in enumerate(ordered)}
        POS0[MODEL][d] = {s: i for i, s in enumerate(ordered)}

# panel row position per (date, symbol) — for looking up guard-metric arrays
PANELPOS = {}
for d, ii in idx.items():
    m = {p_sym[j]: int(j) for j in ii}
    assert len(m) == len(ii), f"duplicate symbol rows at {d}"
    PANELPOS[d] = m


# ---------------- tracker: exact engine replication + guard filter ----------------
def track(sp: pd.DataFrame, gname: str):
    dts = sorted(sp.as_of.unique())
    exs = [exec_of(T) for T in dts]
    cash, shares = 1.0, {}
    recs = []
    for k, T in enumerate(dts):
        E = exs[k]
        g = sp[sp.as_of == T].copy()
        ii = g.index.to_numpy()
        n_elig = len(g); n_sel = max(1, int(np.floor(0.20 * n_elig)))
        cur_vals = {sym: sh * RA.price_at(adj, sym, E) for sym, sh in shares.items()}
        value_pre = cash + sum(cur_vals.values())
        # pass flag is attached to the rows BEFORE sorting so it stays aligned
        if gname == "L0":
            g["_pass"] = True
        elif gname == "L4":
            tvT = tv_arr[ii]
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = (value_pre * C_TOMAN / n_sel) / (tvT / 10.0)
            g["_pass"] = ~(~np.isfinite(tvT) | (ratio > PART))
        else:
            g["_pass"] = ~GMASK[gname][ii]
        gs = g.sort_values(["ui_score", "symbol"], ascending=[False, True])
        passing = gs[gs["_pass"].to_numpy()]
        m = min(n_sel, len(passing))
        sel = passing.iloc[:m]
        pre_w = {s: v / value_pre for s, v in cur_vals.items()} if value_pre > 0 else {}
        pre_cash_w = cash / value_pre if value_pre > 0 else 0.0
        target_each = value_pre / m if m > 0 else 0.0
        target_values, failed = {}, []
        for r in sel.itertuples():
            if (E, r.symbol) in tk:
                target_values[r.symbol] = target_each
            elif r.symbol in cur_vals:
                pass
            else:
                failed.append(r.symbol)
        tradable = {s: (E, s) in tk for s in set(cur_vals) | set(target_values)}
        cash_post, new_pos_vals, cost, buys, sells, buy_scale = RA.rebalance_accounts(
            cash, cur_vals, target_values, tradable, RATE)
        assert cash_post >= -1e-9
        nav_post = cash_post + sum(new_pos_vals.values())
        assert abs(nav_post - (value_pre - cost)) < 1e-6
        shares = {s: v / RA.price_at(adj, s, E) for s, v in new_pos_vals.items()}
        tw = {r.symbol: 1.0 / m for r in sel.itertuples()} if m > 0 else {}
        target_cash_w = sum(1.0 / m for _ in failed) if m > 0 else 0.0
        union = set(tw) | set(pre_w)
        turn = 0.5 * (sum(abs(tw.get(s, 0.0) - pre_w.get(s, 0.0)) for s in union)
                      + abs(target_cash_w - pre_cash_w))
        recs.append({"k": k, "score_date": str(T)[:10], "exec": E, "n_elig": n_elig,
                     "n_sel": n_sel, "n_eff": m, "shortfall": m < n_sel,
                     "selected": set(sel["symbol"]), "failed": set(failed),
                     "weights": ({s: v / nav_post for s, v in new_pos_vals.items()}
                                 if nav_post > 0 else {}),
                     "vals": dict(new_pos_vals), "nav": nav_post, "cash_post": cash_post,
                     "value_pre": value_pre,
                     "cost": cost, "turnover": turn,
                     "holdings": sum(1 for v in new_pos_vals.values() if v > nav_post * 1e-9)})
        cash = cash_post
    return recs


def gross_decomp(recs):
    for k in range(len(recs) - 1):
        E, En = recs[k]["exec"], recs[k + 1]["exec"]
        nav_pre_next = recs[k]["cash_post"]
        tot = 0.0
        for sym, val in recs[k]["vals"].items():
            p1, p2 = RA.price_at(adj, sym, E), RA.price_at(adj, sym, En)
            assert p1 and p2, (sym, E, En)
            r = p2 / p1 - 1.0
            tot += recs[k]["weights"][sym] * r
            nav_pre_next += val * (1 + r)
        gross = nav_pre_next / recs[k]["nav"] - 1.0
        assert abs(gross - tot) < 1e-10, (k, gross, tot)


def local_metrics(recs):
    rets = np.array([recs[k + 1]["nav"] / recs[k]["nav"] - 1 for k in range(len(recs) - 1)])
    entry = recs[0]["nav"]
    path = np.concatenate([[entry], entry * np.cumprod(1 + rets)])
    full = np.concatenate([[1.0], path])
    turn = np.array([r["turnover"] for r in recs])
    return {"n_periods": len(rets), "cumulative_return": float(path[-1] - 1.0),
            "terminal_wealth": float(path[-1]),
            "annualized_return": float(path[-1] ** (12 / len(rets)) - 1),
            "max_drawdown": float((full / np.maximum.accumulate(full) - 1).min()),
            "avg_turnover": float(turn.mean()),
            "total_fees": float(sum(r["cost"] for r in recs))}


def local_yearly(recs):
    out = {}
    for k in range(len(recs) - 1):
        out.setdefault(recs[k]["exec"][:4], []).append(
            recs[k + 1]["nav"] / recs[k]["nav"] - 1)
    return {y: float(np.prod(1 + np.array(v))) - 1 for y, v in sorted(out.items())}


def dd_points(recs):
    """path index: 0 = 1.0, i >= 1 <-> recs[i-1] (engine metrics wealth convention)."""
    rets = np.array([recs[k + 1]["nav"] / recs[k]["nav"] - 1 for k in range(len(recs) - 1)])
    entry = recs[0]["nav"]
    path = np.concatenate([[1.0, entry], entry * np.cumprod(1 + rets)])
    peak = np.maximum.accumulate(path)
    dd = path / peak - 1.0
    t = int(np.argmin(dd))
    p = int(np.where(path[:t + 1] == peak[t])[0][-1])
    rec = next((j for j in range(t, len(path)) if path[j] >= peak[t] - 1e-15), None)
    return path, dd, p, t, rec, float(dd[t])


# ---------------- run all variants; L0 verification gates first -------------------
csv_m = pd.read_csv(AUD + r"\trackA_monthly.csv")
csv1 = csv_m[(csv_m.model == "V1") & (csv_m.cost == "BASE")].sort_values("score_date").reset_index(drop=True)
csv3 = csv_m[(csv_m.model == "B-W1") & (csv_m.cost == "BASE")].sort_values("score_date").reset_index(drop=True)
bench = csv1["bench_return"].to_numpy(float)[:62]
assert list(csv1["score_date"]) == list(csv3["score_date"])
assert np.allclose(np.nan_to_num(csv1["bench_return"].to_numpy(float)[:62]),
                   np.nan_to_num(csv3["bench_return"].to_numpy(float)[:62]), atol=1e-12)
ta = json.load(open(AUD + r"\trackA_results.json"))

RECS = {}   # (model, guard) -> recs
for MODEL, SP in (("V1", sp1), ("V3", sp3)):
    rec_key = "V1" if MODEL == "V1" else "B-W1"
    rec0 = track(SP, "L0")
    eng, _, _ = RA.simulate(SP, adj, cal, tk, 0.20, RATE)
    assert max(abs(a["nav"] - b["value_post_trade"]) for a, b in zip(rec0, eng)) < 1e-9, MODEL
    net = np.array([rec0[k + 1]["nav"] / rec0[k]["nav"] - 1 for k in range(62)])
    csvX = csv1 if MODEL == "V1" else csv3
    assert np.allclose(net, csvX["monthly_return"].to_numpy(float)[:62], atol=1e-10,
                       equal_nan=True), MODEL
    lm = local_metrics(rec0)
    fr = ta["records"][rec_key]
    for a, b in (("annualized_return", "cagr_base"), ("max_drawdown", "mdd_base"),
                 ("avg_turnover", "turnover_base")):
        assert abs(lm[a] - fr[b]) < 1e-9, (MODEL, a, lm[a], fr[b])
    fy = local_yearly(rec0)
    for y, v in ta["portfolio"][rec_key]["BASE"]["yearly"].items():
        assert abs(fy[y] - v) < 1e-9, (MODEL, y, fy[y], v)
    gross_decomp(rec0)
    print(f"VERIFIED L0 {MODEL}: NAV==engine, monthly==frozen CSV, "
          f"cagr/mdd/turnover/yearly == frozen records; gross identity OK")
    RECS[(MODEL, "L0")] = rec0
    for gname in ("L1", "L2", "L3", "L4"):
        rc = track(SP, gname)
        gross_decomp(rc)   # frozen verification gate: identity on every run
        RECS[(MODEL, gname)] = rc

# ---------------- summarize variants + substitution bookkeeping -------------------
def window_stats(recs, lo, hi, excl_init_turnover=False):
    rows = [k for k in range(len(recs) - 1) if lo <= int(recs[k]["exec"][:4]) <= hi]
    rets = np.array([recs[k + 1]["nav"] / recs[k]["nav"] - 1 for k in rows])
    w = np.cumprod(1 + rets)
    tos = [recs[k]["turnover"] for k in rows if not (excl_init_turnover and k == 0)]
    return {"cum": float(np.prod(1 + rets) - 1),
            "mdd": float((w / np.maximum.accumulate(w) - 1).min()),
            "avg_turnover": float(np.mean(tos)) if tos else None, "n_rows": len(rows)}


RESULTS = {}
ALL_SUBS = []
for MODEL in ("V1", "V3"):
    recs0 = RECS[(MODEL, "L0")]
    for gname in ("L0", "L1", "L2", "L3", "L4"):
        recs = RECS[(MODEL, gname)]
        lm = local_metrics(recs); fy = local_yearly(recs)
        net = np.array([recs[k + 1]["nav"] / recs[k]["nav"] - 1 for k in range(62)])
        row = {"model": MODEL, "guard": gname,
               "cagr": lm["annualized_return"], "cum_full": lm["cumulative_return"],
               "mdd": lm["max_drawdown"], "avg_turnover": lm["avg_turnover"],
               "total_fees": lm["total_fees"],
               "bench_cum_full": float(np.prod(1 + bench) - 1),
               "excess_cum_full": float(np.prod(1 + net) / np.prod(1 + bench) - 1)}
        for tag, lo, hi, exl in (("w2122", 2021, 2022, True), ("w2326", 2023, 2026, False)):
            ws = window_stats(recs, lo, hi, exl)
            rws = [k for k in range(62) if lo <= int(recs[k]["exec"][:4]) <= hi]
            row[f"{tag}_cum"] = ws["cum"]; row[f"{tag}_mdd"] = ws["mdd"]
            row[f"{tag}_turnover"] = ws["avg_turnover"]
            row[f"{tag}_bench_cum"] = float(np.prod(1 + bench[rws]) - 1)
            row[f"{tag}_excess_cum"] = (1 + ws["cum"]) / (1 + row[f"{tag}_bench_cum"]) - 1
        for y in ("2021", "2022", "2023", "2024", "2025", "2026"):
            row[f"year_{y}"] = fy.get(y)
        n_subs = n_slots = shortfalls = 0
        events = []
        if gname != "L0":
            for k in range(len(recs)):
                T = recs[k]["score_date"]
                s0, s1 = recs0[k]["selected"], recs[k]["selected"]
                n_slots += len(s0)
                excl, repl = s0 - s1, s1 - s0
                n_subs += len(excl)
                if recs[k]["shortfall"]:
                    shortfalls += 1
                pos0 = POS0[MODEL][T]
                excl_s = sorted(excl, key=lambda s: pos0[s])
                repl_s = sorted(repl, key=lambda s: pos0[s])
                n_before = len(events)
                for a, b in zip(excl_s, repl_s):
                    ia, ib = PANELPOS[T][a], PANELPOS[T][b]
                    d_tv = (float(tv_arr[ib] - tv_arr[ia])
                            if np.isfinite(tv_arr[ib]) and np.isfinite(tv_arr[ia]) else None)
                    events.append({"model": MODEL, "guard": gname, "score_date": T,
                                   "excluded": a, "replacement": b,
                                   "rank_excluded": ia, "rank_replacement": ib,
                                   "d_pct_tv30_pp": float((ptv[ib] - ptv[ia]) * 100),
                                   "d_pct_td60_pp": float((ptd[ib] - ptd[ia]) * 100),
                                   "d_tv30_rial": d_tv})
                ALL_SUBS.extend(events[n_before:])
            row.update({"n_substitutions": n_subs,
                        "avg_subs_per_rebalance": n_subs / len(recs),
                        "retention_pct": 100.0 * (1 - n_subs / n_slots),
                        "n_shortfall_rebalances": shortfalls})
            ev = pd.DataFrame(events)
            if len(ev):
                row["median_d_pct_tv30_pp"] = float(ev["d_pct_tv30_pp"].median())
                row["median_d_pct_td60_pp"] = float(ev["d_pct_td60_pp"].median())
                row["median_d_tv30_rial"] = float(ev["d_tv30_rial"].median())
            else:
                row["median_d_pct_tv30_pp"] = row["median_d_pct_td60_pp"] = None
                row["median_d_tv30_rial"] = None
        else:
            row.update({"n_substitutions": 0, "avg_subs_per_rebalance": 0.0,
                        "retention_pct": 100.0, "n_shortfall_rebalances": 0,
                        "median_d_pct_tv30_pp": None, "median_d_pct_td60_pp": None,
                        "median_d_tv30_rial": None})
        RESULTS[(MODEL, gname)] = row
        print(f"{MODEL} {gname}: cagr={row['cagr']:.4f} mdd={row['mdd']:.4f} "
              f"to={row['avg_turnover']:.4f} 2122={row['w2122_cum']:+.4f} "
              f"2326={row['w2326_cum']:+.4f} subs={row['n_substitutions']} "
              f"ret={row['retention_pct']:.1f}%")

vdf = pd.DataFrame([RESULTS[k] for k in sorted(RESULTS)])
vdf.to_csv(HERE + r"\guard_variants.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(ALL_SUBS).to_csv(HERE + r"\guard_substitution_events.csv", index=False,
                              encoding="utf-8-sig")
sub_rows = []
for (MODEL, gname), recs in RECS.items():
    if gname == "L0":
        continue
    recs0 = RECS[(MODEL, "L0")]
    for k in range(len(recs)):
        s0, s1 = recs0[k]["selected"], recs[k]["selected"]
        if s0 - s1 or s1 - s0:
            sub_rows.append({"model": MODEL, "guard": gname,
                             "score_date": recs[k]["score_date"],
                             "excluded": "|".join(sorted(s0 - s1)),
                             "replacements": "|".join(sorted(s1 - s0))})
pd.DataFrame(sub_rows).to_csv(HERE + r"\guard_substitutions.csv", index=False,
                              encoding="utf-8-sig")

# ---------------- PART 2 evidence: selected-name liquidity profiles ---------------
recs3L0 = RECS[("V3", "L0")]
_, _, p3, t3, recp, mdd3 = dd_points(recs3L0)
dd_rows = list(range(p3 - 1, t3 - 1))
ep_dates = {recs3L0[j]["score_date"] for j in dd_rows}
p2_rows = []
for MODEL in ("V1", "V3"):
    recs0 = RECS[(MODEL, "L0")]
    for k in range(len(recs0)):
        T = recs0[k]["score_date"]
        ii = idx[T]
        sel = recs0[k]["selected"]
        if not sel:
            continue
        sel_i = np.array([j for j in ii if p_sym[j] in sel])
        n_sel = recs0[k]["n_sel"]
        cap_ratio = (C_TOMAN / n_sel) / (tv_arr[sel_i] / 10.0)
        p2_rows.append({
            "model": MODEL, "score_date": T,
            "median_pct_tv30": float(np.nanmedian(ptv[sel_i])),
            "median_pct_td60": float(np.nanmedian(ptd[sel_i])),
            "share_bottom10pct_tv30": float(np.nanmean(ptv[sel_i] < 0.10)),
            "share_bottom10pct_td60": float(np.nanmean(ptd[sel_i] < 0.10)),
            "median_tv30_rial": float(np.nanmedian(tv_arr[sel_i])),
            "median_td60": float(np.nanmedian(td_arr[sel_i])),
            "median_zero_trade_days_60": float(np.nanmedian(60 * (1 - td_arr[sel_i]))),
            "median_capacity_ratio_1B": float(np.nanmedian(cap_ratio)),
            "universe_median_tv30_rial": float(np.nanmedian(tv_arr[ii])),
            "universe_p10_tv30_rial": float(np.nanpercentile(tv_arr[ii], 10)),
            "universe_p10_td60": float(np.nanpercentile(td_arr[ii], 10)),
            "n_sel": n_sel})
p2 = pd.DataFrame(p2_rows)
p2["window"] = np.where(p2["score_date"].isin(ep_dates), "episode_2122",
                        np.where(p2["score_date"] < "2023-01-01", "2021-22_other", "2023-26"))
p2.to_csv(HERE + r"\part2_liquidity_evidence.csv", index=False, encoding="utf-8-sig")
p2s = {}
for MODEL in ("V1", "V3"):
    for wnd, g in p2[p2.model == MODEL].groupby("window"):
        p2s[f"{MODEL}|{wnd}"] = {
            c: float(g[c].mean()) for c in
            ("median_pct_tv30", "median_pct_td60", "share_bottom10pct_tv30",
             "share_bottom10pct_td60", "median_tv30_rial", "median_td60",
             "median_zero_trade_days_60", "median_capacity_ratio_1B")}
json.dump(p2s, open(HERE + r"\part2_summary.json", "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)

# ---------------- PART 6: episode contributors x guards ---------------------------
ep_contrib = pd.read_csv(AUD + r"\audit\partE_security_contributions.csv").head(20)
base2122 = RESULTS[("V3", "L0")]["w2122_cum"]
p6_rows, repl_sets = [], {}
for gname in ("L1", "L2", "L3", "L4"):
    recs = RECS[("V3", gname)]
    sel_by_date = {recs[k]["score_date"]: recs[k]["selected"] for k in dd_rows}
    g2122 = RESULTS[("V3", gname)]["w2122_cum"]
    for _, r in ep_contrib.iterrows():
        s = r["symbol"]
        sel_dates = [recs3L0[j]["score_date"] for j in dd_rows if s in recs3L0[j]["selected"]]
        kept = sum(1 for T in sel_dates if s in sel_by_date[T])
        removed = len(sel_dates) - kept
        verdict = ("REMOVED" if sel_dates and removed == len(sel_dates)
                   else "RETAINED" if removed == 0 else "PARTIAL")
        p6_rows.append({"guard": gname, "symbol": s,
                        "contribution_to_v3_drawdown": r["contribution_to_v3_drawdown"],
                        "l0_selected_dates_in_episode": len(sel_dates),
                        "kept_by_guard": kept, "removed_by_guard": removed,
                        "verdict": verdict})
    l0_union = set().union(*[recs3L0[j]["selected"] for j in dd_rows])
    g_union = set().union(*sel_by_date.values())
    repl_sets[gname] = sorted(g_union - l0_union)
    p6_rows.append({"guard": gname, "symbol": "___V3_2122_cum_guarded___",
                    "contribution_to_v3_drawdown": None,
                    "l0_selected_dates_in_episode": None, "kept_by_guard": None,
                    "removed_by_guard": None,
                    "verdict": (f"guarded 2122 cum {g2122:+.4f} vs L0 {base2122:+.4f}; "
                                f"delta {g2122 - base2122:+.4f}; replacements: "
                                f"{'|'.join(repl_sets[gname]) or 'none'}")})
pd.DataFrame(p6_rows).to_csv(HERE + r"\part6_episode_guard.csv", index=False,
                             encoding="utf-8-sig")
json.dump({"episode_score_dates": sorted(ep_dates),
           "v3_l0_2122_cum": base2122,
           "v1_l0_2122_cum": RESULTS[("V1", "L0")]["w2122_cum"],
           "replacements_by_guard": repl_sets},
          open(HERE + r"\part6_summary.json", "w", encoding="utf-8"), indent=1,
          ensure_ascii=False, default=str)

# ---------------- PART 7 era-preservation deltas vs unguarded ---------------------
p7 = []
for MODEL in ("V1", "V3"):
    base = RESULTS[(MODEL, "L0")]
    for gname in ("L1", "L2", "L3", "L4"):
        r = RESULTS[(MODEL, gname)]
        p7.append({"model": MODEL, "guard": gname,
                   "d2122_cum_pp": 100 * (r["w2122_cum"] - base["w2122_cum"]),
                   "d2326_cum_pp": 100 * (r["w2326_cum"] - base["w2326_cum"]),
                   "d2326_mdd_pp": 100 * (r["w2326_mdd"] - base["w2326_mdd"]),
                   "d_turnover_pp": 100 * (r["avg_turnover"] - base["avg_turnover"]),
                   "d_cagr_pp": 100 * (r["cagr"] - base["cagr"]),
                   "d_mdd_pp": 100 * (r["mdd"] - base["mdd"]),
                   "d_fees": r["total_fees"] - base["total_fees"]})
pd.DataFrame(p7).to_csv(HERE + r"\part7_era_deltas.csv", index=False, encoding="utf-8-sig")

# ------------- DIAGNOSTIC: composition of guard-failing names in top40 -------------
# (why are per-date substitution counts equal across models while name sets differ?)
diag_dates = []
agg = {"v1_fail_events": 0, "v3_fail_events": 0, "td60_of_fails": [], "tv30_of_fails": [],
       "own_rank_of_fails": [], "other_rank_of_fails": [], "both_models_fail_events": 0}
for k in range(63):
    T = recs3L0[k]["score_date"]
    S1 = RECS[("V1", "L0")][k]["selected"]
    S3 = RECS[("V3", "L0")][k]["selected"]
    ii = idx[T]
    F1 = {p_sym[j] for j in ii if GMASK["L1"][j]}
    F3 = {p_sym[j] for j in ii if GMASK["L3"][j]}
    f1, f3 = S1 & F1, S3 & F1
    entry = {"date": T, "top40_overlap": len(S1 & S3),
             "v1_fail_in_top40": sorted(f1), "v3_fail_in_top40": sorted(f3),
             "count_equal": len(f1) == len(f3)}
    prof = {}
    for s in sorted(f1 | f3):
        j = PANELPOS[T][s]
        prof[s] = {"td60": float(td_arr[j]),
                   "tv30_rial": float(tv_arr[j]) if np.isfinite(tv_arr[j]) else None,
                   "rank_v1": RANKS["V1"][T].get(s), "rank_v3": RANKS["V3"][T].get(s),
                   "in_top40_v1": s in S1, "in_top40_v3": s in S3}
    entry["failing_name_profiles"] = prof
    diag_dates.append(entry)
    for tag, own, other in (("v1", "V1", "V3"), ("v3", "V3", "V1")):
        fs = f1 if tag == "v1" else f3
        for s in fs:
            agg[f"{tag}_fail_events"] += 1
            j = PANELPOS[T][s]
            agg["td60_of_fails"].append(float(td_arr[j]))
            if np.isfinite(tv_arr[j]):
                agg["tv30_of_fails"].append(float(tv_arr[j]))
            agg["own_rank_of_fails"].append(RANKS[own][T][s])
            agg["other_rank_of_fails"].append(RANKS[other][T].get(s))
            if s in f1 and s in f3:
                agg["both_models_fail_events"] += 1
diag_sum = {
    "n_dates_L1_count_equal": sum(1 for e in diag_dates if e["count_equal"]),
    "n_dates": len(diag_dates),
    "mean_top40_overlap_V1_V3": float(np.mean([e["top40_overlap"] for e in diag_dates])),
    "v1_fail_events_L1": agg["v1_fail_events"], "v3_fail_events_L1": agg["v3_fail_events"],
    "fail_events_in_both_models_same_date": agg["both_models_fail_events"],
    "median_td60_of_failing_selected": float(np.nanmedian(agg["td60_of_fails"])),
    "frac_failing_selected_td60_nan": float(np.mean([np.isnan(t) for t in agg["td60_of_fails"]])),
    "frac_failing_selected_td60_below_1": float(np.nanmean([t < 1.0 for t in agg["td60_of_fails"]])),
    "median_tv30_rial_of_failing_selected": float(np.median(agg["tv30_of_fails"])) if agg["tv30_of_fails"] else None,
    "median_rank_in_own_model": float(np.median(agg["own_rank_of_fails"])),
    "median_rank_in_other_model": float(np.median([r for r in agg["other_rank_of_fails"] if r is not None])),
    "frac_fails_also_in_other_top40": float(np.mean([r is not None and r < 40 for r in agg["other_rank_of_fails"]])),
}
# cross-assert: tracker substitutions == independent fail-set intersection (L1)
assert agg["v1_fail_events"] == RESULTS[("V1", "L1")]["n_substitutions"], (
    agg["v1_fail_events"], RESULTS[("V1", "L1")]["n_substitutions"])
assert agg["v3_fail_events"] == RESULTS[("V3", "L1")]["n_substitutions"], (
    agg["v3_fail_events"], RESULTS[("V3", "L1")]["n_substitutions"])
# cross-assert (L4): independent recomputation from the recorded guarded value_pre path
for MODEL in ("V1", "V3"):
    recs4, recs0 = RECS[(MODEL, "L4")], RECS[(MODEL, "L0")]
    tot = 0
    for k in range(len(recs4)):
        T = recs4[k]["score_date"]
        ii = idx[T]
        tvT = tv_arr[ii]
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = (recs4[k]["value_pre"] * C_TOMAN / recs4[k]["n_sel"]) / (tvT / 10.0)
        F4 = {p_sym[j] for j, jj in zip(ii, range(len(ii)))
              if (~np.isfinite(tvT[jj])) | (ratio[jj] > PART)}
        tot += len(recs0[k]["selected"] & F4)
    assert tot == RESULTS[(MODEL, "L4")]["n_substitutions"], (MODEL, tot)
print("\nDIAGNOSTIC guard-fail composition:", json.dumps(diag_sum, indent=1))

json.dump({"variants": {f"{m}|{g}": RESULTS[(m, g)] for m in ("V1", "V3")
                        for g in ("L0", "L1", "L2", "L3", "L4")},
           "part7_deltas": p7, "nan_guard_fails": nan_fail,
           "panel_rows_missing_td60": n_nan_td, "panel_rows_missing_tv30": n_nan_tv,
           "episode_dd_rows": [recs3L0[j]["score_date"] for j in dd_rows],
           "v3_l0_mdd": mdd3, "diagnostic_summary": diag_sum,
           "diagnostic_per_date_L1L3": diag_dates},
          open(HERE + r"\guard_backtest_summary.json", "w", encoding="utf-8"),
          indent=1, ensure_ascii=False, default=str)
print("\nALL GUARD RUNS DONE -> research_closure/ outputs written")
