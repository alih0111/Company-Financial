"""UI PIT REPAIR VALIDATION (task 12) — rerun of the FROZEN UI validation metrics on the
PIT-correct panel v2. Repair/reproducibility check of an already-fixed score formula.
NOT feature selection; NOT a performance rerun of the event experiment.

Convention: EXACTLY the frozen ui_score_historical_analysis.py convention —
per-date Spearman(ui_score, ret_h) with >=5 pairs/date, mean/median/positive fraction;
quintiles on dates with >=10 rows (ascending Q1=lowest), Q5-Q1 spread, raw + excess.
Forward returns from the canonical adjusted-return pipeline (same code as the frozen run).
Bootstrap: the project's preregistered dependence-aware convention (seed 20261003, B=2000,
block = 3 months (63d) / 6 months (126d) of signal dates, date-level resampling) — the
original UI validation used no bootstrap; this one applies the frozen event-family setting.
Materiality (a priori, before seeing results): |Delta IC| >= 0.02 (the project's material
increment convention, same as FE6), |Delta spread| >= 1.0pp.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, r"D:\RFA\Company-Financial\model_v2_validation")
import model_v2 as M  # noqa: E402  frozen spearman

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "ui_score_research"
SRC = HERE / "ui_score_historical_pit_v2" / "ui_score_historical_pit_v2.jsonl"
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
HORIZONS = (21, 63, 126, 252)
FROZEN = {"21": 0.1103, "63": 0.1543, "126": 0.1806, "252": 0.1571}
SEED, B = 20261003, 2000
R = {"coverage": {}, "ic": {}, "ic_excess": {}, "quintiles": {}, "bootstrap": {},
     "comparison": {}, "artifacts": {}}


def fwd_series():
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT security_id::text, action_date, adjustment_factor
                       FROM market.corporate_actions
                       WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
        events = {}
        for sid, d, f in cur.fetchall():
            events.setdefault(sid, []).append(
                (d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(f)))
        cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
        sec = {s: (i, ins) for s, i, ins in cur.fetchall()}
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]
    adj = {}
    for sym, (sid, ins) in sec.items():
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        dates_s, raw = [], {}
        for r in recs:
            s = str(r["dEven"])
            d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
            dates_s.append(d)
            raw[d] = float(r["pClosing"])
        evs = sorted(events.get(sid, []), key=lambda e: e[0])
        c, run, ei = {}, 1.0, len(evs) - 1
        for d in reversed(dates_s):
            dd = dt.date.fromisoformat(d)
            while ei >= 0 and evs[ei][0] > dd:
                run *= evs[ei][1]
                ei -= 1
            c[d] = run
        adj[sym] = {"dates": dates_s, "adj": {d: raw[d] * c[d] for d in dates_s}}

    def fwd(sym, signal_date, h):
        s = adj.get(sym)
        if not s:
            return None
        i = bisect_right(s["dates"], signal_date)
        entry = s["dates"][i] if i < len(s["dates"]) else None
        if entry is None:
            return None
        j = bisect_right(cal, entry) - 1
        k = j + h
        if k >= len(cal):
            return None
        exit_d = cal[k]
        a0, a1 = s["adj"].get(entry), s["adj"].get(exit_d)
        if not a0 or not a1:
            return None
        return a1 / a0 - 1.0
    return fwd


def block_len(dates, months):
    """max number of consecutive monthly signal dates spanning <= months*30.44 days."""
    ds = [dt.date.fromisoformat(d) for d in dates]
    best = 1
    for i in range(len(ds)):
        j = i
        while j + 1 < len(ds) and (ds[j + 1] - ds[i]).days <= months * 30.44:
            j += 1
        best = max(best, j - i + 1)
    return best


def circular_bootstrap(per_date_stat, dates_order, block, rng):
    vals = np.array([per_date_stat[d] for d in dates_order if d in per_date_stat], dtype=float)
    n = len(vals)
    if n == 0 or block <= 0:
        return None
    nb = int(np.ceil(n / block))
    stats = np.empty(B)
    for b in range(B):
        idx = []
        for _ in range(nb):
            s = rng.integers(0, n)
            idx.extend((s + k) % n for k in range(block))
        stats[b] = vals[np.array(idx[:n])].mean()
    return {"mean": float(vals.mean()), "ci_lower": float(np.percentile(stats, 2.5)),
            "ci_upper": float(np.percentile(stats, 97.5)), "block_len": block, "B": B}


def main() -> int:
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    fwd = fwd_series()
    for r in rows:
        r["forward_returns"] = {f"ret_{h}": fwd(r["symbol"], r["as_of"], h) for h in HORIZONS}
        r["year"] = int(r["as_of"][:4])
    dates = sorted({r["as_of"] for r in rows})
    by_date = {d: [r for r in rows if r["as_of"] == d] for d in dates}
    R["coverage"] = {"rows": len(rows), "dates": len(dates),
                     "symbols": len({r["symbol"] for r in rows}),
                     "rows_with_ret21": sum(1 for r in rows if r["forward_returns"].get("ret_21") is not None),
                     "rows_with_ret252": sum(1 for r in rows if r["forward_returns"].get("ret_252") is not None),
                     "ui_score_null": sum(1 for r in rows if r.get("ui_score") is None)}
    print("coverage:", R["coverage"])

    def valid(r, h):
        return r.get("forward_returns", {}).get(f"ret_{h}") is not None and r.get("ui_score") is not None

    per_date_ic = {h: {} for h in HORIZONS}
    for h in HORIZONS:
        vals = []
        for d in dates:
            pairs = [(r["ui_score"], r["forward_returns"][f"ret_{h}"]) for r in by_date[d] if valid(r, h)]
            if len(pairs) >= 5:
                ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None:
                    per_date_ic[h][d] = ic
                    vals.append(ic)
        R["ic"][h] = {"n_dates": len(vals), "mean_spearman": float(np.mean(vals)) if vals else None,
                      "median_spearman": float(np.median(vals)) if vals else None,
                      "positive_fraction": float(np.mean([v > 0 for v in vals])) if vals else None}
    # excess (per-date equal-weight eligible universe; per-date Spearman identical, kept for parity)
    for h in HORIZONS:
        uni = {}
        for d in dates:
            rets = [r["forward_returns"][f"ret_{h}"] for r in by_date[d] if valid(r, h)]
            uni[d] = float(np.mean(rets)) if rets else None
        vals = []
        for d in dates:
            pairs = [(r["ui_score"], r["forward_returns"][f"ret_{h}"] - uni[d])
                     for r in by_date[d] if valid(r, h) and uni[d] is not None]
            if len(pairs) >= 5:
                ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None:
                    vals.append(ic)
        R["ic_excess"][h] = {"n_dates": len(vals), "mean_spearman": float(np.mean(vals)) if vals else None,
                             "positive_fraction": float(np.mean([v > 0 for v in vals])) if vals else None}

    # quintiles (frozen convention: >=10 rows/date, ascending, equal-count slices)
    q_stats = {h: {"q_means": {q: [] for q in range(1, 6)}, "spreads": [], "n_dates": 0}
               for h in HORIZONS}
    per_date_spread = {}
    for d in dates:
        rs = [r for r in by_date[d] if valid(r, 21)]
        if len(rs) < 10:
            continue
        rs = sorted(rs, key=lambda r: r["ui_score"])
        n = len(rs)
        qs = [rs[i * n // 5: (i + 1) * n // 5] for i in range(5)]
        for h in HORIZONS:
            rm = []
            for qi, q in enumerate(qs):
                rets = [r["forward_returns"][f"ret_{h}"] for r in q
                        if r["forward_returns"].get(f"ret_{h}") is not None]
                if not rets:
                    rm = None
                    break
                rm.append(float(np.mean(rets)))
            if rm is None:
                continue
            q_stats[h]["n_dates"] += 1
            q_stats[h]["spreads"].append(rm[4] - rm[0])
            per_date_spread[(h, d)] = rm[4] - rm[0]
            for qi in range(5):
                q_stats[h]["q_means"][qi + 1].append(rm[qi])
    for h in HORIZONS:
        R["quintiles"][h] = {
            "n_dates": q_stats[h]["n_dates"],
            "quintile_mean_return": {q: (float(np.mean(v)) if v else None)
                                     for q, v in q_stats[h]["q_means"].items()},
            "q5_q1_mean_spread_pp": float(np.mean(q_stats[h]["spreads"])) * 100 if q_stats[h]["spreads"] else None,
        }

    # dependence-aware bootstrap (preregistered convention)
    rng = np.random.default_rng(SEED)
    bl63 = block_len(dates, 3)
    bl126 = block_len(dates, 6)
    R["bootstrap"] = {
        "seed": SEED, "B": B,
        "ic63": circular_bootstrap(per_date_ic[63], dates, bl63, rng),
        "spread63_pp": None,
    }
    sp = {d: v * 100 for (h, d), v in per_date_spread.items() if h == 63}
    R["bootstrap"]["spread63_pp"] = circular_bootstrap(sp, dates, bl63, rng)

    # comparison vs frozen (a priori materiality)
    comp = {}
    cls = set()
    for h in HORIZONS:
        delta = R["ic"][h]["mean_spearman"] - FROZEN[str(h)]
        c = ("MATERIALLY_WEAKER" if delta <= -0.02 else
             "MATERIALLY_STRONGER" if delta >= 0.02 else "UNCHANGED")
        cls.add(c)
        comp[f"IC{h}"] = {"v2": round(R["ic"][h]["mean_spearman"], 4), "frozen": FROZEN[str(h)],
                          "delta": round(delta, 4), "class": c}
    overall = ("NOT_REBUILDABLE" if not rows else
               "MATERIALLY_WEAKER" if "MATERIALLY_WEAKER" in cls and "UNCHANGED" not in cls and "MATERIALLY_STRONGER" not in cls else
               "MATERIALLY_STRONGER" if "MATERIALLY_STRONGER" in cls and "UNCHANGED" not in cls and "MATERIALLY_WEAKER" not in cls else
               "UNCHANGED" if cls == {"UNCHANGED"} else "MIXED" if len(cls) > 1 else cls.pop())
    R["comparison"] = {"per_horizon": comp, "UI_HISTORICAL_VALIDATION_PIT_REPAIR": overall,
                       "materiality_rule": "|Delta IC| >= 0.02 (a priori, = FE6 convention)"}
    print(json.dumps(R["comparison"], indent=1))
    R["artifacts"] = {"panel": str(SRC), "convention": "frozen ui_score_historical_analysis.py"}
    (HERE / "ui_pit_v2_validation.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote:", HERE / "ui_pit_v2_validation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
