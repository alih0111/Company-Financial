"""SIGNAL V1 — PHASE 0-3: candidate construction + snapshot freeze (no outcomes). Preregistration hash
149ba4afd112f63443316a986ac793af60a60f572e13cf446850a6dcea3859ae.

Implements EXACTLY signal-v1-A, signal-v1-A-momentum, signal-v1-B per the frozen Exact
Experiment Specification (E1-E13). Builds the signal-side artifact ONLY (no outcome columns, no forward returns).
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
    # needles assembled from fragments so this construction source contains no
    # literal outcome/current-source reference
    n1, n2, n3 = "tsetmc" + "_current_shares", "nonresearch" + "_instruments", "z" + "Titad"
    leakage["L4"] = (n1 not in src_self and n2 not in src_self and n3 not in src_self)
    leakage["L7"] = (all(not any(kk.startswith("ret") or "excess" in kk for kk in r)
                         for r in snap_rows)
                     and "raw_closing_universe" in src_self
                     and ("corporate" + "_actions") not in src_self)

    # ---------------- PHASE 3: freeze the signal snapshot ----------------
    with open(SNAP, "w", encoding="utf-8") as fh:
        for r in snap_rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    snap_sha = hashlib.sha256(SNAP.read_bytes()).hexdigest()
    print(f"PHASE3 snapshot rows={len(snap_rows)} sha256={snap_sha}", flush=True)
    print(f"PHASE2 leakage: {json.dumps(leakage)}", flush=True)
    integrity = {"leakage": leakage,
                 "snapshot_rows": len(snap_rows), "snapshot_sha256": snap_sha,
                 "ui_artifact_sha256": hashlib.sha256(UI.read_bytes()).hexdigest(),
                 "note": "construction artifact contains no outcome-source references (L4/L7 structural)"}
    (HERE / "output" / "signal_v1_integrity.json").write_text(
        json.dumps(integrity, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote signal_v1_integrity.json (L1-L7 evaluated at construction)", flush=True)
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
