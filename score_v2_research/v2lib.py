"""SCORE V2 research shared library.

Implements the FROZEN protocol (SCORE_V2_RESEARCH_PROTOCOL.md SHA c4bc1998...):
- certified PIT panel loading (parquet + JSONL ranks),
- raw TSETMC market data + CONFIRMED tsetmc_gap_rule_v1 causal adjustment chain,
- forward returns under the frozen audit convention,
- pre-registered fundamental / technical / Ichimoku feature families,
- cross-sectional midrank transform, IC machinery, frozen split,
- certified portfolio simulation via repair_accounting_v1.

RESEARCH ONLY. Does not modify any certified artifact.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import sys
import os
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "score_v2_research"
PANEL_PQ = ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet"
PANEL_JSONL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2" / "ui_score_historical_pit_v2.jsonl"
IMAP = ROOT / "portfolio_research" / "portfolio_identity_map.parquet"
DAILY = ROOT / "research_bundle" / "daily_market_panel.parquet"
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
REPAIR = ROOT / "portfolio_research" / "repair_accounting_v1.py"
CACHE = HERE / "_cache"

DSN = os.environ.get("CDF_RESEARCH_DSN", "")
HORIZONS = (21, 63, 126, 252)
SEED, B = 20261003, 2000
BOOT_BLOCK_MONTHS_PORTFOLIO = 6  # frozen: 6 monthly return observations (asserted in code)

PROTO_SHA = "c4bc1998067925e64c8bc772d0e279106626d50698a91a0632ee6573102e2816"
SHA_PANEL_PQ = "543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a"
SHA_PANEL_JSONL = "6e1a96484f3018a67c136d19f5af76d36b88c15181f6e855fc04b829aa839bbe"
SHA_IMAP = "eaea81523a11c09b864aca37e625f8efd4c03fd108f714c391d3d4a576e8b10a"
SHA_DAILY = "c94c19f55c72e416d1cbb1fe173a71ed5ecf803e1ad17b5a269d6839ed88db4d"
SHA_REPAIR = "3c63b887632f5fb2f8216ada4fac5309f0478f3a87ef621d978ac59ad1efa2af"

FROZEN_V1_IC = {21: 0.0574, 63: 0.0853, 126: 0.1096, 252: 0.1031}
FROZEN_V1_POS = {21: 0.73, 63: 0.79, 126: 0.90, 252: 0.82}
FROZEN_V1_PORT = {"top20_cagr": 0.3979, "bench_cagr": 0.3247, "excess_pp": 7.32,
                  "top20_mdd": -0.2685, "avg_turnover": 0.2931}

DEV_END, VAL_START, VAL_END, HOLD_START = "2024-06-30", "2024-07-01", "2024-12-31", "2025-01-01"

sys.path.insert(0, str(ROOT / "model_v2_validation"))
import model_v2 as M  # frozen spearman  # noqa: E402

V1_COMPONENTS = {
    "SalesGrowthRank": ("sales_growth_12m", 10, "Growth"),
    "SalesGrowth3MRank": ("sales_growth_3m", 6, "Growth"),
    "RevenueGrowthRank": ("revenue_growth", 5, "Growth"),
    "OperatingProfitGrowthRank": ("operating_profit_growth", 5, "Growth"),
    "NetProfitGrowthRank": ("net_profit_growth|eps_growth", 10, "Growth"),
    "OperatingMarginRank": ("operating_margin", 4, "Profitability"),
    "NetMarginRank": ("net_margin", 4, "Profitability"),
    "ROERank": ("roe", 6, "Profitability"),
    "MarginTrendRank": ("margin_trend", 3, "Profitability"),
    "InterestCoverageRank": ("interest_coverage", 3, "Profitability"),
    "CashConversionRank": ("cash_conversion", 2, "Profitability"),
    "EarningsQualityRank": ("earnings_quality", 4, "Profitability"),
    "PERank": ("pe", 11, "Valuation"),
    "PSRank": ("ps", 3, "Valuation"),
    "PBRank": ("pb", 2, "Valuation"),
    "LiquidityRank": ("avg_trade_value_30d", 3, "MarketRisk"),
    "LeverageRank": ("debt_ratio", 2, "MarketRisk"),
    "CurrentRatioRank": ("current_ratio", 2, "MarketRisk"),
    "StabilityRank": ("sales_stability", 1, "MarketRisk"),
    "LowVolatilityRank": ("volatility_30d", 2, "MarketRisk"),
    "MomentumRank": ("price_momentum_30d", 1, "MarketRisk"),
}

NEW_FUNDAMENTALS = {  # id -> (column, direction higher_better, category)
    "sales_growth_accel": ("f_sales_growth_accel", True, "Growth"),
    "profit_growth_accel": ("f_profit_growth_accel", True, "Growth"),
    "operating_margin_delta": ("f_operating_margin_delta", True, "Profitability"),
    "net_margin_delta": ("f_net_margin_delta", True, "Profitability"),
    "roe_delta": ("f_roe_delta", True, "Profitability"),
    "sales_growth_consistency": ("f_sales_growth_consistency", True, "Growth"),
    "profit_growth_consistency": ("f_profit_growth_consistency", True, "Growth"),
    "earnings_margin_stability": ("f_earnings_margin_stability", True, "Profitability"),
    "debt_ratio_delta": ("f_debt_ratio_delta", False, "BalanceSheet"),
    "current_ratio_delta": ("f_current_ratio_delta", True, "BalanceSheet"),
    "interest_coverage_delta": ("f_interest_coverage_delta", True, "BalanceSheet"),
}

TECHNICALS = {  # id -> (column, higher_better, family)
    "mom_20": ("t_mom_20", True, "Technical"),
    "mom_60": ("t_mom_60", True, "Technical"),
    "mom_120": ("t_mom_120", True, "Technical"),
    "price_vs_ma20": ("t_price_vs_ma20", True, "Technical"),
    "price_vs_ma60": ("t_price_vs_ma60", True, "Technical"),
    "ma20_slope": ("t_ma20_slope", True, "Technical"),
    "ma60_slope": ("t_ma60_slope", True, "Technical"),
    "ma20_vs_ma60": ("t_ma20_vs_ma60", True, "Technical"),
    "dist_high_20": ("t_dist_high_20", True, "Technical"),
    "dist_high_60": ("t_dist_high_60", True, "Technical"),
    "dist_high_120": ("t_dist_high_120", True, "Technical"),
    "vol_20": ("t_vol_20", False, "MarketRisk"),
    "vol_60": ("t_vol_60", False, "MarketRisk"),
    "downside_vol_30": ("t_downside_vol_30", False, "MarketRisk"),
    "mdd_60": ("t_mdd_60", True, "MarketRisk"),
    "atr14_norm": ("t_atr14_norm", False, "Technical"),
    "adx14": ("t_adx14", True, "Technical"),
    "rsi14": ("t_rsi14", False, "Technical"),
    "trade_value_30d": ("t_trade_value_30d", True, "Liquidity"),
    "volume_trend_20": ("t_volume_trend_20", True, "Liquidity"),
    "traded_days_ratio_60": ("t_traded_days_ratio_60", True, "Liquidity"),
}

ICHIMOKU = {  # id -> (column, higher_better)
    "price_vs_kumo": ("i_price_vs_kumo", True),
    "cloud_position": ("i_cloud_position", True),
    "tenkan_kijun_distance": ("i_tenkan_kijun_distance", True),
    "tenkan_above_kijun": ("i_tenkan_above_kijun", True),
    "kijun_slope": ("i_kijun_slope", True),
    "tenkan_slope": ("i_tenkan_slope", True),
    "cloud_thickness": ("i_cloud_thickness", False),
    "future_kumo_direction": ("i_future_kumo_direction", True),
    "chikou_confirmation": ("i_chikou_confirmation", True),
    "days_above_cloud": ("i_days_above_cloud", True),
    "days_below_cloud": ("i_days_below_cloud", False),
    "kumo_breakout_recency": ("i_kumo_breakout_recency", True),
    "kijun_distance": ("i_kijun_distance", True),
    "trend_alignment_score": ("i_trend_alignment_score", True),
    "ichimoku_regime": ("i_ichimoku_regime", True),
}

NEG_CONTROL = {"neg_momentum_60": ("n_neg_momentum_60", True),
               "neg_dist_60d_high": ("n_neg_dist_60d_high", True),
               "neg_inverse_vol30": ("n_neg_inverse_vol30", True)}

MIN_SESSIONS = 200  # frozen warm-up requirement for technical/Ichimoku features

DEF_FUND = {
    "sales_growth_accel": "sales_growth_12m(T) - sales_growth_12m(prev_q in [T-100,T-70]d)",
    "profit_growth_accel": "net_profit_growth(T) [else eps_growth] - same at prev_q",
    "operating_margin_delta": "operating_margin(T) - operating_margin(prev_q)",
    "net_margin_delta": "net_margin(T) - net_margin(prev_q)",
    "roe_delta": "roe(T) - roe(prev_q)",
    "sales_growth_consistency": "-std(sales_growth_12m; rows T,prev_q,prev_q2,prev_q3, ddof=0; all required)",
    "profit_growth_consistency": "-std(net_profit_growth/eps_growth over same 4 rows, ddof=0)",
    "earnings_margin_stability": "-std(net_margin over same 4 rows, ddof=0)",
    "debt_ratio_delta": "debt_ratio(T) - debt_ratio(prev_q)",
    "current_ratio_delta": "current_ratio(T) - current_ratio(prev_q)",
    "interest_coverage_delta": "interest_coverage(T) - interest_coverage(prev_q)",
}
DEF_TECH = {
    "mom_20": "adj(T)/adj(T-19 sessions)-1", "mom_60": "adj(T)/adj(T-59)-1",
    "mom_120": "adj(T)/adj(T-119)-1",
    "price_vs_ma20": "adj(T)/MA20-1", "price_vs_ma60": "adj(T)/MA60-1",
    "ma20_slope": "MA20(T)/MA20(T-4)-1", "ma60_slope": "MA60(T)/MA60(T-20)-1",
    "ma20_vs_ma60": "MA20(T)/MA60(T)-1",
    "dist_high_20": "adj(T)/max(adj,20w)-1", "dist_high_60": "adj(T)/max(adj,60w)-1",
    "dist_high_120": "adj(T)/max(adj,120w)-1",
    "vol_20": "std(session returns,20w,ddof=1)", "vol_60": "std(session returns,60w,ddof=1)",
    "downside_vol_30": "std(min(r,0),30w,ddof=1); 0.0 if no down day in window",
    "mdd_60": "min over 60w of adj(t)/cummax(adj)-1 (higher = shallower)",
    "atr14_norm": "Wilder ATR(14) on adjusted H/L/C / adj(T)",
    "adx14": "Wilder ADX(14) on adjusted H/L/C (diagnostic direction)",
    "rsi14": "Wilder RSI(14) on adjusted closes (pre-registered contrarian direction)",
    "trade_value_30d": "mean raw qTotCap (rial traded value) over last 30 sessions",
    "volume_trend_20": "mean zTotTran(5w)/mean(zTotTran(20w)",
    "traded_days_ratio_60": "fraction of last 60 file-records with qTotTran5J>0",
}
DEF_ICH = {
    "price_vs_kumo": "(close-cloud boundary)/close; 0 inside; current cloud = spans from T-26 data",
    "cloud_position": "ABOVE=+1 INSIDE=0 BELOW=-1 vs current cloud",
    "tenkan_kijun_distance": "(Tenkan9-Kijun26)/close",
    "tenkan_above_kijun": "1 if Tenkan>Kijun else 0",
    "kijun_slope": "Kijun(T)/Kijun(T-5)-1", "tenkan_slope": "Tenkan(T)/Tenkan(T-5)-1",
    "cloud_thickness": "|SpanA_T-SpanB_T|/close (current cloud)",
    "future_kumo_direction": "(SpanA_proj-SpanB_proj)/close computed from data at T only",
    "chikou_confirmation": "1 if close(T)>close(T-26) (no future use of the Chikou plot)",
    "days_above_cloud": "fraction of last 26 sessions with close>cloud max",
    "days_below_cloud": "fraction of last 26 sessions with close<cloud min",
    "kumo_breakout_recency": "sessions since last cloud cross (+up/-down, cap +/-52, 0 none)",
    "kijun_distance": "(close-Kijun)/close",
    "trend_alignment_score": "mean[close>Tenkan, Tenkan>Kijun, close>cloud_max, kijun_slope>0]",
    "ichimoku_regime": "ordinal +2..-2 (strong bullish..strong bearish), diagnostic",
}
DEF_NEG = {
    "neg_momentum_60": "CONTROL: mom_60 (old failed family)",
    "neg_dist_60d_high": "CONTROL: dist_high_60 (old failed family)",
    "neg_inverse_vol30": "CONTROL: -std(session returns,30w) (old failed family)",
}

CATEGORY_OF = {}
for c, (f, w, cat) in V1_COMPONENTS.items():
    CATEGORY_OF[c] = cat
for f, (col, hb, cat) in NEW_FUNDAMENTALS.items():
    CATEGORY_OF[f] = cat
for f, (col, hb, fam) in TECHNICALS.items():
    CATEGORY_OF[f] = "MarketRisk" if fam == "MarketRisk" else ("Liquidity" if fam == "Liquidity" else "Technical")
for f, (col, hb) in ICHIMOKU.items():
    CATEGORY_OF[f] = "Ichimoku"


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_frozen_shas() -> dict:
    got = {"panel_parquet": sha256(PANEL_PQ), "panel_jsonl": sha256(PANEL_JSONL),
           "imap": sha256(IMAP), "daily": sha256(DAILY), "repair": sha256(REPAIR),
           "protocol": sha256(HERE / "SCORE_V2_RESEARCH_PROTOCOL.md")}
    exp = {"panel_parquet": SHA_PANEL_PQ, "panel_jsonl": SHA_PANEL_JSONL, "imap": SHA_IMAP,
           "daily": SHA_DAILY, "repair": SHA_REPAIR, "protocol": PROTO_SHA}
    bad = [k for k in exp if got[k] != exp[k]]
    if bad:
        raise SystemExit(f"FROZEN SHA MISMATCH: {bad}")
    return got


def load_panel() -> pd.DataFrame:
    """Certified PIT panel with JSONL ranks/weighted contributions merged on (as_of, symbol)."""
    pq = pd.read_parquet(PANEL_PQ)
    rows = [json.loads(l) for l in PANEL_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    j = pd.DataFrame({"as_of": [r["as_of"] for r in rows], "symbol": [r["symbol"] for r in rows],
                      "ranks": [r["ranks"] for r in rows],
                      "wcontrib": [r["weighted_contributions"] for r in rows],
                      "dq_flags": [r["dq_flags"] for r in rows],
                      "raw_metrics": [r["raw_metrics"] for r in rows]})
    assert len(pq) == len(j) == 12604
    m = pq.merge(j, on=["as_of", "symbol"], how="inner", validate="one_to_one")
    assert len(m) == 12604
    m = m.sort_values(["as_of", "symbol"]).reset_index(drop=True)
    for c in V1_COMPONENTS:
        m["r_" + c] = [r[c] for r in m["ranks"]]
    raw_fields = sorted({f for raws, _, _ in V1_COMPONENTS.values() for f in raws.split("|")})
    for f in raw_fields:
        m["pres_" + f] = [r.get(f) is not None and pd.notna(r.get(f)) for r in m["raw_metrics"]]
    return m


# ---------------------------------------------------------------- market data

def load_reference_data() -> dict:
    """CONFIRMED corporate actions, certified calendar, primary securities (cached)."""
    CACHE.mkdir(exist_ok=True)
    f_ev, f_cal, f_sec = CACHE / "corp_actions_confirmed.parquet", CACHE / "calendar.parquet", CACHE / "securities.parquet"
    if f_ev.exists() and f_cal.exists() and f_sec.exists():
        return {"events": pd.read_parquet(f_ev), "cal": pd.read_parquet(f_cal)["trade_date"].tolist(),
                "sec": pd.read_parquet(f_sec)}
    if not DSN:
        raise RuntimeError("CDF_RESEARCH_DSN_REQUIRED_WHEN_REFERENCE_CACHE_MISSING")
    import psycopg
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT security_id::text, action_date::text, adjustment_factor
                       FROM market.corporate_actions
                       WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
        ev = pd.DataFrame(cur.fetchall(), columns=["security_id", "action_date", "factor"])
        cur.execute("SELECT DISTINCT trade_date::text FROM market.price_observations ORDER BY trade_date")
        cal = pd.DataFrame({"trade_date": [r[0] for r in cur.fetchall()]})
        cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
        sec = pd.DataFrame(cur.fetchall(), columns=["symbol", "security_id", "ins_code"])
    ev.to_parquet(f_ev, index=False)
    cal.to_parquet(f_cal, index=False)
    sec.to_parquet(f_sec, index=False)
    return {"events": ev, "cal": cal["trade_date"].tolist(), "sec": sec}


class MarketData:
    """Raw TSETMC per-symbol arrays + certified causal adjustment chains.

    adj_full(d)   = raw(d) * prod{events e: e > d}                (certified chain)
    adj_asof(T,d) = raw(d) * prod{events e: d < e <= T}           (as-of-T chain)
    Ratio features on windows ending <= T are identical under both (leakage test B).
    """

    def __init__(self, ref: dict, symbols: list[str] | None = None, events_by_sid: dict | None = None):
        self.cal = ref["cal"]
        ev = ref["events"]
        if events_by_sid is None:
            events_by_sid = {}
            for sid, d, f in ev.itertuples(index=False):
                events_by_sid.setdefault(sid, []).append((dt.date.fromisoformat(str(d)), float(f)))
        sec = ref["sec"]
        self.sym2sid = dict(zip(sec["symbol"], sec["security_id"]))
        self.sym2ins = dict(zip(sec["symbol"], sec["ins_code"]))
        self.events = events_by_sid
        self.data: dict[str, dict] = {}
        for sym in (symbols if symbols is not None else list(sec["symbol"])):
            sid = self.sym2sid.get(sym)
            ins = self.sym2ins.get(sym)
            if not sid or not ins:
                continue
            gz = RAW / f"raw_{sym}_{ins}.json.gz"
            if not gz.exists():
                continue
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                doc = json.loads(fh.read())
            recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
            dates, o, h, l, c, vol, tcnt, tval = [], [], [], [], [], [], [], []
            for r in recs:
                s = str(r["dEven"])
                dates.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
                o.append(float(r.get("priceFirst") or 0) or np.nan)
                h.append(float(r.get("priceMax") or 0) or np.nan)
                l.append(float(r.get("priceMin") or 0) or np.nan)
                c.append(float(r["pClosing"]))
                vol.append(float(r.get("zTotTran") or 0))
                tcnt.append(float(r.get("qTotTran5J") or 0))
                tval.append(float(r.get("qTotCap") or 0))
            evs = sorted(self.events.get(sid, []), key=lambda e: e[0])
            # full certified chain
            cf, run, ei = {}, 1.0, len(evs) - 1
            for d in reversed(dates):
                dd = dt.date.fromisoformat(d)
                while ei >= 0 and evs[ei][0] > dd:
                    run *= evs[ei][1]
                    ei -= 1
                cf[d] = run
            self.data[sym] = {
                "dates": dates, "dset": set(dates), "dmap": {d: k for k, d in enumerate(dates)},
                "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c),
                "vol": np.array(vol), "tcnt": np.array(tcnt), "tval": np.array(tval),
                "cf": np.array([cf[d] for d in dates]),
                "sid": sid, "ins": ins,
            }

    def adj(self, sym: str, kind: str = "c") -> np.ndarray:
        d = self.data[sym]
        return d[kind] * d["cf"]

    def asof_factors(self, sym: str, T: str) -> np.ndarray:
        """prod{events e: d < e <= T} per session (as-of-T chain factors)."""
        d = self.data[sym]
        evs = sorted(self.events.get(d["sid"], []), key=lambda e: e[0])
        run, ei = 1.0, len(evs) - 1
        out = np.empty(len(d["dates"]))
        td = dt.date.fromisoformat(T)
        for k in range(len(d["dates"]) - 1, -1, -1):
            dd = dt.date.fromisoformat(d["dates"][k])
            while ei >= 0 and evs[ei][0] > dd:
                if evs[ei][0] <= td:
                    run *= evs[ei][1]
                ei -= 1
            out[k] = run
        return out  # note: computed high->low; events with date > dd consumed in order

    def idx_at(self, sym: str, T: str) -> int:
        """Last session index with date <= T, or -1."""
        ds = self.data[sym]["dates"]
        return bisect_right(ds, T) - 1


# ------------------------------------------------------- forward returns (frozen)

def fwd_factory(md: MarketData):
    """Frozen convention of run_score_deep_audit_v1.fwd (certified full chain).

    entry = first symbol session strictly AFTER signal_date; exit = the session h
    positions later in the certified global calendar; return = adjusted ratio - 1.
    Returns None when the symbol has no session after the signal date, the exit
    calendar date is not a session of the symbol's file, or the horizon exits the
    available calendar — exactly like the certified audit implementation.
    """
    cal = md.cal
    cal_idx = {d: k for k, d in enumerate(cal)}

    def fwd(sym: str, signal_date: str, h: int):
        s = md.data.get(sym)
        if not s:
            return None
        dates = s["dates"]
        i = bisect_right(dates, signal_date)
        if i >= len(dates):
            return None
        entry = dates[i]
        j = cal_idx.get(entry)
        if j is None or j + h >= len(cal):
            return None
        exit_d = cal[j + h]
        k1 = s["dmap"].get(exit_d)
        if k1 is None:
            return None
        return float(s["c"][k1] * s["cf"][k1] / (s["c"][i] * s["cf"][i]) - 1.0)
    return fwd


# ------------------------------------------------------------- feature transforms

def midrank_pct(values: np.ndarray, higher_better: bool = True) -> np.ndarray:
    """Cross-sectional midrank percentile among present (finite) values; NaN -> NaN."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    m = np.isfinite(v)
    n = int(m.sum())
    if n == 0:
        return out
    order = np.argsort(v[m], kind="stable")
    ranks = np.empty(n)
    sv = v[m][order]
    i = 0
    while i < n:
        k = i
        while k + 1 < n and sv[k + 1] == sv[i]:
            k += 1
        mid = (i + k) / 2.0
        ranks[i:k + 1] = mid
        i = k + 1
    pct = ranks / max(n - 1, 1)
    res = np.empty(n)
    res[order] = pct
    out[m] = res if higher_better else (1.0 - res)
    return out


