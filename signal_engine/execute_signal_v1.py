"""SIGNAL V1 — EXECUTION (exactly once) of preregistration hash
149ba4afd112f63443316a986ac793af60a60f572e13cf446850a6dcea3859ae.

Implements EXACTLY signal-v1-A, signal-v1-A-momentum, signal-v1-B per the frozen Exact
Experiment Specification (E1-E13). Phases: leakage tests L1-L7 BEFORE performance; signal
snapshot frozen+hashed BEFORE outcomes; then outcomes, metrics, gates. No other candidate,
no tuning, no rescue.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import gzip
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\RFA\Company-Financial\model_v2_validation")
import model_v2 as M  # noqa: E402  frozen spearman

HERE = Path(r"D:\RFA\Company-Financial\signal_engine")
PREREG = HERE / "SIGNAL_ENGINE_PREREGISTRATION_V1.md"
UI = HERE / "ui_score_historical_v1.jsonl"
RAW = Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output\raw_closing_universe")
IDX = Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output\tsetmc_share\index.json")
SNAP = HERE / "output" / "signal_v1_snapshot.jsonl"
RESULTS = HERE / "output" / "signal_v1_results.json"
PREREG_SHA256 = "149ba4afd112f63443316a986ac793af60a60f572e13cf446850a6dcea3859ae"
HORIZONS = (21, 63, 126)
SEED, B = 20261002, 2000


def midrank(values: dict, higher_is_better=True, neutral=0.3, invalid_zero=None):
    from bisect import bisect_left, bisect_right
    present = {k: v for k, v in values.items() if v is not None}
    n = len(present)
    out = {k: neutral for k in values}
    if n == 0:
        return out
    if n == 1:
        for k in present:
            out[k] = 0.5
        return out
    ordered = sorted(present.values())
    for k, v in present.items():
        less = bisect_left(ordered, v)
        tie = bisect_right(ordered, v) - less
        pct = (2 * less + (tie - 1)) / (2 * (n - 1))
        out[k] = (1.0 - pct) if not higher_is_better else pct
    if invalid_zero is not None:
        for k in values:
            if values[k] is not None and invalid_zero(values[k]):
                out[k] = 0.0
    return out


def dkey(r, key):
    """None-safe DESCENDING sort key (rank 0.0 is legitimate and must not map to -9e9)."""
    v = r.get(key)
    return -1e18 if v is None else -float(v)


def main() -> int:
    # ---------------- PHASE 0: freeze verification ----------------
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA256, "HASH MISMATCH"
    print("PHASE0 PREREGISTRATION_HASH_MATCH = PASS", flush=True)

    # ---------------- data ----------------
    ui_rows = [json.loads(l) for l in UI.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_date = {}
    for r in ui_rows:
        by_date.setdefault(r["as_of"], []).append(r)
    dates = sorted(by_date)
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    series = {}
    for sym in sorted({r["symbol"] for r in ui_rows}):
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

    def feats(sym, d, trunc=False):
        """Timing features ex ante at signal date d. trunc=True drops observations after d
        (L5/L6 invariance path)."""
        s = series.get(sym)
        if not s:
            return {"max_date_used": None}
        ds, ps = s
        if trunc:
            k = bisect.bisect_right(ds, d)
            ds, ps = ds[:k], ps[:k]
        i = bisect.bisect_right(ds, d) - 1
        if i < 0:
            return {"max_date_used": None}
        f = {"max_date_used": ds[i]}
        if i >= 60 and ps[i] > 0 and ps[i - 60] > 0:
            f["Momentum60"] = ps[i] / ps[i - 60] - 1.0
        if i >= 59 and ps[i] > 0:
            hi = max(ps[i - 59:i + 1])
            if hi > 0:
                f["DistanceFrom60DayHigh"] = ps[i] / hi - 1.0
        if i >= 21:
            rets = [ps[j] / ps[j - 1] - 1.0 for j in range(i - 20, i + 1) if ps[j - 1] > 0]
            if len(rets) == 21:
                f["Volatility30"] = statistics.stdev(rets)
        return f

    # ---------------- PHASE 1-2: candidates + leakage L1/L5/L6 (pre-outcome) ----------------
    leakage = {"L1": True, "L5": True, "L6": True, "L2": True, "L3": True, "L4": True, "L7": True}
    snap_rows = []
    per_date = {}
    for d in dates:
        base = by_date[d]
        n = len(base)
        base_sorted = sorted(base, key=lambda r: -r["ui_score"])
        q5 = base_sorted[4 * (n // 5):]
        feats_q5 = {}
        for r in q5:
            f = feats(r["symbol"], d)
            feats_q5[r["symbol"]] = f
            if f.get("max_date_used") and f["max_date_used"] > d:
                leakage["L1"] = False
        if d in ("2021-03-31", "2023-08-30", "2025-08-31"):
            for r in q5[:40]:
                f_full = feats_q5[r["symbol"]]
                f_trunc = feats(r["symbol"], d, trunc=True)
                for kk in ("Momentum60", "DistanceFrom60DayHigh", "Volatility30"):
                    a, b = f_full.get(kk), f_trunc.get(kk)
                    if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
                        leakage["L5"] = leakage["L6"] = False
        elig = {s: f for s, f in feats_q5.items()
                if all(f.get(k) is not None for k in ("Momentum60", "DistanceFrom60DayHigh", "Volatility30"))}
        r60 = midrank({s: f.get("Momentum60") for s, f in elig.items()})
        rdh = midrank({s: f.get("DistanceFrom60DayHigh") for s, f in elig.items()})
        rvol = midrank({s: f.get("Volatility30") for s, f in elig.items()}, higher_is_better=False)
        core_a = {s: (r60[s] + rdh[s] + rvol[s]) / 3.0 for s in elig}
        rank_a = midrank(core_a, neutral=0.0)
        core_mom = {s: (r60[s] + rdh[s]) / 2.0 for s in elig}
        rank_mom = midrank(core_mom, neutral=0.0)
        elig_b = {}
        for r in base:
            s = r["symbol"]
            f = feats(s, d)
            if all(f.get(k) is not None for k in ("Momentum60", "DistanceFrom60DayHigh", "Volatility30")):
                elig_b[s] = (f, r)
        r60b = midrank({s: f.get("Momentum60") for s, (f, r) in elig_b.items()})
        rdhb = midrank({s: f.get("DistanceFrom60DayHigh") for s, (f, r) in elig_b.items()})
        rvolb = midrank({s: f.get("Volatility30") for s, (f, r) in elig_b.items()}, higher_is_better=False)
        core_b = {s: (r60b[s] + rdhb[s] + rvolb[s]) / 3.0 for s in elig_b}
        ui_rank_b = midrank({s: r["ui_score"] for s, (f, r) in elig_b.items()})
        final_b = {s: 0.5 * ui_rank_b[s] + 0.5 * core_b[s] for s in elig_b}
        rank_b = midrank(final_b, neutral=0.0)
        per_date[d] = {"q5": q5, "elig_a_syms": set(elig.keys()), "rank_a": rank_a,
                       "core_a": core_a, "rank_mom": rank_mom, "core_mom": core_mom,
                       "elig_b_syms": set(elig_b.keys()), "rank_b": rank_b, "final_b": final_b,
                       "feats_q5": feats_q5}
        ui_q5_rank = midrank({x["symbol"]: x["ui_score"] for x in q5})
        for r in q5:
            s = r["symbol"]
            f = feats_q5[s]
            snap_rows.append({
                "signal_date": d, "symbol": s, "security_id": r.get("security_id"),
                "ui_score": r["ui_score"], "ui_rank_q5": ui_q5_rank.get(s), "ui_quintile": "Q5",
                "Momentum60": f.get("Momentum60"), "Momentum60Rank": r60.get(s),
                "DistanceFrom60DayHigh": f.get("DistanceFrom60DayHigh"),
                "DistanceFrom60DayHighRank": rdh.get(s),
                "Volatility30": f.get("Volatility30"), "InverseVolatility30Rank": rvol.get(s),
                "TIMING_CORE": core_a.get(s), "FINAL_SIGNAL_RANK_A": rank_a.get(s),
                "TIMING_MOMENTUM": core_mom.get(s), "FINAL_SIGNAL_RANK_A_MOMENTUM": rank_mom.get(s),
                "FINAL_SIGNAL_B": final_b.get(s), "FINAL_SIGNAL_RANK_B": rank_b.get(s),
                "timing_eligible_A": s in elig,
                "missing_features": [k for k in ("Momentum60", "DistanceFrom60DayHigh", "Volatility30")
                                     if f.get(k) is None],
                "candidate_versions": ["signal-v1-A", "signal-v1-A-momentum", "signal-v1-B"]})
    u0 = ui_rows[0]
    leakage["L2"] = leakage["L3"] = (u0.get("calculation_version") == "ui_score_historical_v1"
                                     and u0.get("score_version") == "canonical-v1-dev")
    src_self = Path(__file__).read_text(encoding="utf-8")
    leakage["L4"] = ("tsetmc_current_shares" not in src_self
                     and "nonresearch_instruments" not in src_self)
    leakage["L7"] = (all(not any(kk.startswith("ret") or "excess" in kk for kk in r)
                         for r in snap_rows)
                     and "raw_closing_universe" in src_self
                     and "corporate_actions" not in src_self)

    # ---------------- PHASE 3: freeze the signal snapshot ----------------
    with open(SNAP, "w", encoding="utf-8") as fh:
        for r in snap_rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    snap_sha = hashlib.sha256(SNAP.read_bytes()).hexdigest()
    print(f"PHASE3 snapshot rows={len(snap_rows)} sha256={snap_sha}", flush=True)
    print(f"PHASE2 leakage: {json.dumps(leakage)}", flush=True)
    if not all(leakage.values()):
        json.dump({"SIGNAL_V1_INTEGRITY_GATE": "FAIL", "leakage": leakage},
                  open(RESULTS, "w", encoding="utf-8"), indent=1)
        print("SIGNAL_V1_INTEGRITY_GATE = FAIL - STOP before performance")
        return 1

    # ---------------- PHASE 4: attach frozen outcomes (post-snapshot) ----------------
    import psycopg
    DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
    ca_events = {}
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT s.codal_symbol, ca.action_date, ca.adjustment_factor
                       FROM market.corporate_actions ca JOIN core.securities s ON s.id=ca.security_id
                       WHERE ca.source='tsetmc_gap_rule_v1' AND ca.adjustment_evidence_status='CONFIRMED'""")
        for sym, d, f in cur.fetchall():
            ca_events.setdefault(sym, []).append(
                (d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(f)))
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(x) for (x,) in cur.fetchall()]
    adj_series = {}
    for sym, (ds, ps) in series.items():
        ins = (idx.get(sym) or {}).get("ins_code")
        evs = sorted(ca_events.get(sym, []), key=lambda e: e[0])
        c, run, ei = {}, 1.0, len(evs) - 1
        for d in reversed(ds):
            dd = dt.date.fromisoformat(d)
            while ei >= 0 and evs[ei][0] > dd:
                run *= evs[ei][1]
                ei -= 1
            c[d] = run
        adj_series[sym] = {"dates": ds, "adj": {d: ps[k] * c[d] for k, d in enumerate(ds)}}

    def fwd(sym, signal_date, h):
        s = adj_series.get(sym)
        if not s:
            return None
        i = bisect.bisect_right(s["dates"], signal_date)
        entry = s["dates"][i] if i < len(s["dates"]) else None
        if entry is None:
            return None
        j = bisect.bisect_right(cal, entry) - 1
        kx = j + h
        if kx >= len(cal):
            return None
        exit_d = cal[kx]
        a0, a1 = s["adj"].get(entry), s["adj"].get(exit_d)
        if not a0 or not a1:
            return None
        return a1 / a0 - 1.0

    for r in snap_rows:
        r["fwd"] = {f"ret_{h}": fwd(r["symbol"], r["signal_date"], h) for h in HORIZONS}
    uni_mean = {}
    for d in dates:
        for h in HORIZONS:
            vals = [fwd(r["symbol"], d, h) for r in by_date[d]]
            vals = [x for x in vals if x is not None]
            uni_mean[(d, h)] = float(np.mean(vals)) if vals else None
    for r in snap_rows:
        r["excess"] = {f"ret_{h}": (r["fwd"][f"ret_{h}"] - uni_mean[(r["signal_date"], h)]
                                    if r["fwd"][f"ret_{h}"] is not None
                                    and uni_mean.get((r["signal_date"], h)) is not None else None)
                       for h in HORIZONS}

    # ---------------- metric helpers ----------------
    def ic_stats(pairs_by_date):
        ics = []
        for pairs in pairs_by_date.values():
            if len(pairs) >= 5:
                ics.append(M.spearman([p[0] for p in pairs], [p[1] for p in pairs]))
        return ics

    def quintile_table(rows_fn, key, h):
        qd = {q: {"n": 0, "rets": [], "exc": [], "wins": []} for q in range(1, 6)}
        spreads_mean, spreads_med = [], []
        for d in dates:
            rs = [r for r in rows_fn(d) if r["fwd"][f"ret_{h}"] is not None and r.get(key) is not None]
            if len(rs) < 10:
                continue
            um = float(np.mean([r["fwd"][f"ret_{h}"] for r in rs]))
            rs_sorted = sorted(rs, key=lambda r: dkey(r, key))
            m = len(rs_sorted)
            rm, sm = [], []
            for qi in range(5):
                q = rs_sorted[qi * m // 5: (qi + 1) * m // 5]
                rets = [r["fwd"][f"ret_{h}"] for r in q]
                qd[qi + 1]["n"] += len(rets)
                qd[qi + 1]["rets"] += rets
                qd[qi + 1]["exc"] += [x - um for x in rets]
                qd[qi + 1]["wins"] += [1.0 if x > 0 else 0.0 for x in rets]
                rm.append(float(np.mean(rets)))
                sm.append(float(np.median(rets)))
            if len(rm) == 5:
                spreads_mean.append(rm[4] - rm[0])
                spreads_med.append(sm[4] - sm[0])
        table = {}
        for q in range(1, 6):
            e = qd[q]
            table[q] = {"n": e["n"], "mean_ret": float(np.mean(e["rets"])) if e["rets"] else None,
                        "median_ret": float(np.median(e["rets"])) if e["rets"] else None,
                        "mean_excess": float(np.mean(e["exc"])) if e["exc"] else None,
                        "median_excess": float(np.median(e["exc"])) if e["exc"] else None,
                        "win_rate": float(np.mean(e["wins"])) if e["wins"] else None}
        table["Q5_minus_Q1_mean"] = (table[5]["mean_ret"] - table[1]["mean_ret"]) if table[5]["mean_ret"] is not None else None
        table["Q5_minus_Q1_median"] = (table[5]["median_ret"] - table[1]["median_ret"]) if table[5]["median_ret"] is not None else None
        table["mean_spread_exc"] = float(np.mean(spreads_mean)) if spreads_mean else None
        table["median_spread_exc"] = float(np.median(spreads_med)) if spreads_med else None
        return table

    def block_boot(dlist, ic_fn, spread_fn, k):
        rng = random.Random(SEED)
        ics, pfs, spr = [], [], []
        for d in dlist:
            a = ic_fn(d)
            if a is not None:
                ics.append(a)
                pfs.append(1.0 if a > 0 else 0.0)
            s = spread_fn(d)
            if s is not None:
                spr.append(s)
        m = len(ics)
        bi, bp, bs = [], [], []
        for _ in range(B):
            take = []
            while len(take) < m:
                st = rng.randrange(0, max(1, m - k + 1))
                take += list(range(st, min(st + k, m)))
            take = take[:m]
            bi.append(float(np.mean([ics[i] for i in take])))
            bp.append(float(np.mean([pfs[i] for i in take])))
            if len(spr) == m:
                bs.append(float(np.mean([spr[i] for i in take])))
        res = {"n_dates": m, "ic_ci95": [float(np.quantile(bi, 0.025)), float(np.quantile(bi, 0.975))],
               "pos_frac_ci95": [float(np.quantile(bp, 0.025)), float(np.quantile(bp, 0.975))],
               "p_ic_le_0": float(np.mean([x <= 0 for x in bi]))}
        if len(bs) == m:
            res["spread_ci95"] = [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))]
            res["p_spread_le_0"] = float(np.mean([x <= 0 for x in bs]))
        return res

    # ---------------- candidate evaluation ----------------
    def eval_candidate(label, rows_fn, key):
        rows_map = {d: rows_fn(d) for d in dates}
        dlist = [d for d in dates if len(rows_map[d]) >= 5]
        pairs_by, pairs_by_base = {}, {}
        for d in dlist:
            rs = [r for r in rows_map[d] if r["fwd"]["ret_63"] is not None]
            if len(rs) >= 5:
                pairs_by[d] = [(r[key], r["fwd"]["ret_63"]) for r in rs]
                pairs_by_base[d] = [(r["ui_score"], r["fwd"]["ret_63"]) for r in rs]
        ics_sig = ic_stats(pairs_by)
        ics_base = ic_stats(pairs_by_base)

        def ic63(d):
            return ic_stats({d: pairs_by[d]})[0] if d in pairs_by else None

        def spread(d):
            rs = [r for r in rows_map[d] if r["fwd"]["ret_63"] is not None]
            if len(rs) < 10:
                return None
            s = sorted(rs, key=lambda r: dkey(r, key))
            m = len(s)
            return (float(np.mean([r["fwd"]["ret_63"] for r in s[4*(m//5):]]))
                    - float(np.mean([r["fwd"]["ret_63"] for r in s[:4*(m//5)]])))

        qtable = quintile_table(rows_fn, key, 63)
        boot = block_boot(dlist, ic63, spread, 3)
        annual = {}
        for y in (2021, 2022, 2023, 2024, 2025, 2026):
            vals = [ic63(d) for d in dlist if d[:4] == str(y)]
            vals = [x for x in vals if x is not None]
            annual[y] = {"mean": float(np.mean(vals)) if vals else None, "n": len(vals)}
        tot, transitions, prev = [], 0, None
        for d in dlist:
            rs = [r for r in rows_map[d] if r.get(key) is not None]
            if len(rs) < 10:
                continue
            k = max(1, int(len(rs) * 0.2))
            cur = {r["symbol"] for r in sorted(rs, key=lambda r: dkey(r, key))[:k]}
            if prev is not None:
                tot.append(1.0 - len(cur & prev) / len(prev))
                transitions += 1
            prev = cur
        base_spreads = []
        for d in dlist:
            rs = [r for r in rows_map[d] if r["fwd"]["ret_63"] is not None]
            if len(rs) < 10:
                continue
            s = sorted(rs, key=lambda r: -r["ui_score"])
            m = len(s)
            base_spreads.append(float(np.mean([r["fwd"]["ret_63"] for r in s[4*(m//5):]]))
                                - float(np.mean([r["fwd"]["ret_63"] for r in s[:4*(m//5)]])))
        syms = {r["symbol"] for d in dlist for r in rows_map[d]}
        return {"label": label, "n_rows": sum(len(rows_map[d]) for d in dlist),
                "n_dates_ic": len(ics_sig), "symbols": len(syms),
                "ic63_mean": float(np.mean(ics_sig)) if ics_sig else None,
                "ic63_median": float(np.median(ics_sig)) if ics_sig else None,
                "ic63_positive_fraction": float(np.mean([x > 0 for x in ics_sig])) if ics_sig else None,
                "annual_ic63": annual,
                "quintiles_63": qtable, "bootstrap_63": boot,
                "turnover": {"mean": round(float(np.mean(tot)), 4) if tot else None,
                             "median": round(float(np.median(tot)), 4) if tot else None,
                             "p90": round(float(np.quantile(tot, 0.90)), 4) if tot else None,
                             "n_transitions": transitions},
                "baseline": {"ic63_mean": float(np.mean(ics_base)) if ics_base else None,
                             "ic63_positive_fraction": (float(np.mean([x > 0 for x in ics_base]))
                                                        if ics_base else None),
                             "q5_q1_mean_excess_spread": (float(np.mean(base_spreads))
                                                          if base_spreads else None)},
                "delta_ic63": (float(np.mean(ics_sig) - np.mean(ics_base))
                               if ics_sig and ics_base else None),
                "delta_spread63": (qtable["mean_spread_exc"]
                                   - (float(np.mean(base_spreads)) if base_spreads else None))}

    def rows_A(d):
        pd_ = per_date[d]
        return [r for r in by_date[d] if r["symbol"] in pd_["elig_a_syms"]]

    def rows_A_mom(d):
        pd_ = per_date[d]
        return [r for r in by_date[d] if r["symbol"] in pd_["rank_mom"]]

    def rows_B(d):
        pd_ = per_date[d]
        return [r for r in by_date[d] if r["symbol"] in pd_["elig_b_syms"]]

    res_a = eval_candidate("signal-v1-A", rows_A, "FINAL_SIGNAL_RANK_A")
    res_amom = eval_candidate("signal-v1-A-momentum", rows_A_mom, "FINAL_SIGNAL_RANK_A_MOMENTUM")
    res_b = eval_candidate("signal-v1-B", rows_B, "FINAL_SIGNAL_RANK_B")

    # secondary/diagnostic horizons (descriptive)
    sec = {}
    for label, rows_fn, key in (("signal-v1-A", rows_A, "FINAL_SIGNAL_RANK_A"),
                                ("signal-v1-A-momentum", rows_A_mom, "FINAL_SIGNAL_RANK_A_MOMENTUM"),
                                ("signal-v1-B", rows_B, "FINAL_SIGNAL_RANK_B")):
        sec[label] = {}
        for h in (126, 21):
            ics, spreads = [], []
            for d in dates:
                rs = [r for r in rows_fn(d) if r["fwd"][f"ret_{h}"] is not None and r.get(key) is not None]
                if len(rs) >= 5:
                    ics.append(M.spearman([r[key] for r in rs], [r["fwd"][f"ret_{h}"] for r in rs]))
                if len(rs) >= 10:
                    s = sorted(rs, key=lambda r: dkey(r, key))
                    m = len(s)
                    spreads.append(float(np.mean([r["fwd"][f"ret_{h}"] for r in s[4*(m//5):]]))
                                   - float(np.mean([r["fwd"][f"ret_{h}"] for r in s[:4*(m//5)]])))
            sec[label][f"h{h}"] = {"ic_mean": round(float(np.mean(ics)), 4) if ics else None,
                                   "positive_fraction": (round(float(np.mean([x > 0 for x in ics])), 3)
                                                         if ics else None),
                                   "Q5_Q1_spread_mean": (round(float(np.mean(spreads)), 4)
                                                         if spreads else None)}

    # coverage (SG7)
    q5_rows = sum(len(per_date[d]["q5"]) for d in dates)
    elig_rows = sum(len(per_date[d]["elig_a_syms"]) for d in dates)
    miss = {"Momentum60": 0, "DistanceFrom60DayHigh": 0, "Volatility30": 0}
    for d in dates:
        for r in per_date[d]["q5"]:
            f = per_date[d]["feats_q5"][r["symbol"]]
            for k in miss:
                if f.get(k) is None:
                    miss[k] += 1
    coverage = {"ui_q5_rows": q5_rows, "timing_eligible_rows": elig_rows, "missing": miss,
                "coverage_pct": round(elig_rows / q5_rows * 100, 2)}

    # ---------------- SG1-SG8 for the PRIMARY ----------------
    sg = {
        "SG1": res_a["ic63_mean"] is not None and res_a["ic63_mean"] >= 0.05,
        "SG2a": res_a["ic63_positive_fraction"] is not None and res_a["ic63_positive_fraction"] >= 0.60,
        "SG2b": sum(1 for y in (2021, 2022, 2023, 2024, 2025)
                    if res_a["annual_ic63"][y]["mean"] is not None
                    and res_a["annual_ic63"][y]["mean"] > 0) >= 4,
        "SG3": (res_a["quintiles_63"]["mean_spread_exc"] is not None
                and res_a["quintiles_63"]["mean_spread_exc"] >= 0.02
                and res_a["bootstrap_63"].get("spread_ci95") is not None
                and res_a["bootstrap_63"]["spread_ci95"][0] > 0),
        "SG4": res_a["bootstrap_63"]["ic_ci95"][0] > 0,
        "SG5": (res_a["delta_ic63"] is not None and res_a["delta_ic63"] >= 0.02
                and res_a["delta_spread63"] is not None and res_a["delta_spread63"] >= 0.01),
        "SG6": res_a["turnover"]["mean"] is not None and res_a["turnover"]["mean"] <= 0.50,
        "SG7": coverage["coverage_pct"] >= 85,
        "SG8": all(leakage.values()),
    }
    gate = "PASS" if all(sg.values()) else "FAIL"

    doc = {"version": "SIGNAL_V1_EXECUTION", "preregistration_sha256": PREREG_SHA256,
           "snapshot_sha256": snap_sha, "leakage": leakage, "coverage": coverage,
           "candidates": {"signal-v1-A": res_a, "signal-v1-A-momentum": res_amom,
                          "signal-v1-B": res_b},
           "secondary_horizons": sec, "sg": sg, "SIGNAL_V1_PRIMARY_GATE": gate,
           "SIGNAL_V1_SHADOW_ELIGIBLE": "YES" if gate == "PASS" else "NO"}
    RESULTS.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("SG:", json.dumps(sg), flush=True)
    print("SIGNAL_V1_PRIMARY_GATE:", gate, flush=True)
    print("A:", json.dumps({"ic63": res_a["ic63_mean"], "pf": res_a["ic63_positive_fraction"],
                            "spread63exc": res_a["quintiles_63"]["mean_spread_exc"],
                            "delta_ic63": res_a["delta_ic63"],
                            "delta_spread63": res_a["delta_spread63"],
                            "turnover": res_a["turnover"]["mean"]}), flush=True)
    print("A base:", json.dumps(res_a["baseline"]), flush=True)
    print("A annual:", json.dumps(res_a["annual_ic63"], default=str), flush=True)
    print("A-mom:", json.dumps({"ic63": res_amom["ic63_mean"], "pf": res_amom["ic63_positive_fraction"],
                                "spread": res_amom["quintiles_63"]["mean_spread_exc"],
                                "turnover": res_amom["turnover"]["mean"]}), flush=True)
    print("B:", json.dumps({"ic63": res_b["ic63_mean"], "pf": res_b["ic63_positive_fraction"],
                            "spread": res_b["quintiles_63"]["mean_spread_exc"],
                            "delta_ic63": res_b["delta_ic63"]}), flush=True)
    print("126d:", json.dumps({k: v["h126"] for k, v in sec.items()}), flush=True)
    print("21d:", json.dumps({k: v["h21"] for k, v in sec.items()}), flush=True)
    print("wrote signal_v1_results.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
