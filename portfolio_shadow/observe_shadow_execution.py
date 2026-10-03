"""SHADOW V1 — observe_shadow_execution.py

Observes what would actually have happened to the frozen paper orders of one shadow
month (SHADOW_V1_SPEC §5–§9, §15), closes the month through the certified accounting
engine (deterministic port), and writes the monthly observation artifacts exactly once.

Rules implemented here (frozen):
  - EXECUTION_DATE = first shadow trading date strictly after the decision as_of (§5a);
    recomputed at observation time from the fullest calendar; a change vs the decision-time
    projection is logged, never applied later-ward.
  - path-A fill evidence = raw cache record on E with qTotTran5J > 0 (§7);
    missing cache data -> DATA_MISSING (no fill), never synthesized (§5b/§7).
  - fills/valuation on the CONFIRMED adjusted chain, identical to the certified engine (§5b).
  - path-B (market.price_observations, vendor series) is diagnostic ONLY (§5b/§7/§9).
  - held names that are not re-selected are sold iff independently tradable on E
    (cache record with volume > 0) — identical to the certified backtest's rules.
  - observation finalization: caches cover E, or E + 7 calendar days deadline (§15b).
  - the performance block completed by this month's E belongs to the PREVIOUS decision
    month (the entry rebalance is excluded from its own return), mirroring the backtest.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\RFA\Company-Financial\portfolio_research")))

import pandas as pd
import psycopg

import shadow_common as sc
from deterministic_accounting import rebalance_accounts, assert_invariants
from repair_accounting_v1 import build_adj, price_at     # certified chain logic, unmodified

SHADOW_DIR = sc.ROOT / "portfolio_shadow"


def append_issue(text: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(SHADOW_DIR / "SHADOW_V1_ISSUES.md", "a", encoding="utf-8") as fh:
        fh.write(f"\n- [{ts}] {text}\n")


def db_evidence_for(pg, security_ids: list[str], E: str) -> dict[str, dict]:
    """Path-B deduplicated rows (max collected_at per security) for diagnostics only."""
    out = {}
    if not security_ids:
        return out
    with pg.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (security_id) security_id::text, closing_price_rial,
                              last_price_rial, volume, trade_value_rial, closing_change_percent,
                              collected_at
                       FROM market.price_observations
                       WHERE trade_date=%s AND security_id::text = ANY(%s)
                       ORDER BY security_id, collected_at DESC""", (E, security_ids))
        for r in cur.fetchall():
            out[r[0]] = {"closing_price_rial": float(r[1]) if r[1] is not None else None,
                         "last_price_rial": float(r[2]) if r[2] is not None else None,
                         "volume": int(r[3]) if r[3] is not None else None,
                         "trade_value_rial": float(r[4]) if r[4] is not None else None,
                         "closing_change_percent": float(r[5]) if r[5] is not None else None,
                         "collected_at": r[6].isoformat() if r[6] else None}
    return out


def classify_and_fill(order: dict, rec_e: dict | None, dbrow: dict | None,
                      session_existed: bool) -> tuple[str, dict]:
    """Spec §7 primary flag + path-A fill fields (never fills without path-A evidence)."""
    diag = {"db_cross_check": ("row_present" if dbrow else "no_row") if session_existed else "no_session"}
    if order["identity_status"] == "IDENTITY_ERROR":
        return "IDENTITY_ERROR", diag
    if rec_e is None:
        # conservative: two independent sources lacking the security on a real session day
        # = probable suspension; any DB row = source disagreement = data gap. No fill either way.
        if session_existed and dbrow is None:
            return "SUSPENDED", diag
        return "DATA_MISSING", diag
    vol = rec_e.get("qTotTran5J") or 0
    pclose = rec_e.get("pClosing")
    if pclose is None:
        return ("INSUFFICIENT_LIQUIDITY_DATA" if vol > 0 else "NO_TRADE"), diag
    if float(vol) <= 0:
        return "NO_TRADE", diag
    diag["pDrCotVal_last_trade"] = (float(rec_e["pDrCotVal"])
                                    if rec_e.get("pDrCotVal") is not None else None)
    chg = (dbrow or {}).get("closing_change_percent")
    if chg is not None and (abs(abs(chg) - 7.0) <= 0.1 or abs(abs(chg) - 10.0) <= 0.1):
        diag["price_limit_candidate"] = True
        diag["observed_closing_change_percent"] = chg
    return "EXECUTABLE_REFERENCE", diag


