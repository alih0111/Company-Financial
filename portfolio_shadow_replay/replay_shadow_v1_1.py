"""SHADOW V1.1 — HISTORICAL WALK-FORWARD REPLAY  (label: HISTORICAL_REPLAY_ONLY)

Replays the CURRENT frozen Shadow V1.1 harness month-by-month over the 63 certified
historical PIT decision dates (2021-01 .. 2026-06). This is engineering validation of
what the live harness itself would have generated historically. It is NOT the forward
12-month shadow, NOT forward validation, and NOT new evidence for promotion.

Hard guarantees (asserted at runtime):
  - portfolio_shadow/ is NEVER written; shadow_v1_state.json is read-only here and its
    SHA-256 must be byte-identical before and after the run.
  - No shadow decision is created; SHADOW_FORWARD_CLOCK_STARTED stays NO (decisions=[]).
  - Frozen rules only: SHADOW_V1_1_SPEC.md (sha f396b5f6...), selection = highest 20%
    by (quant_score DESC, symbol ASC), equal target weights, 50 bps one-way BASE cost,
    deterministic repaired accounting engine (portfolio_shadow/deterministic_accounting,
    the sorted port of certified repair_accounting_v1.rebalance_accounts), certified
    identity map (company_id:ins_code), path-A cache fill evidence, shadow calendar
    (no Thu/Fri, breadth >= 30), execution = first canonical trading date after the
    score date. No whole-sample optimization, no turnover buffers, no timing.

Engine provenance (identical to the live harness):
  - decision/selection semantics  : portfolio_shadow/build_shadow_portfolio.py
  - execution/close semantics     : portfolio_shadow/observe_shadow_execution.py
  - accounting                    : portfolio_shadow/deterministic_accounting.py
  - adjusted price chain          : portfolio_research/repair_accounting_v1.py (certified)
  - PIT score source              : ui_score_research/ui_score_historical_pit_v2.parquet
Artifacts are written ONLY into portfolio_shadow_replay/.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\RFA\Company-Financial\portfolio_shadow")
sys.path.insert(0, r"D:\RFA\Company-Financial\portfolio_research")

import numpy as np
import pandas as pd
import psycopg

import shadow_common as sc
from deterministic_accounting import rebalance_accounts, assert_invariants
from repair_accounting_v1 import build_adj, price_at

ROOT = sc.ROOT
HERE = ROOT / "portfolio_shadow_replay"
STATE = sc.STATE_PATH
SPEC = ROOT / "portfolio_shadow" / "SHADOW_V1_1_SPEC.md"
SPEC_SHA = "f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e"
PANEL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet"
PANEL_SHA = "543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a"
IMAP = sc.IDENTITY_MAP
DAILY = ROOT / "research_bundle" / "daily_market_panel.parquet"
CERT_MONTHLY = ROOT / "portfolio_research" / "score_portfolio_v1_monthly_accounting_repaired.csv"
CERT_HOLDINGS = ROOT / "portfolio_research" / "score_portfolio_v1_holdings_accounting_repaired.parquet"
CERT_TRADES = ROOT / "portfolio_research" / "score_portfolio_v1_trades_accounting_repaired.parquet"
CERT_YEARLY = ROOT / "portfolio_research" / "score_portfolio_v1_yearly_accounting_repaired.csv"
FIXTURE_RUN = "e5998f6d-93ab-4577-b13a-7b2f89c39c02"   # state-marked test fixture; excluded from preview
SELECTION_PCT = 0.20
COST = sc.COST_RATE_BASE                                # 50 bps one-way, frozen BASE convention
TOL = 1e-9

R: dict = {"verification": {}, "calendar": {}, "tradability": {}, "engine": {}, "parity": {}}


def sha_file(p: Path) -> str:
    return sc.sha256_file(p)


def classify_flag(identity_status: str, rec_e: dict | None) -> str:
    """Path-A fill classification, mirroring observe_shadow_execution.classify_and_fill.
    The replay evaluates path-A cache evidence only; the path-B (DB) cross-check is a
    diagnostic in the live harness and is not needed for the fill decision."""
    if identity_status == "IDENTITY_ERROR":
        return "IDENTITY_ERROR"
    if rec_e is None:
        # session existed (E is a canonical >=30-breadth session); no path-A record
        return "SUSPENDED"
    vol = rec_e.get("qTotTran5J") or 0
    pclose = rec_e.get("pClosing")
    if pclose is None:
        return "INSUFFICIENT_LIQUIDITY_DATA" if vol > 0 else "NO_TRADE"
    if float(vol) <= 0:
        return "NO_TRADE"
    return "EXECUTABLE_REFERENCE"


def close_month(adj, caches, orders, holdings, cash, E, n_sel) -> dict:
    """Port of observe_shadow_execution.close_month (the harness month close)."""
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
        else:
            sym, _ins = meta.get(key, (None, None))
            rec = (caches.get(sym) or {}).get(E) or {} if sym else {}
            tradable[key] = bool(rec.get("qTotTran5J"))

    res = rebalance_accounts(cash, cur_vals, target_values, tradable, COST)
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
    assert abs(nav_post - (value_pre - cost)) <= TOL, "NAV identity violated at month close"

    tw = {o["portfolio_security_key"]: 1.0 / n_sel for o in orders if o["flag"] == "EXECUTABLE_REFERENCE"}
    n_failed = sum(1 for o in orders if o["flag"] != "EXECUTABLE_REFERENCE")
    target_cash_w = n_failed * (1.0 / n_sel if n_sel else 0.0)
    union = sorted(set(tw) | set(pre_w))
    turnover = 0.5 * (sum(abs(tw.get(s, 0.0) - pre_w.get(s, 0.0)) for s in union)
                      + abs(target_cash_w - pre_cash_w))
    rw = {k: v / nav_post for k, v in sorted(new_pos_vals.items())} if nav_post > 0 else {}
    w_sorted = sorted(rw.values(), reverse=True)
    return {"value_pre_trade": value_pre, "cash_pre": cash, "cash_post": cash_post,
            "post_holdings": post_holdings, "cost": cost, "buys": buys, "sells": sells,
            "buy_scale": buy_scale, "nav_post": nav_post, "turnover": turnover,
            "n_failed": n_failed,
            "holdings_count": sum(1 for v in new_pos_vals.values() if v > nav_post * 1e-9),
            "realized_traded_notional_fraction": (buys + sells) / value_pre if value_pre > 0 else 0.0,
            "transaction_cost_fraction": cost / value_pre if value_pre > 0 else 0.0,
            "top1_weight": w_sorted[0] if w_sorted else 0.0,
            "top5_weight": float(sum(w_sorted[:5])), "top10_weight": float(sum(w_sorted[:10])),
            "cur_vals": cur_vals, "target_values": target_values, "tradable": tradable,
            "realized_weights": rw, "meta": meta}


def trade_ledger(orders, close) -> list[dict]:
    """Realized trade rows at E, mirroring repair_accounting_v1.simulate's ledger,
    plus informational CARRY_HELD_SELECTED rows (notional 0)."""
    key2order = {o["portfolio_security_key"]: o for o in orders}
    meta = close["meta"]
    sym_of = lambda key: (key2order.get(key, {}).get("symbol")) or meta.get(key, (None, None))[0]
    held_nonexec = {o["portfolio_security_key"] for o in orders
                    if o["flag"] != "EXECUTABLE_REFERENCE" and o["portfolio_security_key"] in close["cur_vals"]}
    rows = []
    for key in sorted(close["target_values"]):
        o = key2order[key]
        d = close["target_values"][key] - close["cur_vals"].get(key, 0.0)
        if d > 0 and close["buy_scale"] < 1.0:
            d = close["buy_scale"] * d
        if abs(d) > TOL:
            rows.append({"symbol": o["symbol"], "portfolio_security_key": key,
                         "side": "BUY" if d > 0 else "SELL_REBAL", "notional": abs(d),
                         "cost": COST * abs(d)})
    for key in sorted(close["cur_vals"]):
        if key in close["target_values"]:
            continue
        cv = close["cur_vals"][key]
        if key in held_nonexec:
            rows.append({"symbol": sym_of(key), "portfolio_security_key": key,
                         "side": "CARRY_HELD_SELECTED", "notional": 0.0, "cost": 0.0})
        elif close["tradable"].get(key):
            rows.append({"symbol": sym_of(key), "portfolio_security_key": key,
                         "side": "SELL", "notional": cv, "cost": COST * cv})
        else:
            rows.append({"symbol": sym_of(key), "portfolio_security_key": key,
                         "side": "CARRY_HELD_UNSELECTED", "notional": 0.0, "cost": 0.0})
    for o in sorted(orders, key=lambda x: x["portfolio_security_key"] or ""):
        if o["flag"] != "EXECUTABLE_REFERENCE" and o["portfolio_security_key"] not in close["cur_vals"]:
            rows.append({"symbol": o["symbol"], "portfolio_security_key": o["portfolio_security_key"],
                         "side": "CASH_FAILED_TARGET", "notional": 0.0, "cost": 0.0})
    return rows


def main() -> int:
    # ---------- 0. live-state safety ----------
    state_sha_before = sha_file(STATE)
    state = json.loads(STATE.read_text(encoding="utf-8"))
    R["live_state_before"] = {"sha256": state_sha_before, "decisions": len(state["decisions"]),
                              "flags": state["flags"], "shadow_version": state["shadow_version"]}
    assert len(state["decisions"]) == 0, "live shadow has decisions; replay must not interfere"
    print("[0] live state read-only:", state_sha_before[:16], "decisions:", len(state["decisions"]))

    # ---------- 1. frozen-input verification ----------
    assert sha_file(SPEC) == SPEC_SHA, "active spec hash mismatch"
    assert sha_file(PANEL) == PANEL_SHA, "PIT panel hash mismatch"
    imap = pd.read_parquet(IMAP)
    assert len(imap) == 235 and (imap.mapping_status == "UNIQUE").all()
    assert imap.symbol.is_unique
    R["verification"] = {
        "spec_sha256": SPEC_SHA, "panel_sha256": PANEL_SHA,
        "imap_sha256": sha_file(IMAP),
        "cert_monthly_sha256": sha_file(CERT_MONTHLY),
        "cert_holdings_sha256": sha_file(CERT_HOLDINGS),
        "cert_trades_sha256": sha_file(CERT_TRADES),
        "imap_rows": 235, "imap_all_unique": True,
        "cost_rate_base": COST, "selection_pct": SELECTION_PCT,
    }
    print("[1] frozen inputs verified")

    # ---------- 2. PIT panel + certified identity mapping ----------
    panel = pd.read_parquet(PANEL, columns=[
        "as_of", "knowledge_cutoff", "symbol", "security_id", "ui_score", "data_quality_score",
        "growth_score", "profitability_score", "valuation_score", "market_score",
        "n_factors_missing"]).dropna(subset=["ui_score"])
    panel["as_of"] = panel["as_of"].astype(str).str[:10]
    imap_by_symbol = {r.symbol: r for r in imap.itertuples()}
    missing = sorted(set(panel.symbol.unique()) - set(imap_by_symbol))
    assert not missing, f"identity gap: {missing}"
    dates = sorted(panel.as_of.unique())
    assert len(dates) == 63, f"expected 63 decision dates, got {len(dates)}"
    groups: dict[str, list[dict]] = {}
    for T in dates:
        g = panel[panel.as_of == T]
        rows = []
        for r in g.itertuples():
            m = imap_by_symbol[r.symbol]
            rows.append({"symbol": r.symbol, "security_id": str(r.security_id),
                         "company_id": m.company_id, "ins_code": m.ins_code,
                         "key": f"{m.company_id}:{m.ins_code}",
                         "ui_score": float(r.ui_score),
                         "dq": None if pd.isna(r.data_quality_score) else float(r.data_quality_score),
                         "identity_status": "MAP_VERIFIED"})
        rows.sort(key=lambda x: (-x["ui_score"], x["symbol"], x["ins_code"]))
        for i, x in enumerate(rows, start=1):
            x["ui_rank"] = i
        kcs = set(g.knowledge_cutoff.astype(str))
        assert len(kcs) == 1, f"multiple knowledge_cutoffs at {T}: {kcs}"
        groups[T] = {"rows": rows, "knowledge_cutoff": next(iter(kcs))}
    R["panel"] = {"rows": int(len(panel)), "decision_dates": len(dates),
                  "first": dates[0], "last": dates[-1]}
    print(f"[2] panel loaded: {len(panel)} rows, {len(dates)} decision dates {dates[0]}..{dates[-1]}")

    # ---------- 3. calendars + price chain ----------
    adj, cal_cert = build_adj()
    with psycopg.connect(sc.DSN) as pg:
        cal_shadow = [d for d, _ in sc.shadow_calendar_rows(pg)]
    e_cert, e_shadow = {}, {}
    for T in dates:
        i = bisect_right(cal_cert, T)
        j = bisect_right(cal_shadow, T)
        e_cert[T] = cal_cert[i] if i < len(cal_cert) else None
        e_shadow[T] = cal_shadow[j] if j < len(cal_shadow) else None
    mism = [T for T in dates if e_cert[T] != e_shadow[T]]
    assert not mism and all(v for v in e_shadow.values()), f"execution-date mismatch: {mism}"
    R["calendar"] = {"rule": "first canonical trading date strictly after score date",
                     "shadow_calendar": "no Thu/Fri, breadth>=30 (spec V1.1 §4)",
                     "certified_calendar": "all distinct market.price_observations trade dates",
                     "exec_date_mismatches": 0,
                     "rederived_63_of_63_match": True}
    print("[3] calendars re-derived: 63/63 execution dates identical; price chain built")

    # ---------- 4. caches + tradability cross-check ----------
    syms = sorted(imap_by_symbol)
    sym2ins = {s: (imap_by_symbol[s].company_id, imap_by_symbol[s].ins_code) for s in syms}
    caches: dict[str, dict] = {}
    for s in syms:
        c, ins = sym2ins[s]
        caches[s] = sc.load_raw_cache(s, ins) or {}
    daily = pd.read_parquet(DAILY, columns=["date", "symbol", "security_traded"])
    daily["date"] = daily.date.astype(str).str[:10]
    dset = set(map(tuple, daily.loc[daily.security_traded == True, ["date", "symbol"]].values))
    need = {(E, s) for E in e_shadow.values() for s in syms}
    only_daily = only_cache = both = neither = 0
    for E, s in sorted(need):
        a = (E, s) in dset
        b = bool((caches.get(s) or {}).get(E, {}).get("qTotTran5J"))
        both += a and b
        only_daily += a and not b
        only_cache += b and not a
        neither += (not a) and (not b)
    assert only_daily == 0 and only_cache == 0, "tradability source disagreement"
    R["tradability"] = {"pairs_checked": int(len(need)), "both_traded": int(both),
                        "only_daily_panel": int(only_daily), "only_cache": int(only_cache),
                        "neither": int(neither),
                        "conclusion": "path-A cache evidence and certified daily-panel flag agree "
                                      "on every (E, symbol) pair needed by the replay"}
    del daily, dset
    print(f"[4] tradability cross-check: {len(need)} pairs, 0 disagreements")

    # ---------- 5. walk-forward monthly loop ----------
    port_state = {"cash": 1.0, "holdings": {}}
    bench_state = {"cash": 1.0, "holdings": {}}
    prev_selected: dict[str, dict] = {}
    prev_targets: dict[str, float] = {}
    monthly_rows, target_rows, trade_rows, holding_rows = [], [], [], []
    spells_open: dict[str, dict] = {}
    spells_closed: list[dict] = []
    key_meta: dict[str, dict] = {}
    nav_path, bench_nav_path = [1.0], [1.0]

    for k, T in enumerate(dates):
        month = T[:7]
        E = e_shadow[T]
        g = groups[T]
        rows, kc = g["rows"], g["knowledge_cutoff"]
        n_elig = len(rows)
        n_sel = max(1, int(SELECTION_PCT * n_elig))
        selected = rows[:n_sel]
        sel_keys = [r["key"] for r in selected]

        # decision-time valuation of the carried portfolio at T (harness build_decision semantics)
        cash = float(port_state["cash"])
        holdings = port_state["holdings"]
        decision_nav = cash
        holdings_decision = {}
        for key in sorted(holdings):
            h = holdings[key]
            p = price_at(adj, h["symbol"], T)
            exact = T in (caches.get(h["symbol"]) or {})
            val = h["shares"] * (p if p is not None else 0.0)
            decision_nav += val
            holdings_decision[key] = {"value_decision": val,
                                      "valued_at": T if exact else "carried_last_known"}

        orders = []
        for seq, r in enumerate(selected, start=1):
            key = r["key"]
            key_meta.setdefault(key, {"symbol": r["symbol"], "company_id": r["company_id"],
                                      "ins_code": r["ins_code"]})
            cur_val = holdings_decision.get(key, {}).get("value_decision", 0.0)
            expected = decision_nav / n_sel
            delta = expected - cur_val
            held = key in holdings
            if not held:
                action = "BUY"
            elif delta > decision_nav * TOL:
                action = "INCREASE"
            elif delta < -decision_nav * TOL:
                action = "DECREASE"
            else:
                action = "HOLD"
            rec = caches.get(r["symbol"]) or {}
            if T in rec and rec[T].get("pClosing") is not None:
                ref_price, ref_note = float(rec[T]["pClosing"]), "as_of_session_pClosing"
            else:
                earlier = [d for d in sorted(rec) if d <= T]
                ref_price, ref_note = ((float(rec[earlier[-1]]["pClosing"]), f"carried_from_{earlier[-1]}")
                                       if earlier else (None, "DATA_MISSING"))
            flag = classify_flag(r["identity_status"], rec.get(E))
            orders.append({"shadow_order_id": f"RPLY-{month.replace('-', '')}-{seq:03d}",
                           "portfolio_security_key": key, "company_id": r["company_id"],
                           "symbol": r["symbol"], "ins_code": r["ins_code"],
                           "security_id": r["security_id"], "identity_status": r["identity_status"],
                           "ui_score": r["ui_score"], "ui_rank": r["ui_rank"], "dq": r["dq"],
                           "paper_action": action, "flag": flag,
                           "trade_notional_fraction": abs(delta) / decision_nav if decision_nav else 0.0,
                           "expected_notional": expected, "cur_val_decision": cur_val,
                           "ref_price": ref_price, "ref_note": ref_note})
        flag_counts = {}
        for o in orders:
            flag_counts[o["flag"]] = flag_counts.get(o["flag"], 0) + 1

        close = close_month(adj, caches, orders, holdings, cash, E, n_sel)
        bench_orders = [{"portfolio_security_key": r["key"], "company_id": r["company_id"],
                         "symbol": r["symbol"], "ins_code": r["ins_code"],
                         "identity_status": r["identity_status"],
                         "flag": "EXECUTABLE_REFERENCE" if (caches.get(r["symbol"]) or {}).get(E, {}).get("qTotTran5J")
                                 else "DATA_MISSING"}
                        for r in rows]
        bench_close = close_month(adj, caches, bench_orders, bench_state["holdings"],
                                  float(bench_state["cash"]), E, len(bench_orders))

        # portfolio changes vs previous frozen targets
        cur_selected = {r["key"]: r for r in selected}
        entered = sorted(k for k in sel_keys if k not in prev_selected)
        exited = sorted(k for k in prev_selected if k not in cur_selected)
        retained = [k for k in sel_keys if k in prev_selected]
        act_counts = {}
        for o in orders:
            act_counts[o["paper_action"]] = act_counts.get(o["paper_action"], 0) + 1

        # five largest target-weight changes vs previous month's frozen targets
        wchg = []
        for key in sorted(set(prev_targets) | set(cur_selected)):
            new_w = 1.0 / n_sel if key in cur_selected else 0.0
            wchg.append((key, new_w - prev_targets.get(key, 0.0)))
        wchg.sort(key=lambda x: (-x[1], x[0]))
        top_incr = [(key_meta[k]["symbol"], round(d, 4)) for k, d in wchg[:5] if d > 0]
        top_decr = [(key_meta[k]["symbol"], round(d, 4)) for k, d in reversed(wchg[-5:]) if d < 0]

        # descriptive score movement among names eligible in both months
        score_diffs = []
        if prev_selected:
            prev_scores = {r["key"]: r["ui_score"] for r in groups[dates[k - 1]]["rows"]}
            for r in rows:
                if r["key"] in prev_scores:
                    score_diffs.append((r["symbol"], r["ui_score"] - prev_scores[r["key"]]))
            score_diffs.sort(key=lambda x: (-x[1], x[0]))
        movers_up = [(s, round(d, 4)) for s, d in score_diffs[:5] if d > 0]
        movers_dn = [(s, round(d, 4)) for s, d in reversed(score_diffs[-5:]) if d < 0]

        # holding spells (target membership per decision month)
        for r in rows:
            key = r["key"]
            if r["key"] in cur_selected:
                key_meta.setdefault(key, {"symbol": r["symbol"], "company_id": r["company_id"],
                                          "ins_code": r["ins_code"]})
                if key not in spells_open:
                    spells_open[key] = {"start": month, "months": 0, "ranks": []}
                spells_open[key]["months"] += 1
                spells_open[key]["ranks"].append(r["ui_rank"])
                age = spells_open[key]["months"] - 1
            elif key in spells_open:
                sp = spells_open.pop(key)
                spells_closed.append({"key": key, "start": sp["start"], "end": prev_month,
                                      "months": sp["months"], "open_ended": False})
                age = None
            else:
                age = None
            holding_rows.append({
                "decision_month": month, "decision_date": T, "exec_date": E,
                "symbol": r["symbol"], "company_id": r["company_id"], "ins_code": r["ins_code"],
                "portfolio_security_key": key, "ui_score": r["ui_score"], "ui_rank": r["ui_rank"],
                "data_quality": r["dq"], "selected": key in cur_selected,
                "target_weight": (1.0 / n_sel) if key in cur_selected else None,
                "action": next((o["paper_action"] for o in orders if o["portfolio_security_key"] == key), None),
                "execution_status": next((o["flag"] for o in orders if o["portfolio_security_key"] == key), None),
                "holding_age_months": age})
        prev_month = month

        # per-month target rows (row-level decision artifact, section 6)
        for o in orders:
            key = o["portfolio_security_key"]
            target_rows.append({
                "decision_month": month, "score_date": T, "knowledge_cutoff": kc,
                "execution_date": E, "eligible_universe_count": n_elig, "selected_count": n_sel,
                "shadow_order_id": o["shadow_order_id"], "symbol": o["symbol"],
                "company_id": o["company_id"], "ins_code": o["ins_code"],
                "security_id": o["security_id"], "ui_score": o["ui_score"], "ui_rank": o["ui_rank"],
                "data_quality": o["dq"], "target_weight": 1.0 / n_sel,
                "previous_weight": (holdings_decision.get(key, {}).get("value_decision", 0.0) / decision_nav
                                    if decision_nav else 0.0),
                "previous_target_weight": prev_targets.get(key, 0.0),
                "paper_action": o["paper_action"],
                "trade_notional_fraction": o["trade_notional_fraction"],
                "identity_status": o["identity_status"],
                "price_observable": T in (caches.get(o["symbol"]) or {}),
                "reference_price_raw_pClosing": o["ref_price"], "reference_price_note": o["ref_note"],
                "execution_status": o["flag"], "executable_at_exec": o["flag"] == "EXECUTABLE_REFERENCE"})
        month_trades = trade_ledger(orders, close)
        side_counts = {}
        for row in month_trades:
            side_counts[row["side"]] = side_counts.get(row["side"], 0) + 1
            row.update({"decision_month": month, "rebalance": k + 1, "score_date": T, "exec_date": E})
            trade_rows.append(row)

        monthly_rows.append({
            "rebalance": k + 1, "decision_month": month, "score_date": T,
            "knowledge_cutoff": kc, "exec_date": E,
            "n_eligible": n_elig, "n_selected": n_sel,
            "decision_nav": decision_nav,
            "value_pre_trade": close["value_pre_trade"], "transaction_cost": close["cost"],
            "value_post_trade": close["nav_post"],
            "cash_weight": close["cash_post"] / close["nav_post"] if close["nav_post"] else 0.0,
            "holdings_count": close["holdings_count"],
            "turnover": close["turnover"],
            "realized_traded_notional_fraction": close["realized_traded_notional_fraction"],
            "transaction_cost_fraction": close["transaction_cost_fraction"],
            "buy_notional": close["buys"], "sell_notional": close["sells"],
            "failed_targets": close["n_failed"], "buy_scale": close["buy_scale"],
            "order_flags": json.dumps(flag_counts, sort_keys=True),
            "actions_buy": act_counts.get("BUY", 0),
            "actions_hold": act_counts.get("HOLD", 0), "actions_increase": act_counts.get("INCREASE", 0),
            "actions_decrease": act_counts.get("DECREASE", 0),
            "exec_sells_exits": side_counts.get("SELL", 0),
            "exec_sell_rebal": side_counts.get("SELL_REBAL", 0),
            "exec_carry_held_unselected": side_counts.get("CARRY_HELD_UNSELECTED", 0),
            "exec_carry_held_selected": side_counts.get("CARRY_HELD_SELECTED", 0),
            "exec_cash_failed": side_counts.get("CASH_FAILED_TARGET", 0),
            "n_entered": len(entered), "n_exited": len(exited), "n_retained": len(retained),
            "entered_symbols": ",".join(key_meta[kk]["symbol"] for kk in entered),
            "exited_symbols": ",".join(key_meta[kk]["symbol"] for kk in exited),
            "top_holding_weight": close["top1_weight"], "top5_weight": close["top5_weight"],
            "top10_weight": close["top10_weight"],
            "bench_value_pre_trade": bench_close["value_pre_trade"],
            "bench_transaction_cost": bench_close["cost"],
            "bench_value_post_trade": bench_close["nav_post"],
            "bench_holdings_count": bench_close["holdings_count"],
            "bench_turnover": bench_close["turnover"],
            "bench_cash_weight": bench_close["cash_post"] / bench_close["nav_post"] if bench_close["nav_post"] else 0.0,
            "eligible_dq_mean": float(np.mean([r["dq"] for r in rows if r["dq"] is not None])),
            "eligible_score_std": float(np.std([r["ui_score"] for r in rows], ddof=1)),
            "eligible_score_p90_p10": float(np.percentile([r["ui_score"] for r in rows], 90)
                                            - np.percentile([r["ui_score"] for r in rows], 10)),
            "top_weight_increases": json.dumps(top_incr, ensure_ascii=False),
            "top_weight_decreases": json.dumps(top_decr, ensure_ascii=False),
            "score_movers_up": json.dumps(movers_up, ensure_ascii=False),
            "score_movers_down": json.dumps(movers_dn, ensure_ascii=False),
        })
        nav_path.append(close["nav_post"])
        bench_nav_path.append(bench_close["nav_post"])

        # exits that completed this month are recorded against the PREVIOUS decision month
        port_state = {"cash": close["cash_post"], "holdings": close["post_holdings"]}
        bench_state = {"cash": bench_close["cash_post"], "holdings": bench_close["post_holdings"]}
        prev_selected = cur_selected
        prev_targets = {o["portfolio_security_key"]: 1.0 / n_sel for o in orders}
        if k % 12 == 0 or k == len(dates) - 1:
            print(f"[5] {k + 1}/63 months replayed (through {month})")

    # close still-open spells at the end of history
    for key, sp in sorted(spells_open.items()):
        spells_closed.append({"key": key, "start": sp["start"], "end": dates[-1][:7],
                              "months": sp["months"], "open_ended": True})
    spells_open = {}

    # ---------- 6. returns, NAV, drawdown ----------
    n_periods = len(dates) - 1
    for k in range(n_periods):
        monthly_rows[k]["portfolio_return"] = nav_path[k + 2] / nav_path[k + 1] - 1.0
        monthly_rows[k]["benchmark_return"] = bench_nav_path[k + 2] / bench_nav_path[k + 1] - 1.0
        monthly_rows[k]["excess_return"] = (monthly_rows[k]["portfolio_return"]
                                            - monthly_rows[k]["benchmark_return"])
    monthly_rows[-1]["portfolio_return"] = None
    monthly_rows[-1]["benchmark_return"] = None
    monthly_rows[-1]["excess_return"] = None

    def dd_series(path):
        peak, out = path[0], []
        for v in path:
            peak = max(peak, v)
            out.append(v / peak - 1.0)
        return out

    port_dd, bench_dd = dd_series(nav_path), dd_series(bench_nav_path)
    for k in range(len(dates)):
        monthly_rows[k]["portfolio_nav"] = nav_path[k + 1]
        monthly_rows[k]["benchmark_nav"] = bench_nav_path[k + 1]
        monthly_rows[k]["portfolio_drawdown"] = port_dd[k + 1]
        monthly_rows[k]["benchmark_drawdown"] = bench_dd[k + 1]

    rets = np.array([r["portfolio_return"] for r in monthly_rows[:-1]])
    brets = np.array([r["benchmark_return"] for r in monthly_rows[:-1]])
    entry = nav_path[1]
    w_path = np.concatenate([[entry], entry * np.cumprod(1 + rets)])
    peak = np.maximum.accumulate(np.concatenate([[1.0], w_path]))
    summary = {
        "label": "HISTORICAL_REPLAY_ONLY (TOP20 BASE)",
        "n_decision_months": 63, "n_return_periods": int(n_periods),
        "terminal_wealth_multiple": float(w_path[-1]),
        "benchmark_terminal_wealth_multiple": float(np.concatenate(
            [[bench_nav_path[1]], bench_nav_path[1] * np.cumprod(1 + brets)])[-1]),
        "annualized_return": float(w_path[-1] ** (12 / n_periods) - 1),
        "annualized_volatility": float(np.std(rets, ddof=1) * np.sqrt(12)),
        "max_drawdown": float((np.concatenate([[1.0], w_path]) / np.maximum.accumulate(
            np.concatenate([[1.0], w_path])) - 1).min()),
        "sharpe_0rf": float(np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(12)),
        "avg_turnover": float(np.mean([r["turnover"] for r in monthly_rows])),
        "median_turnover": float(np.median([r["turnover"] for r in monthly_rows])),
        "avg_holdings": float(np.mean([r["holdings_count"] for r in monthly_rows])),
        "median_holdings": float(np.median([r["holdings_count"] for r in monthly_rows])),
        "avg_cash_pct": float(np.mean([r["cash_weight"] for r in monthly_rows]) * 100),
        "avg_excess_monthly": float(np.mean(rets - brets)),
        "positive_excess_fraction": float(np.mean(rets - brets > 0)),
        "unique_securities_ever_selected": len({r["portfolio_security_key"] for r in holding_rows if r["selected"]}),
    }
    R["engine"] = {"summary": summary, "conventions": {
        "returns": "NAV_post(E_k) -> NAV_post(E_k+1) (certified repaired convention; identical "
                   "to the live shadow perf block), entry rebalance cost included in NAV_post(0)",
        "costs": "50 bps one-way BASE, paid from portfolio cash, buys scale proportionally "
                 "when cash+sells cannot cover buys+costs",
        "return_semantics": "PRICE_PLUS_MECHANICAL_ADJUSTMENTS (CONFIRMED gap-rule chain; no dividends)"}}
    print(f"[6] wealth multiple {w_path[-1]:.4f} | bench "
          f"{summary['benchmark_terminal_wealth_multiple']:.4f} | MDD {summary['max_drawdown']:.2%}")

    # ---------- 7. parity vs certified SCORE_PORTFOLIO_V1 (accounting repaired) ----------
    cert = pd.read_csv(CERT_MONTHLY)
    certh = pd.read_parquet(CERT_HOLDINGS)
    float_fields = {"value_pre_trade": "value_pre_trade", "transaction_cost": "transaction_cost",
                    "value_post_trade": "value_post_trade", "cash_weight": "cash_weight",
                    "turnover": "turnover", "buy_notional": "buy_notional",
                    "sell_notional": "sell_notional", "buy_scale": "buy_scale",
                    "transaction_cost_fraction": "transaction_cost_fraction",
                    "absolute_traded_notional_fraction": "realized_traded_notional_fraction",
                    "holdings_count": "holdings_count", "failed_targets": "failed_targets"}
    par = {"months_compared": 0, "exec_date_mismatches": [], "n_eligible_mismatches": [],
           "n_selected_mismatches": [], "selection_set_mismatches": [],
           "float_field_mismatches": {}, "return_mismatches": [], "trade_notional_mismatches": [],
           "max_abs_diff_by_field": {}, "examples": {}}
    par = {"months_compared": 0, "exec_date_mismatches": [], "n_eligible_mismatches": [],
           "n_selected_mismatches": [], "selection_set_mismatches": [],
           "float_field_mismatches": {}, "return_mismatches": [], "trade_notional_mismatches": [],
           "max_abs_diff_by_field": {}}
    for k in range(63):
        i = k + 1
        c = cert.iloc[k]
        m = monthly_rows[k]
        par["months_compared"] += 1
        if c.exec_date != m["exec_date"]:
            par["exec_date_mismatches"].append({"rebalance": i, "cert": c.exec_date, "replay": m["exec_date"]})
        if int(c.n_eligible) != m["n_eligible"]:
            par["n_eligible_mismatches"].append({"rebalance": i})
        if int(c.n_selected) != m["n_selected"]:
            par["n_selected_mismatches"].append({"rebalance": i})
        cert_sel = set(certh[certh.rebalance == i].symbol)
        my_sel = {o["symbol"] for o in groups[dates[k]]["rows"][:m["n_selected"]]}
        if cert_sel != my_sel:
            par["selection_set_mismatches"].append({
                "rebalance": i, "only_cert": sorted(cert_sel - my_sel)[:10],
                "only_replay": sorted(my_sel - cert_sel)[:10]})
        for cf, mf in float_fields.items():
            if cf not in c.index:
                continue
            d = abs(float(c[cf]) - float(m[mf]))
            par["max_abs_diff_by_field"][cf] = max(par["max_abs_diff_by_field"].get(cf, 0.0), d)
            if d > TOL:
                par["float_field_mismatches"].setdefault(cf, []).append({"rebalance": i, "abs_diff": d})
        if pd.notna(c.top20_return) and m["portfolio_return"] is not None:
            d = abs(float(c.top20_return) - m["portfolio_return"])
            par["max_abs_diff_by_field"]["top20_return"] = max(par["max_abs_diff_by_field"].get("top20_return", 0.0), d)
            if d > TOL:
                par["return_mismatches"].append({"rebalance": i, "field": "top20_return", "abs_diff": d})
        if pd.notna(c.bench_return) and m["benchmark_return"] is not None:
            d = abs(float(c.bench_return) - m["benchmark_return"])
            par["max_abs_diff_by_field"]["bench_return"] = max(par["max_abs_diff_by_field"].get("bench_return", 0.0), d)
            if d > TOL:
                par["return_mismatches"].append({"rebalance": i, "field": "bench_return", "abs_diff": d})
    cert_tr = pd.read_parquet(CERT_TRADES)
    cert_tr_agg = cert_tr[cert_tr.side.isin(["BUY", "SELL", "SELL_REBAL"])].groupby(
        ["rebalance", "symbol", "side"])["notional"].sum()
    my_tr = pd.DataFrame(trade_rows)
    my_tr_agg = my_tr[my_tr.side.isin(["BUY", "SELL", "SELL_REBAL"])].groupby(
        ["rebalance", "symbol", "side"])["notional"].sum()
    common = pd.DataFrame({"a": my_tr_agg, "b": cert_tr_agg}).dropna()
    dmax = float((common.a - common.b).abs().max()) if len(common) else 0.0
    par["max_abs_diff_by_field"]["trade_notional"] = dmax
    par["trade_notional_pairs_compared"] = int(len(common))
    if dmax > TOL:
        par["trade_notional_mismatches"].append({"max_abs_diff": dmax})
    mismatch_cats = ["exec_date_mismatches", "n_eligible_mismatches", "n_selected_mismatches",
                     "selection_set_mismatches", "return_mismatches", "trade_notional_mismatches"]
    par["any_mismatch"] = bool(any(par[c_] for c_ in mismatch_cats)
                               or any(v for v in par["float_field_mismatches"].values()))
    par["SHADOW_REPLAY_PORTFOLIO_PARITY"] = "FAIL" if par["any_mismatch"] else "PASS"
    par["tolerance"] = TOL
    par["note"] = ("engine = live shadow harness semantics (deterministic sorted port); baseline = "
                   "SCORE_PORTFOLIO_V1 accounting-repaired certified artifacts")
    R["parity"] = par
    print(f"[7] parity: {par['SHADOW_REPLAY_PORTFOLIO_PARITY']} "
          f"(max diffs: {json.dumps({k: f'{v:.2e}' for k, v in par['max_abs_diff_by_field'].items()})})")

    # ---------- 8. artifacts ----------
    HERE.mkdir(exist_ok=True)
    md = pd.DataFrame(monthly_rows)
    md.to_csv(HERE / "shadow_replay_monthly.csv", index=False)
    tdf = pd.DataFrame(target_rows).sort_values(["decision_month", "shadow_order_id"])
    tdf.to_parquet(HERE / "shadow_replay_targets.parquet", compression="zstd", index=False)
    ttr = pd.DataFrame(trade_rows).sort_values(["rebalance", "symbol", "side"])
    ttr.to_parquet(HERE / "shadow_replay_trades.parquet", compression="zstd", index=False)
    hdf = pd.DataFrame(holding_rows).sort_values(["decision_date", "ui_rank"])
    hdf.to_csv(HERE / "security_holding_history.csv", index=False)

    # spells / durations
    spell_rows = []
    for sp in spells_closed:
        km = key_meta[sp["key"]]
        spell_rows.append({"symbol": km["symbol"], "company_id": km["company_id"],
                           "portfolio_security_key": sp["key"], "first_entry_month": sp["start"],
                           "last_exit_month": sp["end"], "months_in_spell": sp["months"],
                           "open_ended": sp["open_ended"]})
    sp_df = pd.DataFrame(spell_rows)
    all_spells = sp_df.months_in_spell.values if len(sp_df) else np.array([0])
    per_sec = []
    for key in sorted({r["portfolio_security_key"] for r in holding_rows if r["selected"]}):
        km = key_meta[key]
        ss = sp_df[sp_df.portfolio_security_key == key]
        ranks = [r["ui_rank"] for r in holding_rows if r["portfolio_security_key"] == key and r["selected"]]
        per_sec.append({"symbol": km["symbol"], "company_id": km["company_id"],
                        "first_entry_date": ss.sort_values("first_entry_month").iloc[0]["first_entry_month"],
                        "last_exit_date": ss.sort_values("last_exit_month").iloc[-1]["last_exit_month"],
                        "n_spells": int(len(ss)), "total_months_held": int(ss.months_in_spell.sum()),
                        "avg_rank_while_held": float(np.mean(ranks)),
                        "currently_held_at_replay_end": bool(ss.open_ended.any())})
    sec_df = pd.DataFrame(per_sec).sort_values("symbol")
    duration_stats = {
        "n_spells_total": int(len(sp_df)),
        "spell_length_median": float(np.median(all_spells)),
        "spell_length_p25": float(np.percentile(all_spells, 25)),
        "spell_length_p75": float(np.percentile(all_spells, 75)),
        "spell_length_p90": float(np.percentile(all_spells, 90)),
        "spell_length_mean": float(np.mean(all_spells)),
        "spell_length_max": int(all_spells.max()),
    }

    # concentration / recurrence / yearly / era
    rec = hdf[hdf.selected].groupby("symbol").agg(
        months_in_top20=("decision_month", "nunique"),
        avg_rank=("ui_rank", "mean")).sort_values(["months_in_top20", "avg_rank"], ascending=[False, True])
    streaks = []
    for sym, gsym in hdf[hdf.selected].sort_values("decision_date").groupby("symbol"):
        months = sorted(gsym.decision_month.unique())
        best = cur = 1
        for a, b in zip(months, months[1:]):
            y1, m1 = map(int, a.split("-")); y2, m2 = map(int, b.split("-"))
            nxt = (m1 == 12 and (y2, m2) == (y1 + 1, 1)) or (m2 == m1 + 1)
            cur = cur + 1 if nxt else 1
            best = max(best, cur)
        streaks.append({"symbol": sym, "longest_uninterrupted_streak": best,
                        "months_in_top20": len(months)})
    streak_df = pd.DataFrame(streaks).sort_values(["longest_uninterrupted_streak", "months_in_top20"],
                                                  ascending=[False, False])
    singles = rec[rec.months_in_top20 == 1]
    n_spells_sym = sp_df.groupby("symbol").size()
    churners = n_spells_sym[n_spells_sym >= 4].sort_values(ascending=False)

    yearly_rows = []
    for y in ["2021", "2022", "2023", "2024", "2025", "2026"]:
        mr = [r for r in monthly_rows if r["exec_date"][:4] == y]
        rr = [r["portfolio_return"] for r in mr if r["portfolio_return"] is not None]
        bb = [r["benchmark_return"] for r in mr if r["benchmark_return"] is not None]
        prev_rows = [r for r in monthly_rows if r["exec_date"][:4] < y]
        start_h = prev_rows[-1]["holdings_count"] if prev_rows else 0
        if rr:
            w0 = (prev_rows[-1]["value_post_trade"] if prev_rows else 1.0)
            navs = [w0] + [r["portfolio_nav"] for r in mr]
            peak = np.maximum.accumulate(navs)
            mdd = float((np.array(navs) / peak - 1).min())
            py = float(np.prod(1 + np.array(rr)) - 1)
            by = float(np.prod(1 + np.array(bb)) - 1)
            freq = hdf[(hdf.selected) & (hdf.decision_date.str[:4] == y)].symbol.value_counts()
            yearly_rows.append({
                "year": y, "rebalances": len(mr), "starting_holdings": int(start_h),
                "ending_holdings": int(mr[-1]["holdings_count"]),
                "avg_holdings": float(np.mean([r["holdings_count"] for r in mr])),
                "avg_turnover": float(np.mean([r["turnover"] for r in mr])),
                "portfolio_return": py, "benchmark_return": by, "excess_return": py - by,
                "max_drawdown": mdd, "best_month": float(np.max(rr)), "worst_month": float(np.min(rr)),
                "top10_most_frequently_held": "; ".join(freq.head(10).index)})
        else:
            yearly_rows.append({"year": y, "rebalances": len(mr), "starting_holdings": int(start_h),
                                "ending_holdings": int(mr[-1]["holdings_count"]),
                                "avg_holdings": float(np.mean([r["holdings_count"] for r in mr])),
                                "avg_turnover": float(np.mean([r["turnover"] for r in mr])),
                                "portfolio_return": None, "benchmark_return": None,
                                "excess_return": None, "max_drawdown": None, "best_month": None,
                                "worst_month": None, "top10_most_frequently_held": ""})
    ydf = pd.DataFrame(yearly_rows)
    ydf.to_csv(HERE / "shadow_replay_yearly.csv", index=False)

    era = {}
    for label, yrs in [("2021-2023", ["2021", "2022", "2023"]), ("2024-2026", ["2024", "2025", "2026"])]:
        sel = [r for r in monthly_rows if r["decision_month"][:4] in yrs]
        era[label] = {
            "decision_months": len(sel),
            "median_eligible_universe": float(np.median([r["n_eligible"] for r in sel])),
            "median_selected": float(np.median([r["n_selected"] for r in sel])),
            "mean_eligible_dq": float(np.mean([r["eligible_dq_mean"] for r in sel])),
            "median_score_std": float(np.median([r["eligible_score_std"] for r in sel])),
            "median_score_p90_p10": float(np.median([r["eligible_score_p90_p10"] for r in sel])),
            "avg_target_turnover": float(np.mean([r["turnover"] for r in sel])),
            "avg_realized_traded_fraction": float(np.mean([r["realized_traded_notional_fraction"] for r in sel])),
            "avg_holdings": float(np.mean([r["holdings_count"] for r in sel])),
            "avg_monthly_retention_fraction": float(np.mean(
                [r["n_retained"] / r["n_selected"] for r in sel[1:]])) if len(sel) > 1 else None,
        }
    R["era_comparison"] = {"purpose": "descriptive only — no tuning, no strategy change",
                           **era}

    # ---------- 9. NON_SHADOW_CURRENT_PREVIEW ----------
    import build_shadow_portfolio as bsp
    preview_info = None
    try:
        bsp.verify_active_spec(state)
        with psycopg.connect(sc.DSN) as pg, pg.cursor() as cur:
            cur.execute("""SELECT id::text, as_of_date::text, source_cutoff_at, completed_at, code_version
                           FROM analytics.score_runs
                           WHERE status='completed' AND score_version='canonical-v1-dev'
                             AND id <> %s
                           ORDER BY completed_at DESC LIMIT 1""", (FIXTURE_RUN,))
            rid, as_of, cutoff, completed, code_version = cur.fetchone()
        snap = bsp.load_snapshot_from_db(rid)
        cal_for_preview = cal_shadow
        dec = bsp.build_decision(snap, {"holdings": {}, "cash": 1.0}, adj, cal_for_preview)
        by_key = {r["company_id"]: r for r in snap["rows"]}
        prow = []
        for o in dec["orders"]:
            src = by_key[o["company_id"]]
            prow.append({"symbol": o["symbol"], "company_id": o["company_id"],
                         "ins_code": o["ins_code"], "ui_score": o["ui_score"],
                         "ui_rank": o["ui_rank"],
                         "data_quality_score": src["data_quality_score"],
                         "target_weight": o["target_weight"],
                         "identity_status": o["identity_status"]})
        pdf = pd.DataFrame(prow)
        pdf.to_csv(HERE / "current_nonshadow_preview.csv", index=False)
        preview_info = {"label": "NON_SHADOW_CURRENT_PREVIEW",
                        "run_id": rid, "as_of_date": as_of,
                        "source_cutoff_at": cutoff.isoformat() if cutoff else None,
                        "completed_at": completed.isoformat() if completed else None,
                        "code_version": code_version,
                        "eligible_universe_count": dec["n_eligible"],
                        "selected_count": dec["n_selected"],
                        "note": "not a frozen month-end shadow decision; no paper orders; "
                                "clock NOT started; state untouched",
                        "excluded_fixture_run": FIXTURE_RUN}
        print(f"[9] preview: run {rid[:8]} as_of {as_of}: eligible {dec['n_eligible']}, top20% {dec['n_selected']}")
    except Exception as exc:                                   # noqa: BLE001 — preview is optional
        preview_info = {"label": "NON_SHADOW_CURRENT_PREVIEW", "error": repr(exc)}
        print("[9] preview failed (non-fatal):", repr(exc))
    R["preview"] = preview_info

    # ---------- 10. finalize ----------
    state_sha_after = sha_file(STATE)
    assert state_sha_after == state_sha_before, "LIVE STATE WAS MODIFIED — abort"
    R["live_state_after"] = {"sha256": state_sha_after, "byte_identical": True}
    R["determinism_probe"] = {
        "monthly_csv_sha256": sc.sha256_file(HERE / "shadow_replay_monthly.csv"),
        "targets_content_sha256": sc.canonical_content_hash(target_rows),
        "trades_content_sha256": sc.canonical_content_hash(trade_rows),
        "note": "re-run with a different PYTHONHASHSEED must reproduce these hashes"}
    R["duration"] = duration_stats
    R["holdings_per_security"] = len(sec_df)
    R["recurrence"] = {
        "top15_by_months_in_top20": [{"symbol": s, "months": int(m), "avg_rank": float(a)}
                                     for s, m, a in rec.head(15).itertuples(name=None)],
        "top10_longest_streaks": streak_df.head(10).to_dict("records"),
        "n_entered_only_once": int(len(singles)),
        "symbols_entered_only_once": sorted(singles.index.tolist()),
        "n_churners_4plus_spells": int(len(churners)),
        "churners": {s: int(v) for s, v in churners.items()},
    }
    (HERE / "replay_state.json").write_bytes(
        sc.canonical_json(R).encode("utf-8") + b"\n")

    np.save(HERE / "_nav_path.npy", np.array(nav_path))
    np.save(HERE / "_bench_nav_path.npy", np.array(bench_nav_path))
    md.to_pickle(HERE / "_monthly_rows.pkl")
    hdf.to_pickle(HERE / "_holding_rows.pkl")
    sp_df.to_pickle(HERE / "_spells.pkl")
    ydf.to_pickle(HERE / "_yearly.pkl")
    pd.DataFrame(era).to_pickle(HERE / "_era.pkl")
    with open(HERE / "_preview_info.json", "w", encoding="utf-8") as fh:
        json.dump(preview_info, fh, ensure_ascii=False, indent=1, default=str)
    print("[10] artifacts written; live state byte-identical:",
          state_sha_after == state_sha_before)
    print("SUMMARY:", json.dumps({"summary": summary, "parity": par["SHADOW_REPLAY_PORTFOLIO_PARITY"],
                                  "duration": duration_stats}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