# ------------------------------------------------------------ technical features

def _roll_mean(x: np.ndarray, w: int) -> np.ndarray:
    s = pd.Series(x).rolling(w, min_periods=w).mean().to_numpy()
    return s


def _roll_std(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=w).std(ddof=1).to_numpy()


def _roll_max(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=w).max().to_numpy()


def _roll_min(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=w).min().to_numpy()


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def compute_symbol_technicals(md: MarketData, sym: str) -> pd.DataFrame:
    """All pre-registered technical + Ichimoku features for every session of one symbol.

    Index = session date string. Computed on the certified FULL chain (ratio-invariant
    to events after T for windows ending <= T; proven by tests/test_pit_contract.py).
    """
    d = md.data[sym]
    n = len(d["dates"])
    c = md.adj(sym, "c")
    h = d["h"] * d["cf"]
    l = d["l"] * d["cf"]
    out = {spec[0]: np.full(n, np.nan) for spec in
           list(TECHNICALS.values()) + list(ICHIMOKU.values()) + list(NEG_CONTROL.values())}

    if n >= 2:
        r = np.full(n, np.nan)
        r[1:] = c[1:] / c[:-1] - 1.0
        out["t_mom_20"][19:] = c[19:] / c[:-19] - 1.0
        out["t_mom_60"][59:] = c[59:] / c[:-59] - 1.0
        out["t_mom_120"][119:] = c[119:] / c[:-119] - 1.0
        ma20 = _roll_mean(c, 20)
        ma60 = _roll_mean(c, 60)
        out["t_price_vs_ma20"] = c / ma20 - 1.0
        out["t_price_vs_ma60"] = c / ma60 - 1.0
        out["t_ma20_slope"][4:] = ma20[4:] / ma20[:-4] - 1.0
        out["t_ma60_slope"][20:] = ma60[20:] / ma60[:-20] - 1.0
        out["t_ma20_vs_ma60"] = ma20 / ma60 - 1.0
        for w, key in ((20, "t_dist_high_20"), (60, "t_dist_high_60"), (120, "t_dist_high_120")):
            out[key][w - 1:] = c[w - 1:] / _roll_max(c, w)[w - 1:] - 1.0
        out["t_vol_20"] = _roll_std(r, 20)
        out["t_vol_60"] = _roll_std(r, 60)
        dn = np.where(np.isfinite(r), np.minimum(r, 0.0), np.nan)
        dvol = _roll_std(dn, 30)
        down_ct = pd.Series((r < 0).astype(float)).rolling(30, min_periods=30).sum().to_numpy()
        out["t_downside_vol_30"] = np.where(down_ct == 0, 0.0, dvol)  # std of min(r,0); 0.0 if no down day
        cm = np.maximum.accumulate(np.where(np.isfinite(c), c, -np.inf))
        dd = c / cm - 1.0
        out["t_mdd_60"][59:] = _roll_min(dd, 60)[59:]
        out["n_neg_momentum_60"] = out["t_mom_60"]
        out["n_neg_dist_60d_high"] = out["t_dist_high_60"]
        vol30 = _roll_std(r, 30)
        out["n_neg_inverse_vol30"] = -vol30
        # volume / liquidity (raw PIT fields)
        out["t_trade_value_30d"] = _roll_mean(d["tval"], 30)
        m5, m20 = _roll_mean(d["vol"], 5), _roll_mean(d["vol"], 20)
        out["t_volume_trend_20"] = m5 / m20
        traded = (d["tcnt"] > 0).astype(float)
        out["t_traded_days_ratio_60"] = pd.Series(traded).rolling(60, min_periods=60).mean().to_numpy()
        # ATR / RSI / ADX (Wilder, adjusted H/L/C)
        pc = np.empty(n)
        pc[0] = np.nan
        pc[1:] = c[:-1]
        tr = np.nanmax(np.stack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
        atr = _wilder(tr, 14)
        out["t_atr14_norm"] = atr / c
        delta = np.diff(c, prepend=c[0])
        up = np.where(delta > 0, delta, 0.0)
        dn_ = np.where(delta < 0, -delta, 0.0)
        ru, rd = _wilder(up, 14), _wilder(dn_, 14)
        rs = ru / np.where(rd == 0, np.nan, rd)
        out["t_rsi14"] = 100.0 - 100.0 / (1.0 + rs)
        with np.errstate(invalid="ignore", divide="ignore"):
            plus_dm = np.where((delta > 0) & (delta > -np.roll(delta, 1)), delta, 0.0)
            minus_dm = np.where((delta < 0) & (-delta > np.roll(delta, 1)), -delta, 0.0)
        plus_dm[0] = minus_dm[0] = 0.0
        pdi = 100.0 * _wilder(plus_dm, 14) / atr
        mdi = 100.0 * _wilder(minus_dm, 14) / atr
        dx = 100.0 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
        out["t_adx14"] = _wilder(dx, 14)
        # ---------------- Ichimoku (9/26/52, displacement 26) ----------------
        tenkan = ( _roll_max(h, 9) + _roll_min(l, 9)) / 2.0
        kijun = ( _roll_max(h, 26) + _roll_min(l, 26)) / 2.0
        midB52 = ( _roll_max(h, 52) + _roll_min(l, 52)) / 2.0
        sa_plot = np.full(n, np.nan)
        sb_plot = np.full(n, np.nan)
        if n > 26:
            sa_plot[26:] = (tenkan[:n - 26] + kijun[:n - 26]) / 2.0
            sb_plot[26:] = midB52[:n - 26]
        cl_max = np.nanmax(np.stack([sa_plot, sb_plot]), axis=0)
        cl_min = np.nanmin(np.stack([sa_plot, sb_plot]), axis=0)
        kumo_valid = np.isfinite(cl_max) & np.isfinite(cl_min)
        # strict cloud comparisons made tie-robust (eps=1e-12 relative): an exact
        # touch classifies as INSIDE, deterministically, independent of the chain
        # multiplication order (leakage test B requires chain-invariance).
        EPS = 1e-12
        above = c > cl_max * (1.0 + EPS)
        below = c < cl_min * (1.0 - EPS)
        above[~kumo_valid] = False
        below[~kumo_valid] = False
        out["i_price_vs_kumo"] = np.where(
            above, (c - cl_max) / c, np.where(below, (c - cl_min) / c, 0.0))
        out["i_price_vs_kumo"][~kumo_valid] = np.nan
        out["i_cloud_position"] = np.where(above, 1.0, np.where(below, -1.0, 0.0))
        out["i_cloud_position"][~(np.isfinite(cl_max) & np.isfinite(cl_min))] = np.nan
        out["i_tenkan_kijun_distance"] = (tenkan - kijun) / c
        tk_above = tenkan > kijun * (1.0 + EPS)
        tk_below = tenkan < kijun * (1.0 - EPS)
        out["i_tenkan_above_kijun"] = np.where(tk_above, 1.0, np.where(tk_below, 0.0, 0.0))
        out["i_tenkan_above_kijun"][~np.isfinite(tenkan) | ~np.isfinite(kijun)] = np.nan
        out["i_kijun_slope"][5:] = kijun[5:] / kijun[:-5] - 1.0
        out["i_tenkan_slope"][5:] = tenkan[5:] / tenkan[:-5] - 1.0
        out["i_cloud_thickness"] = np.abs(sa_plot - sb_plot) / c
        sa_proj = (tenkan + kijun) / 2.0
        out["i_future_kumo_direction"] = (sa_proj - midB52) / c
        chik = np.zeros(n)
        chik[26:] = (c[26:] > c[:-26] * (1.0 + EPS)).astype(float)
        chik[(~np.isfinite(c)) | (np.arange(n) < 26)] = np.nan
        out["i_chikou_confirmation"] = chik
        da = pd.Series(above.astype(float)).rolling(26, min_periods=26).mean().to_numpy()
        db = pd.Series(below.astype(float)).rolling(26, min_periods=26).mean().to_numpy()
        valid = np.isfinite(cl_max) & np.isfinite(cl_min)
        out["i_days_above_cloud"] = np.where(valid, da, np.nan)
        out["i_days_below_cloud"] = np.where(valid, db, np.nan)
        # breakout recency: last state change into/through the cloud within 52 sessions
        state = np.where(above, 1, np.where(below, -1, 0))
        state[~valid] = 99  # unknown
        rec = np.full(n, np.nan)
        for t in range(26, n):
            if state[t] == 99:
                continue
            lo = max(0, t - 52)
            found = 0.0
            for k in range(t - 1, lo - 1, -1):
                if state[k] == 99:
                    break
                if state[k] != state[t] and state[k] != 0 and state[t] != 0:
                    found = float(t - k) if state[t] > 0 else -float(t - k)
                    break
                if state[k] != state[t] and state[t] == 0 and state[k] != 0:
                    found = 0.5 * float(t - k) if state[k] > 0 else -0.5 * float(t - k)
                    break
            rec[t] = found
        out["i_kumo_breakout_recency"] = rec
        out["i_kijun_distance"] = (c - kijun) / c
        ks = np.zeros(n)
        ks[5:] = kijun[5:] / kijun[:-5] - 1.0
        ks[~np.isfinite(kijun)] = np.nan
        align = ((c > tenkan * (1.0 + EPS)).astype(float) + tk_above.astype(float)
                 + above.astype(float) + np.where(np.isfinite(ks), ks > 0, 0.0)) / 4.0
        align[~(np.isfinite(tenkan) & np.isfinite(kijun) & valid)] = np.nan
        out["i_trend_alignment_score"] = align
        regime = np.where(above & tk_above & np.isfinite(ks), 2.0,
                          np.where(above, 1.0, np.where(below, -1.0, 0.0)))
        regime = np.where(above & tk_above & ~(ks > 0), 1.0, regime)
        regime = np.where(below & (tenkan < kijun) & (ks < 0), -2.0, regime)
        regime[~valid] = np.nan
        out["i_ichimoku_regime"] = regime

    return pd.DataFrame(out, index=d["dates"])


# ----------------------------------------------------------------- IC machinery

def ics(scores_by_date: dict, rets_by_date: dict, min_pairs: int = 5):
    per = {}
    for d in scores_by_date:
        pairs = [(s, r) for s, r in zip(scores_by_date[d], rets_by_date[d])
                 if s is not None and r is not None and np.isfinite(s) and np.isfinite(r)]
        if len(pairs) >= min_pairs:
            ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if ic is not None and np.isfinite(ic):
                per[d] = ic
    vals = list(per.values())
    return per, {"mean": float(np.mean(vals)) if vals else None,
                 "median": float(np.median(vals)) if vals else None,
                 "positive_fraction": float(np.mean([v > 0 for v in vals])) if vals else None,
                 "n_dates": len(vals)}


def block_len(dates, months):
    ds = [dt.date.fromisoformat(d) for d in dates]
    best = 1
    for i in range(len(ds)):
        j = i
        while j + 1 < len(ds) and (ds[j + 1] - ds[i]).days <= months * 30.44:
            j += 1
        best = max(best, j - i + 1)
    return best


def boot(per_date: dict, dates_order: list, block: int, rng, n_boot: int = B):
    vals = np.array([per_date[d] for d in dates_order if d in per_date], dtype=float)
    n = len(vals)
    if n == 0:
        return None
    nb = int(np.ceil(n / block))
    stats = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        for _ in range(nb):
            s = int(rng.integers(0, n))
            idx.extend((s + k) % n for k in range(block))
        stats[b] = vals[np.array(idx[:n])].mean()
    return {"mean": float(vals.mean()), "ci_lower": float(np.percentile(stats, 2.5)),
            "ci_upper": float(np.percentile(stats, 97.5))}


def qspread(score_rows: dict, h_unused=None, min_rows: int = 10):
    per, means = {}, {q: [] for q in range(1, 6)}
    for d, sr in score_rows.items():
        pairs = [(s, r) for s, r in sr if s is not None and r is not None
                 and np.isfinite(s) and np.isfinite(r)]
        if len(pairs) < min_rows:
            continue
        pairs.sort(key=lambda x: x[0])
        n = len(pairs)
        rm = []
        for qi in range(5):
            q = pairs[qi * n // 5:(qi + 1) * n // 5]
            rm.append(float(np.mean([r for _, r in q])))
        if None in rm or any(not np.isfinite(x) for x in rm):
            continue
        per[d] = rm[4] - rm[0]
        for qi in range(5):
            means[qi + 1].append(rm[qi])
    return (per, {q: (float(np.mean(v)) if v else None) for q, v in means.items()},
            {"mean_spread": float(np.mean(list(per.values()))) if per else None,
             "n_dates": len(per)})


# ------------------------------------------------------------------- frozen split

def split_dates(dates: list[str]) -> dict:
    dev = [d for d in dates if d <= DEV_END]
    val = [d for d in dates if VAL_START <= d <= VAL_END]
    hold = [d for d in dates if d >= HOLD_START]
    assert len(dev) == 42 and len(val) == 6 and len(hold) == 15, (len(dev), len(val), len(hold))
    assert dev[-1] < val[0] and val[-1] < hold[0]
    return {"development": dev, "validation": val, "locked_holdout": hold}


# ------------------------------------------------------------ portfolio (certified)

def load_portfolio_engine():
    sys.path.insert(0, str(ROOT / "portfolio_research"))
    import repair_accounting_v1 as RA  # noqa: F401  (sha-verified frozen engine)
    return RA


def tradability_keys() -> set:
    df = pd.read_parquet(DAILY, columns=["date", "symbol", "security_traded"])
    df = df[df["security_traded"] == True]  # noqa: E712
    return set(zip(df["date"].astype(str), df["symbol"]))
