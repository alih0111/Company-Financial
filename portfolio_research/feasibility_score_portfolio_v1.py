"""SCORE PORTFOLIO V1 — PRE-OUTCOME FEASIBILITY (task section 26). No returns, no performance.

Mechanics frozen for the feasibility measurement (identical rules go into the
preregistration):
  selection   : per score date T, eligible = scored rows; sort by (ui_score DESC, symbol ASC);
                Top20 n = max(1, floor(0.20*N)), Top10 n = max(1, floor(0.10*N))
  execution   : EXECUTION_DATE = first canonical trading date strictly AFTER T
  tradability : selected security tradable on EXECUTION_DATE iff the canonical daily panel
                has a row AND security_traded == True (zero-trade/unknown = NOT executable)
  cash        : failed weight stays cash (weight NOT redistributed)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import psycopg

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "portfolio_research"
HERE.mkdir(exist_ok=True)
PANEL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet"
DAILY = ROOT / "research_bundle" / "daily_market_panel.parquet"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"

R = {"rebalance_dates": {}, "selection": {}, "tradability": {}, "coverage": {},
     "semantics": {}, "gates_precheck": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    panel = pd.read_parquet(PANEL, columns=["as_of", "knowledge_cutoff", "security_id",
                                            "symbol", "ui_score"])
    panel = panel.dropna(subset=["ui_score"])
    daily = pd.read_parquet(DAILY, columns=["date", "security_id", "symbol", "security_traded"])
    daily["date"] = daily.date.astype(str).str[:10]
    # IDENTITY KEY: the daily panel is keyed by the research-symbol mapping, and the score
    # panel's security_id (is_primary) does NOT match it for the same symbol; the canonical
    # execution identity for SCORE PORTFOLIO V1 is therefore the SYMBOL (the same key used
    # by every return pipeline in this project: raw_{symbol}_{ins_code} caches).
    tradable_keys = set(map(tuple, daily.loc[daily.security_traded == True, ["date", "symbol"]].values))
    daily_symbols = set(daily.symbol.unique())

    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]

    dates = sorted(panel.as_of.unique())
    R["rebalance_dates"] = {"n": len(dates), "first": dates[0], "last": dates[-1]}
    rows = []
    for T in dates:
        g = panel[panel.as_of == T]
        n_elig = len(g)
        n20 = max(1, int(np.floor(0.20 * n_elig)))
        n10 = max(1, int(np.floor(0.10 * n_elig)))
        gs = g.sort_values(["ui_score", "symbol"], ascending=[False, True])
        i = bisect_right(cal, str(T)[:10])
        exec_date = cal[i] if i < len(cal) else None
        sel20 = gs.head(n20)
        sel10 = gs.head(n10)

        def failed(sel):
            if exec_date is None:
                return len(sel)
            return sum(1 for r in sel.itertuples()
                       if (exec_date, r.symbol) not in tradable_keys)
        f20, f10 = failed(sel20), failed(sel10)
        rows.append({
            "score_date": str(T)[:10], "exec_date": exec_date, "n_eligible": n_elig,
            "n20": n20, "n10": n10,
            "failed20": f20, "cash20_pct": round(100 * f20 / n20, 2),
            "failed10": f10, "cash10_pct": round(100 * f10 / n10, 2),
        })
    fb = pd.DataFrame(rows)
    fb.to_csv(HERE / "score_portfolio_v1_feasibility_by_date.csv", index=False)
    R["selection"] = {
        "eligible_per_date_median": int(fb.n_eligible.median()),
        "eligible_per_date_min": int(fb.n_eligible.min()),
        "eligible_per_date_max": int(fb.n_eligible.max()),
        "top20_holdings_median": int(fb.n20.median()),
        "top20_holdings_min": int(fb.n20.min()),
        "top20_holdings_max": int(fb.n20.max()),
        "top10_holdings_median": int(fb.n10.median()),
        "top10_holdings_min": int(fb.n10.min()),
        "tie_break_rule": "(ui_score DESC, symbol ASC); n = max(1, floor(pct*N))",
    }
    R["tradability"] = {
        "exec_dates_resolvable": int(fb.exec_date.notna().sum()),
        "top20_failed_median": float(fb.failed20.median()),
        "top20_failed_mean": round(float(fb.failed20.mean()), 2),
        "top20_cash_pct_mean": round(float(fb.cash20_pct.mean()), 2),
        "top20_cash_pct_max": round(float(fb.cash20_pct.max()), 2),
        "top10_failed_mean": round(float(fb.failed10.mean()), 2),
        "top10_cash_pct_mean": round(float(fb.cash10_pct.mean()), 2),
        "dates_with_top20_failure": int((fb.failed20 > 0).sum()),
        "rule": "tradable iff daily-panel row exists AND security_traded == True; failed weight stays cash",
    }
    by_year = fb.assign(year=fb.score_date.str[:4]).groupby("year").agg(
        dates=("score_date", "size"), med_elig=("n_eligible", "median"),
        med_n20=("n20", "median"), med_cash20=("cash20_pct", "median"))
    R["coverage"] = {
        "panel_rows": int(len(panel)), "panel_symbols": int(panel.symbol.nunique()),
        "daily_panel_symbols": int(daily_symbols.__len__()),
        "scored_symbols_in_daily_panel": int(len(set(panel.symbol.unique()) & daily_symbols)),
        "identity_key": "symbol (score-panel is_primary security_id does not match the daily "
                        "panel's research-symbol security_id for the same symbol)",
        "by_year": {str(k): {kk: (int(vv) if kk in ("dates", "med_elig", "med_n20") else round(float(vv), 2))
                             for kk, vv in v.items()} for k, v in by_year.to_dict("index").items()},
    }
    R["semantics"] = {
        "PORTFOLIO_RETURN_SEMANTICS": "PRICE_PLUS_MECHANICAL_ADJUSTMENTS",
        "basis": ("canonical adjusted chain = pClosing x CONFIRMED tsetmc_gap_rule_v1 factors; "
                  "corporate actions covered: capital_increase 384, rights_issue 480, "
                  "reverse_split 30, other heuristic gaps 6,119"),
        "cash_dividends": "NOT captured (no dividend adjustment source exists)",
        "terminology": "annualized/cumulative figures are price-plus-mechanical-adjustment returns; "
                       "'total shareholder return' is NOT a permitted label",
    }
    R["gates_precheck"] = {
        "PV7_median_holdings_ge20_top20": bool(fb.n20.median() >= 20),
        "PV8_expected_involuntary_cash_le10pct_top20": bool(fb.cash20_pct.mean() <= 10),
        "note": "pre-checks only; PV1-PV8 are formally evaluated at execution",
    }
    feasible = (R["gates_precheck"]["PV7_median_holdings_ge20_top20"]
                and R["gates_precheck"]["PV8_expected_involuntary_cash_le10pct_top20"]
                and R["rebalance_dates"]["n"] >= 24
                and int(fb.exec_date.notna().sum()) == len(fb))
    R["PORTFOLIO_V1_FEASIBLE"] = "YES" if feasible else "NO"
    R["artifacts"] = {
        "score_panel": str(PANEL), "score_panel_sha256": sha256(PANEL),
        "daily_panel": str(DAILY), "daily_panel_sha256": sha256(DAILY),
        "feasibility_script_sha256": sha256(Path(__file__).resolve()),
    }
    (HERE / "score_portfolio_v1_feasibility.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in R.items() if k != "coverage"}, indent=1, default=str))
    print("coverage by year:", json.dumps(R["coverage"]["by_year"], default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