def close_month(adj: dict, orders: list[dict], holdings: dict, cash: float, E: str,
                n_sel: int) -> dict:
    """Certified-engine month close at E (spec §12): fills, invariants, post state."""
    meta = {k: (h.get("symbol"), h.get("ins_code")) for k, h in holdings.items()}
    for o in orders:
        meta.setdefault(o.get("portfolio_security_key") or o.get("company_id"),
                        (o.get("symbol"), o.get("ins_code")))
    cur_vals = {}
    for key in sorted(holdings):
        h = holdings[key]
        p = price_at(adj, h["symbol"], E)
        cur_vals[key] = h["shares"] * p if p is not None else 0.0
    value_pre = cash + sum(cur_vals.values())
    pre_w = {k: v / value_pre for k, v in cur_vals.items()} if value_pre > 0 else {}
    pre_cash_w = cash / value_pre if value_pre > 0 else 0.0

    exec_keys = {o["portfolio_security_key"] for o in orders if o["flag"] == "EXECUTABLE_REFERENCE"}
    target_values = {k: value_pre / n_sel for k in sorted(exec_keys)}
    tradable = {}
    for key in sorted(set(cur_vals) | set(target_values)):
        if key in target_values:
            tradable[key] = True
        else:                                   # held, not re-selected: sell iff independently tradable
            sym, ins = meta.get(key, (None, None))
            rec = sc.load_raw_cache(sym, ins) or {} if sym else {}
            tradable[key] = bool((rec.get(E) or {}).get("qTotTran5J"))

    res = rebalance_accounts(cash, cur_vals, target_values, tradable, sc.COST_RATE_BASE)
    assert_invariants(cash, cur_vals, res)
    cash_post, new_pos_vals, cost, buys, sells, buy_scale = res

    post_holdings = {}
    for key in sorted(new_pos_vals):
        sym, ins = meta.get(key, (None, None))
        p = price_at(adj, sym, E) if sym else None
        post_holdings[key] = {"symbol": sym, "ins_code": ins,
                              "shares": new_pos_vals[key] / p if p else 0.0,
                              "value_at_E": new_pos_vals[key]}
    nav_post = cash_post + sum(new_pos_vals.values())
    if abs(nav_post - (value_pre - cost)) > 1e-9:
        raise AssertionError("NAV identity violated at month close")

    # frozen turnover formula (prereg §6): 0.5 x sum|target_w - pre_w| incl. cash
    tw = {o["portfolio_security_key"]: 1.0 / n_sel for o in orders if o["flag"] == "EXECUTABLE_REFERENCE"}
    n_failed = sum(1 for o in orders if o["flag"] != "EXECUTABLE_REFERENCE")
    target_cash_w = n_failed * (1.0 / n_sel if n_sel else 0.0)
    union = sorted(set(tw) | set(pre_w))
    turnover = 0.5 * (sum(abs(tw.get(s, 0.0) - pre_w.get(s, 0.0)) for s in union)
                      + abs(target_cash_w - pre_cash_w))
    return {"value_pre_trade": value_pre, "cash_pre": cash,
            "cash_post": cash_post, "post_holdings": post_holdings, "cost": cost,
            "buys": buys, "sells": sells, "buy_scale": buy_scale, "nav_post": nav_post,
            "turnover": turnover, "n_failed": n_failed,
            "holdings_count": sum(1 for v in new_pos_vals.values() if v > nav_post * 1e-9)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: latest unfinalized decision)")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    state = json.loads(sc.STATE_PATH.read_text(encoding="utf-8"))
    if args.month:
        idx = next(i for i, d in enumerate(state["decisions"]) if d["decision_month"] == args.month)
    else:
        idx = next((i for i, d in enumerate(state["decisions"]) if not d.get("observation_final")), None)
    if idx is None:
        print(json.dumps({"observation": None, "message": "no unfinalized shadow decision"}))
        return 0
    dec = state["decisions"][idx]
    month = dec["decision_month"]
    month_tag = month.replace("-", "_")

    orders = pd.read_parquet(SHADOW_DIR / f"shadow_orders_{month_tag}.parquet").to_dict("records")
    as_of = dec["as_of_date"]
    n_sel = dec["n_selected"]

    adj = build_adj()
    with psycopg.connect(sc.DSN) as pg:
        cal_dates = [d for d, _ in sc.shadow_calendar_rows(pg)]
        E = sc.first_execution_date(cal_dates, as_of)
        if E is None:
            print(json.dumps({"observation": month, "status": "NO_EXECUTION_DATE_YET"}))
            return 0
        proj = dec.get("exec_date_projected")
        if proj and proj != E:
            append_issue(f"{month}: EXECUTION_DATE recomputed per frozen rule §5a: "
                         f"decision-time projection {proj} -> final {E} (earliest qualifying "
                         f"session; calendar data arrived after decision freeze)")
        sec_ids = [o["security_id"] for o in orders if o.get("security_id")]
        dbrows = db_evidence_for(pg, sec_ids, E)

        caches_max = sc.raw_caches_max_date()
        deadline = dt.date.fromisoformat(E) + dt.timedelta(days=sc.OBSERVATION_DEADLINE_DAYS)
        covered = caches_max is not None and caches_max >= E
        expired = dt.date.today() >= deadline
        if not covered and not expired:
            print(json.dumps({"observation": month, "status": "CHECK_ONLY",
                              "exec_date": E, "caches_max_date": caches_max,
                              "finalize_deadline": deadline.isoformat(),
                              "message": "caches do not cover E yet; §15b deadline not reached"}))
            return 0

        obs_rows = []
        for o in sorted(orders, key=lambda r: r["shadow_order_id"]):
            rec = sc.load_raw_cache(o["symbol"], o["ins_code"]) or {}
            flag, diag = classify_and_fill(o, rec.get(E), dbrows.get(o["security_id"]),
                                           session_existed=True)
            o["flag"] = flag
            row = dict(o)
            row["diagnostics"] = json.dumps(diag, ensure_ascii=False, sort_keys=True)
            obs_rows.append(row)

    pre_state = dec.get("pre_decision_state") or {"cash": 1.0, "holdings": {}}
    close = close_month(adj, orders, pre_state.get("holdings", {}),
                        float(pre_state.get("cash", 1.0)), E, n_sel)

    # benchmark: equal-weight ALL eligible scored names, identical engine/conventions (§15)
    snap = json.loads((SHADOW_DIR / f"shadow_snapshot_{month_tag}.json").read_text(encoding="utf-8"))
    prev_pfs = state["decisions"][idx - 1].get("post_fill_state") if idx > 0 else None
    bench_pre = (prev_pfs or {}).get("benchmark") or {"cash": 1.0, "holdings": {}}
    bench_orders = []
    for r in sorted(snap["rows"], key=lambda r: r["ui_rank"]):
        sym, ins = r["symbol"], r["ins_code"]
        rec = sc.load_raw_cache(sym, ins) or {} if sym else {}
        traded = bool((rec.get(E) or {}).get("qTotTran5J"))
        identity_ok = r["identity_status"] in ("MAP_VERIFIED", "FORWARD_MAP_VERIFIED")
        bench_orders.append({"portfolio_security_key": r.get("portfolio_security_key") or r["company_id"],
                             "company_id": r["company_id"], "symbol": sym, "ins_code": ins,
                             "identity_status": r["identity_status"],
                             "flag": "EXECUTABLE_REFERENCE" if (traded and identity_ok)
                                     else ("IDENTITY_ERROR" if not identity_ok else "DATA_MISSING")})
    bench = close_month(adj, bench_orders, bench_pre.get("holdings", {}),
                        float(bench_pre.get("cash", 1.0)), E, len(bench_orders))

    # performance block completed by this E: the previous decision month's period
    perf = None
    if idx > 0 and prev_pfs and prev_pfs.get("exec_date"):
        E_prev = prev_pfs["exec_date"]
        v0, v1 = prev_pfs["portfolio"]["nav_post"], close["nav_post"]
        b0, b1 = prev_pfs["benchmark"]["nav_post"], bench["nav_post"]
        perf = {"period_month": state["decisions"][idx - 1]["decision_month"],
                "from_exec_date": E_prev, "to_exec_date": E,
                "portfolio_return": v1 / v0 - 1.0, "benchmark_return": b1 / b0 - 1.0,
                "excess_return": (v1 / v0 - 1.0) - (b1 / b0 - 1.0),
                "return_semantics": "PRICE_PLUS_MECHANICAL_ADJUSTMENTS (no cash dividends)"}

    flags = {}
    for o in orders:
        flags[o["flag"]] = flags.get(o["flag"], 0) + 1
    scores = [r["quant_score"] for r in snap["rows"] if r.get("quant_score") is not None]
    dqs = [r["data_quality_score"] for r in snap["rows"] if r.get("data_quality_score") is not None]

    obs_path = SHADOW_DIR / f"shadow_execution_observations_{month_tag}.parquet"
    sum_path = SHADOW_DIR / f"shadow_execution_summary_{month_tag}.json"
    if args.check_only:
        print(json.dumps({"observation": month, "status": "CHECK_ONLY", "exec_date": E,
                          "flags": flags, "portfolio_turnover": close["turnover"]}, indent=1))
        return 0
    for p in (obs_path, sum_path):
        if p.exists():
            raise RuntimeError(f"artifact exists, never overwritten: {p}")
    obs_df = pd.DataFrame(sorted(obs_rows, key=lambda r: r["shadow_order_id"]))
    obs_df.to_parquet(obs_path, compression="zstd", index=False)

    bench_flag_counts = {}
    for b_ in bench_orders:
        bench_flag_counts[b_["flag"]] = bench_flag_counts.get(b_["flag"], 0) + 1
    summary = {
        "artifact_kind": "SHADOW_EXECUTION_SUMMARY", "decision_month": month,
        "as_of_date": as_of, "run_id": dec["run_id"], "exec_date": E,
        "exec_date_projection": dec.get("exec_date_projected"),
        "caches_max_date": caches_max,
        "finalized_by": "cache_coverage" if covered else "deadline_expired",
        "order_flags": flags,
        "portfolio_close": close, "benchmark_close": bench,
        "benchmark_n_eligible": len(bench_orders), "benchmark_flag_counts": bench_flag_counts,
        "completed_period_performance": perf,
        "monitoring": {
            "eligible_universe_size": dec["n_eligible"], "selected_holdings": n_sel,
            "target_turnover": close["turnover"],
            "cash_weight_post": close["cash_post"] / close["nav_post"] if close["nav_post"] else None,
            "estimated_transaction_cost_base": close["cost"],
            "score_distribution": {"n": len(scores), "mean": sum(scores) / len(scores),
                                   "min": min(scores), "max": max(scores),
                                   "quartiles": [sorted(scores)[int(q * (len(scores) - 1))]
                                                 for q in (0.25, 0.5, 0.75)]},
            "dq_distribution": {"n": len(dqs), "mean": sum(dqs) / len(dqs),
                                "min": min(dqs), "max": max(dqs)},
            "identity_status_counts": {s: sum(1 for r in snap["rows"] if r["identity_status"] == s)
                                       for s in {r["identity_status"] for r in snap["rows"]}},
        },
        "artifact_hashes": {"shadow_execution_observations.parquet": sc.sha256_file(obs_path)},
    }
    sum_path.write_bytes(sc.canonical_json(summary).encode("utf-8") + b"\n")

    dec["observation_final"] = True
    dec["exec_date_final"] = E
    dec["post_fill_state"] = {"exec_date": E,
                              "portfolio": {"cash": close["cash_post"], "holdings": close["post_holdings"],
                                            "nav_post": close["nav_post"]},
                              "benchmark": {"cash": bench["cash_post"], "holdings": bench["post_holdings"],
                                            "nav_post": bench["nav_post"]}}
    unfilled = [o["shadow_order_id"] for o in orders if o["flag"] != "EXECUTABLE_REFERENCE"]
    if unfilled:
        append_issue(f"{month}: {len(unfilled)}/{len(orders)} paper orders not executable at "
                     f"reference ({E}); flags={flags}; targets remained cash/carry per frozen rule")
    sc.STATE_PATH.write_text(sc.canonical_json(state) + "\n", encoding="utf-8")
    print(json.dumps({"observation": month, "exec_date": E, "flags": flags,
                      "turnover": close["turnover"], "nav_post": close["nav_post"],
                      "completed_period": perf}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
